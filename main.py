# -*- coding: utf-8 -*-
"""
Zapretik v1.0.0 — умная консольная утилита для обхода DPI-блокировок
Discord и YouTube в Windows.

Принцип работы:
  1. Скрипт является "обёрткой" (wrapper) над бинарником winws.exe
     из проекта bol-van/zapret (обход DPI с помощью WinDivert).
  2. При первом запуске автоматически скачивает готовый бандл
     (winws.exe, WinDivert.dll, WinDivert64.sys, стратегии, списки
     доменов) с последнего релиза GitHub и распаковывает в рабочую папку.
  3. Предоставляет интерактивное меню для выбора стратегии обхода.
  4. Требует права администратора (UAC), так как WinDivert — это драйвер
     уровня ядра: без остановки процесса WinDivert фильтры сами снимутся.

Установка зависимостей (выполните один раз):
    pip install rich requests

Запуск:
    python main.py
"""

from __future__ import annotations

import ctypes
import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence

import requests
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeRemainingColumn
from rich.table import Table

# --------------------------------------------------------------------------- #
#  Константы и глобальные настройки
# --------------------------------------------------------------------------- #

VERSION = "1.0.0"

# Рабочая папка — каталог, где лежит main.py
BASE_DIR = Path(sys.argv[0]).resolve().parent
# Каталог, куда распаковывается ядро (winws.exe, WinDivert.dll и т.д.)
BIN_DIR = BASE_DIR / "bin"
# Каталог со списками доменов/IP для hostlist-фильтров
LISTS_DIR = BASE_DIR / "lists"
# Файл логов
LOG_FILE = BASE_DIR / "zapretik.log"

# --- Источник ядра zapret ------------------------------------------------ #
# В релизах bol-van/zapret лежат только исходные коды, поэтому Windows-
# бинарники (winws.exe + WinDivert) удобнее брать из готового бандла
# flowseal/zapret-discord-youtube: в его релизе есть всё нужное сразу.
CORE_REPO = "flowseal/zapret-discord-youtube"
GITHUB_API_LATEST = f"https://api.github.com/repos/{CORE_REPO}/releases/latest"
ZIP_URL_TEMPLATE = (
    f"https://github.com/{CORE_REPO}/releases/download/{{tag}}/"
    f"zapret-discord-youtube-{{tag}}.zip"
)
GITHUB_HEADERS = {"User-Agent": "zapretik", "Accept": "application/vnd.github+json"}

WINWS_NAME = "winws.exe"

# --------------------------------------------------------------------------- #
# Стратегии запуска winws.exe
#
# ВАЖНО: winws.exe — это Windows-версия nfqws, поэтому у него СВОИ флаги.
# Параметры вроде "--wsize", "--split-pos", "--fake-tls" из Linux-версии
# к winws НЕ применимы. Здесь используются реальные флаги winws из проекта
# flowseal/zapret-discord-youtube. Несколько фильтров в одной стратегии
# разделяются ключом "--new".
# --------------------------------------------------------------------------- #

# Общий префикс: "широкое окно" — ловим нужные порты.
WF_COMMON = [
    "--wf-tcp=80,443,2053,2083,2087,2096,8443",
    "--wf-udp=443,19294-19344,50000-50100",
]


def _bin(name: str) -> str:
    """Абсолютный путь к файлу из каталога bin/ (для аргументов winws)."""
    return str(BIN_DIR / name)


def _lst(name: str) -> str:
    """Абсолютный путь к списку доменов из каталога lists/."""
    return str(LISTS_DIR / name)


def _hostlist(path: str) -> str:
    """Аргумент --hostlist для winws."""
    return f"--hostlist={path}"


def _hostlist_excl(path: str) -> str:
    """Аргумент --hostlist-exclude для winws."""
    return f"--hostlist-exclude={path}"


def _chain_discord_media(dpi: Sequence[str]) -> List[str]:
    """Цепочка для трафика discord.media на нестандартных портах."""
    return [
        "--filter-tcp=2053,2083,2087,2096,8443",
        "--hostlist-domains=discord.media",
        *list(dpi),
        "--new",
    ]


def _chain_google(dpi: Sequence[str]) -> List[str]:
    """Цепочка для YouTube/Google на TCP 443."""
    return [
        "--filter-tcp=443",
        _hostlist(_lst("list-google.txt")),
        "--ip-id=zero",
        *list(dpi),
        "--new",
    ]


def _chain_general(dpi: Sequence[str]) -> List[str]:
    """Цепочка для остальных доменов из общего списка (идёт последней)."""
    return [
        "--filter-tcp=80,443",
        _hostlist(_lst("list-general.txt")),
        _hostlist_excl(_lst("list-exclude.txt")),
        *list(dpi),
    ]


def _common_udp() -> List[str]:
    """Общие UDP-цепочки (QUIC Discord/YouTube + голосовые каналы STUN)."""
    return [
        # UDP-трафик Discord/YouTube (QUIC) — подмена пакетов
        "--filter-udp=443",
        _hostlist(_lst("list-general.txt")),
        _hostlist_excl(_lst("list-exclude.txt")),
        "--dpi-desync=fake",
        "--dpi-desync-repeats=6",
        f"--dpi-desync-fake-quic={_bin('quic_initial_www_google_com.bin')}",
        "--new",
        # Голосовые UDP-каналы Discord (STUN) — подмена пакетов
        "--filter-udp=19294-19344,50000-50100",
        "--filter-l7=discord,stun",
        "--dpi-desync=fake",
        f"--dpi-desync-fake-discord={_bin('ACTIVE_DISCORD_UDP.bin')}",
        f"--dpi-desync-fake-stun={_bin('ACTIVE_DISCORD_UDP.bin')}",
        "--dpi-desync-repeats=6",
        "--new",
    ]


# Библиотека стратегий из проекта flowseal/zapret-discord-youtube.
# Каждая стратегия = общий UDP-блок + три TCP-цепочки (discord.media,
# YouTube/Google, общий список). Цепочки различаются только параметрами
# десинхронизации DPI, поэтому сведены в компактные списки ниже.
_MULTISPLIT_681 = [
    "--dpi-desync=multisplit",
    "--dpi-desync-split-seqovl=681",
    "--dpi-desync-split-pos=1",
    f"--dpi-desync-split-seqovl-pattern={_bin('tls_clienthello_www_google_com.bin')}",
]

_FAKEDSPLIT_GOOGLE = [
    "--dpi-desync=fake,fakedsplit",
    "--dpi-desync-repeats=6",
    "--dpi-desync-fooling=ts",
    "--dpi-desync-fakedsplit-pattern=0x00",
    f"--dpi-desync-fake-tls={_bin('tls_clienthello_www_google_com.bin')}",
]

_FAKEDSPLIT_GENERAL = _FAKEDSPLIT_GOOGLE + [
    f"--dpi-desync-fake-http={_bin('tls_clienthello_max_ru.bin')}",
]

_MULTISPLIT_652 = [
    "--dpi-desync=multisplit",
    "--dpi-desync-split-seqovl=652",
    "--dpi-desync-split-pos=2",
    f"--dpi-desync-split-seqovl-pattern={_bin('tls_clienthello_www_google_com.bin')}",
]

_HOSTFAKESPLIT_GOOGLE = [
    "--dpi-desync=fake,hostfakesplit",
    "--dpi-desync-fake-tls-mod=rnd,dupsid,sni=www.google.com",
    "--dpi-desync-hostfakesplit-mod=host=www.google.com,altorder=1",
    "--dpi-desync-fooling=ts",
]

_HOSTFAKESPLIT_YARU = [
    "--dpi-desync=fake,hostfakesplit",
    "--dpi-desync-fake-tls-mod=rnd,dupsid,sni=ya.ru",
    "--dpi-desync-hostfakesplit-mod=host=ya.ru,altorder=1",
    "--dpi-desync-fooling=ts",
    f"--dpi-desync-fake-http={_bin('tls_clienthello_max_ru.bin')}",
]

_BADSEQ_1000 = [
    "--dpi-desync=fake,multisplit",
    "--dpi-desync-repeats=6",
    "--dpi-desync-fooling=badseq",
    "--dpi-desync-badseq-increment=1000",
    f"--dpi-desync-fake-tls={_bin('tls_clienthello_www_google_com.bin')}",
]

_BADSEQ_1000_GENERAL = _BADSEQ_1000 + [
    f"--dpi-desync-fake-http={_bin('tls_clienthello_max_ru.bin')}",
]

_SIMPLE_BADSEQ_2 = [
    "--dpi-desync=fake",
    "--dpi-desync-repeats=6",
    "--dpi-desync-fooling=badseq",
    "--dpi-desync-badseq-increment=2",
    f"--dpi-desync-fake-tls={_bin('tls_clienthello_www_google_com.bin')}",
]

_SIMPLE_BADSEQ_2_GENERAL = _SIMPLE_BADSEQ_2 + [
    f"--dpi-desync-fake-http={_bin('tls_clienthello_max_ru.bin')}",
]

_EXP_DISCORD = [
    "--dpi-desync=fake,multisplit",
    "--dpi-desync-split-seqovl=681",
    "--dpi-desync-split-pos=1",
    "--dpi-desync-fooling=ts",
    "--dpi-desync-repeats=8",
    f"--dpi-desync-split-seqovl-pattern={_bin('tls_clienthello_www_google_com.bin')}",
    f"--dpi-desync-fake-tls={_bin('tls_clienthello_www_google_com.bin')}",
]

_EXP_GOOGLE = [
    "--dpi-desync=hostfakesplit",
    "--dpi-desync-fooling=ts",
    "--dpi-desync-hostfakesplit-mod=host=www.google.com",
]

_EXP_GENERAL = [
    "--dpi-desync=fake,multisplit",
    "--dpi-desync-split-seqovl=480",
    "--dpi-desync-split-pos=1",
    "--dpi-desync-fooling=ts",
    "--dpi-desync-repeats=4",
    f"--dpi-desync-split-seqovl-pattern={_bin('stun2.bin')}",
    f"--dpi-desync-fake-tls={_bin('tls_clienthello_max_ru.bin')}",
    f"--dpi-desync-fake-http={_bin('tls_clienthello_max_ru.bin')}",
]


STRATEGIES: Dict[str, Dict[str, Sequence[str]]] = {
    "1": {
        "name": "Discord + YouTube (Стандарт)",
        "desc": "Сбалансированный multisplit-обход для Discord и YouTube (general.bat).",
        "args": WF_COMMON
        + _common_udp()
        + _chain_discord_media(_MULTISPLIT_681)
        + _chain_google(_MULTISPLIT_681)
        + _chain_general([
            "--dpi-desync=multisplit",
            "--dpi-desync-split-seqovl=568",
            "--dpi-desync-split-pos=1",
            f"--dpi-desync-split-seqovl-pattern={_bin('tls_clienthello_4pda_to.bin')}",
        ]),
    },
    "2": {
        "name": "Только YouTube (Агрессивный)",
        "desc": "FAKE TLS AUTO + рассинхронизация пакетов (макс. маскировка).",
        "args": WF_COMMON
        + [
            "--filter-tcp=443",
            _hostlist(_lst("list-google.txt")),
            "--ip-id=zero",
            "--dpi-desync=fake,multidisorder",
            "--dpi-desync-split-pos=1,midsld",
            "--dpi-desync-repeats=11",
            "--dpi-desync-fooling=badseq",
            "--dpi-desync-fake-tls=0x00000000",
            "--dpi-desync-fake-tls=!",
            "--dpi-desync-fake-tls-mod=rnd,dupsid,sni=www.google.com",
        ],
    },
    "3": {
        "name": "Безопасный режим (Медленный)",
        "desc": "Только фрагментация TLS без фейковых пакетов.",
        "args": WF_COMMON
        + [
            "--filter-tcp=443",
            _hostlist(_lst("list-general.txt")),
            _hostlist(_lst("list-google.txt")),
            _hostlist_excl(_lst("list-exclude.txt")),
            "--dpi-desync=multisplit",
            "--dpi-desync-split-seqovl=568",
            "--dpi-desync-split-pos=1",
        ],
    },
    "4": {
        "name": "ALT1 (fake + fakedsplit)",
        "desc": "Фейк + разделение пакетов на фрагменты (general (ALT).bat).",
        "args": WF_COMMON
        + _common_udp()
        + _chain_discord_media(_FAKEDSPLIT_GOOGLE)
        + _chain_google(_FAKEDSPLIT_GOOGLE)
        + _chain_general(_FAKEDSPLIT_GENERAL),
    },
    "5": {
        "name": "ALT2 (multisplit pos=2)",
        "desc": "Мультисплит с разделением на 2 позиции (general (ALT2).bat).",
        "args": WF_COMMON
        + _common_udp()
        + _chain_discord_media(_MULTISPLIT_652)
        + _chain_google(_MULTISPLIT_652)
        + _chain_general(_MULTISPLIT_652),
    },
    "6": {
        "name": "ALT3 (hostfakesplit)",
        "desc": "Подмена хоста в ClientHello (general (ALT3).bat).",
        "args": WF_COMMON
        + _common_udp()
        + _chain_discord_media(_HOSTFAKESPLIT_GOOGLE)
        + _chain_google(_HOSTFAKESPLIT_GOOGLE)
        + _chain_general(_HOSTFAKESPLIT_YARU),
    },
    "7": {
        "name": "ALT4 (fake + badseq)",
        "desc": "Фейк + битый порядок пакетов +1000 (general (ALT4).bat).",
        "args": WF_COMMON
        + _common_udp()
        + _chain_discord_media(_BADSEQ_1000)
        + _chain_google(_BADSEQ_1000)
        + _chain_general(_BADSEQ_1000_GENERAL),
    },
    "8": {
        "name": "SIMPLE FAKE",
        "desc": "Простой фейк + битый порядок +2 (general (SIMPLE FAKE ALT).bat).",
        "args": WF_COMMON
        + _common_udp()
        + _chain_discord_media(_SIMPLE_BADSEQ_2)
        + _chain_google(_SIMPLE_BADSEQ_2)
        + _chain_general(_SIMPLE_BADSEQ_2_GENERAL),
    },
    "9": {
        "name": "EXP (hostfakesplit+multisplit)",
        "desc": "Экспериментальная смесь hostfakesplit и multisplit (general (EXP).bat).",
        "args": WF_COMMON
        + _common_udp()
        + _chain_discord_media(_EXP_DISCORD)
        + _chain_google(_EXP_GOOGLE)
        + _chain_general(_EXP_GENERAL),
    },
}


# --------------------------------------------------------------------------- #
# Глобальные объекты

console = Console(highlight=False)
logger = logging.getLogger("zapretik")

# Активный дочерний процесс winws (нужен для пункта меню "Стоп" и Ctrl+C).
win_proc: Optional[subprocess.Popen[str]] = None


# --------------------------------------------------------------------------- #
# Логирование: файл + цветная консоль
# --------------------------------------------------------------------------- #

class ConsoleLogHandler(logging.Handler):
    """Выводит записи лога в консоль через rich с цветовой маркировкой."""

    # Цвет для каждого уровня важности
    LEVEL_COLORS = {
        logging.DEBUG: "dim",
        logging.INFO: "cyan",
        logging.WARNING: "yellow",
        logging.ERROR: "bold red",
        logging.CRITICAL: "bold white on red",
    }

    def emit(self, record: logging.LogRecord) -> None:
        try:
            color = self.LEVEL_COLORS.get(record.levelno, "white")
            console.print(f"[{color}]{record.getMessage()}[/{color}]")
        except Exception:
            self.handleError(record)


def setup_logging() -> None:
    """Настраиваем логирование: цветная консоль + файл zaprerik.log."""
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%H:%M:%S")

    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = ConsoleLogHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)


# --------------------------------------------------------------------------- #
# Проверка прав администратора и перезапуск с UAC
# --------------------------------------------------------------------------- #

def check_admin() -> bool:
    """True, если процесс запущен с правами администратора."""
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> None:
    """Перезапускаем скрипт от имени администратора через UAC-запрос."""
    if "--elevated" in sys.argv:
        console.print("[bold red]Не удалось получить права администратора.[/bold red]")
        return

    logger.info("Запрашиваем права администратора (UAC)...")
    params = f'"{sys.argv[0]}" {" ".join(sys.argv[1:])} --elevated'
    ret = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, params, None, 1
    )
    if ret > 32:
        sys.exit(0)  # исходный (непривилегированный) процесс завершаем
    console.print("[bold red]UAC-запрос отклонён или запуск не удался.[/bold red]")


# --------------------------------------------------------------------------- #
# Авто-скачивание и установка ядра
# --------------------------------------------------------------------------- #

def _looks_complete() -> bool:
    """True, если минимальный набор файлов ядра уже установлен."""
    return (BIN_DIR / "winws.exe").exists() and (BIN_DIR / "WinDivert.dll").exists()


def humanize_size(num: float) -> str:
    """Превращает число байт в человекочитаемую строку."""
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024:
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} TB"


def download_file(url: str, dest: Path, *, is_asset: bool = False) -> None:
    """Скачивает файл по URL в dest, показывая индикатор прогресса.

    is_asset=True: URL ведёт на ассет релиза через API GitHub, поэтому
    требуется заголовок Accept: application/octet-stream, иначе GitHub
    вернёт описание ассета в JSON вместо самого файла.
    """
    headers = dict(GITHUB_HEADERS)
    if is_asset:
        headers["Accept"] = "application/octet-stream"
    with requests.get(url, stream=True, timeout=(20, 60), headers=headers) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length", 0))
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.fields[got]} из {task.fields[all]}"),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(
                Path(url).name, total=total, got="0 B", all=humanize_size(total)
            )
            written = 0
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
                        written += len(chunk)
                        progress.update(
                            task, completed=written,
                            got=humanize_size(written), all=humanize_size(total),
                        )


def _safe_extract(zipf: zipfile.ZipFile, dest: Path) -> None:
    """Извлечение архива с защитой от path traversal."""
    dest = dest.resolve()
    for member in zipf.infolist():
        target = (dest / member.filename).resolve()
        if member.filename.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
            continue
        if not target.is_relative_to(dest):
            logger.warning("Пропущен подозрительный путь в архиве: %s", member.filename)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipf.open(member) as src, open(target, "wb") as dst:
            dst.write(src.read())


def _copy_bundle(bundle_dir: Path) -> None:
    """Копирует bin/ и lists/ из распакованного бандла в рабочую папку."""
    BIN_DIR.mkdir(parents=True, exist_ok=True)
    LISTS_DIR.mkdir(parents=True, exist_ok=True)

    # Найти каталог, где лежит winws.exe
    exe_files = list(bundle_dir.rglob("winws.exe"))
    if not exe_files:
        raise FileNotFoundError("В архиве не найден winws.exe")
    core_src = exe_files[0].parent

    # Копируем весь каталог bin/ рекурсивно
    for src_file in core_src.rglob("*"):
        if src_file.is_file():
            rel = src_file.relative_to(core_src)
            dst = BIN_DIR / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src_file.read_bytes())

    # Копируем списки доменов из соседнего каталога lists/
    src_lists = core_src.parent / "lists"
    if not src_lists.is_dir():
        src_lists = core_src / "lists"
    if src_lists.is_dir():
        for txt in src_lists.glob("*.txt"):
            (LISTS_DIR / txt.name).write_bytes(txt.read_bytes())

    logger.info("Ядро установлено в %s", BIN_DIR)


def download_core() -> None:
    """Автоустановка ядра: скачать релиз с GitHub, распаковать, скопировать."""
    if _looks_complete():
        logger.info("Ядро уже установлено (winws.exe + WinDivert.dll найдены).")
        return

    logger.info("Ядро не обнаружено. Начинаем автоматическую загрузку...")
    try:
        logger.info("Запрашиваем последний релиз %s...", CORE_REPO)
        resp = requests.get(GITHUB_API_LATEST, headers=GITHUB_HEADERS, timeout=20)
        resp.raise_for_status()
        release = resp.json()
        tag = release["tag_name"]

        # Формируем список кандидатов для скачивания и пробуем их по очереди:
        #   1) ассет релиза напрямую через api.github.com (обходит блокировку
        #      github.com — DPI обычно не трогает этот домен);
        #   2) обычный URL github.com/releases/download/...
        # При нестабильном интернете один из источников обязательно сработает.
        zip_asset = next(
            (a for a in release["assets"] if a["name"].lower().endswith(".zip")),
            None,
        )
        if zip_asset is None:
            raise RuntimeError("В релизе не найден zip-ассет")
        download_sources: List[tuple[str, bool]] = [
            (zip_asset["url"], True),                    # через API (oktet-stream)
            (ZIP_URL_TEMPLATE.format(tag=tag), False),   # напрямую с github.com
        ]

        with tempfile.TemporaryDirectory(prefix="zapretik_") as tmp:
            tmp_p = Path(tmp)
            zip_path = tmp_p / "bundle.zip"

            # Пробуем каждый источник, пока не скачается целый файл
            ok = False
            for url, is_asset in download_sources:
                try:
                    logger.info("Пробуем источник: %s", url)
                    download_file(url, zip_path, is_asset=is_asset)
                    if zip_path.stat().st_size > 0:
                        ok = True
                        break
                except Exception as exc:
                    logger.warning("Источник недоступен: %s", exc)
                    if zip_path.exists():
                        zip_path.unlink()
            if not ok:
                raise RuntimeError("Все источники скачивания недоступны")

            extract = tmp_p / "unzipped"
            extract.mkdir(exist_ok=True)
            with zipfile.ZipFile(zip_path) as zf:
                _safe_extract(zf, extract)

            _copy_bundle(extract)
        logger.info("Установка ядра завершена успешно.")
    except Exception as exc:
        logger.error("Не удалось выполнить авто-загрузку: %s", exc)
        console.print(
            f"[bold yellow]Настройте вручную: положите winws.exe и WinDivert.dll "
            f"в каталог {BIN_DIR}[/bold yellow]"
        )
        input("Нажмите Enter, чтобы вернуться в меню...")
        return


# --------------------------------------------------------------------------- #
# Запуск и остановка стратегий
# --------------------------------------------------------------------------- #

def run_strategy(key: str, strategy: Dict[str, Sequence[str]]) -> None:
    """Запускает winws.exe с аргументами выбранной стратегии."""
    global win_proc

    name = strategy["name"]
    console.print()
    console.print(f"[bold green]> Запуск стратегии:[/bold green] {name}")

    if not (BIN_DIR / "winws.exe").exists():
        logger.error("Ядро отсутствует. Запустите автозагрузку в меню (пункт 9).")
        input("Нажмите Enter, чтобы вернуться в меню...")
        return

    cmd_line = [str(BIN_DIR / "winws.exe"), *[str(a) for a in strategy["args"]]]
    logger.info("Запуск процесса: %s", " ".join(cmd_line))

    try:
        proc = subprocess.Popen(
            cmd_line,
            start_new_session=True,
            stderr=None,
        )
    except Exception as exc:
        logger.error("Не удалось запустить winws: %s", exc)
        input("Нажмите Enter, чтобы вернуться в меню...")
        return

    win_proc = proc
    logger.info("Процесс запущен (PID=%s). Стратегия активна.", proc.pid)
    console.print(
        "[dim]Для остановки обхода нажмите Ctrl+C или выберите пункт «Остановить».[/dim]"
    )

    # Ждём, пока пользователь не остановит процесс (пунктом меню или Ctrl+C).
    try:
        while win_proc is not None and win_proc.poll() is None:
            time.sleep(0.5)
    except KeyboardInterrupt:
        handle_interrupt()  # дежурная обработка (обычно делает отмена sts)
        return

    if win_proc is not None:
        code = win_proc.returncode
        win_proc = None
        logger.info("Процесс winws завершён (код: %s).", code)


def stop_service() -> None:
    """Корректно останавливает активный процесс winws (снимает WinDivert)."""
    global win_proc

    if win_proc is None:
        logger.warning("Активный процесс не найден — ничего останавливать.")
        return

    proc = win_proc
    logger.info("Останавливаем процесс (PID=%s)...", proc.pid)
    try:
        if proc.poll() is None:
            proc.terminate()  # в Windows это TerminateProcess
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Процесс не завершился за 5 сек — принудительно.")
                proc.kill()
                proc.wait(timeout=3)
    except Exception as exc:
        logger.error("Ошибка при остановке процесса: %s", exc)

    win_proc = None
    logger.info("Обход остановлен, драйвер WinDivert снят.")


# --------------------------------------------------------------------------- #
# Ctrl+C и интерфейс
# --------------------------------------------------------------------------- #

def handle_interrupt() -> None:
    """Останавливает активный процесс корректно при Ctrl+C."""
    console.print("\n[bold yellow]Ctrl+C — останавливаем обход...[/bold yellow]")
    stop_service()
    logger.info("Zapretik завершён по Ctrl+C.")
    sys.exit(0)


def print_banner() -> None:
    banner = (
        f"[bold magenta]Zapretik[/bold magenta] v{VERSION} — обход DPI для "
        "Discord и YouTube\n"
        "[dim]Обёртка над winws.exe от bol-van/zapret · идея — "
        "flowseal/zapret-discord-youtube[/dim]"
    )
    console.print(Panel(banner, border_style="magenta"))


def print_menu() -> None:
    """Рисует интерактивное меню."""
    table = Table(show_header=True, header_style="bold cyan", box=None)
    table.add_column("#", style="bold magenta", min_width=3)
    table.add_column("Стратегия", style="bold")
    table.add_column("Описание", style="dim")
    for key, strat in STRATEGIES.items():
        table.add_row(key, strat["name"], strat["desc"])
    table.add_row("S", "Остановить сервис", "Снять фильтры WinDivert")
    table.add_row("R", "Переустановить ядро", "Скачать заново и распаковать")
    table.add_row("0", "Выход", "Завершить Zapretik")
    console.print(table)


# --------------------------------------------------------------------------- #
# Вход / точка входа
# --------------------------------------------------------------------------- #

def main() -> None:
    """Главная функция утилиты."""
    setup_logging()
    print_banner()

    if not check_admin():
        relaunch_as_admin()
        return  # либо произошёл перезапуск с UAC, либо юзер отверг.

    logger.info("Запуск от администратора подтверждён.")

    # Авто-установка ядра при первом запуске
    download_core()

    while True:
        console.print()
        print_menu()
        choice = input("Выберите пункт: ").strip()

        if choice in STRATEGIES:
            run_strategy(choice, STRATEGIES[choice])
        elif choice.lower() == "s":
            stop_service()
        elif choice.lower() == "r":
            if BIN_DIR.exists():
                shutil.rmtree(BIN_DIR, ignore_errors=True)
            download_core()
        elif choice == "0":
            stop_service()
            console.print("[bold]До встречи![/bold]")
            break
        else:
            console.print("[red]Неверный пункт. Попробуйте ещё раз.[/red]")


if __name__ == "__main__":
    try:
        # Обработчик прерывания; также перехватываем в главном цикле.
        signal.signal(signal.SIGINT, lambda s, f: handle_interrupt())
        main()
    except KeyboardInterrupt:
        handle_interrupt()
    except SystemExit:
        raise
    except Exception as exc:
        console.print(f"[bold red]Непредвиденная ошибка: {exc}[/bold red]")
        logger.exception("Непредвиденная ошибка")
        input("Нажмите Enter, чтобы выйти...")