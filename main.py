#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
  ZAPRETIK — умная утилита для обхода DPI-блокировок Discord и YouTube в Windows
================================================================================

  Zapretik — это «обёртка» (wrapper) над winws.exe из проекта bol-van/zapret
  (https://github.com/bol-van/zapret). Скрипт умеет:

      * проверять наличие ядра (winws.exe + WinDivert.dll) и при отсутствии
        автоматически скачивать его с GitHub и распаковывать в рабочую папку;
      * запускать winws.exe с одной из заранее настроенных стратегий обхода DPI;
      * записывать весь вывод winws.exe в файл zapretik.log и дублировать его
        в консоль с цветовой маркировкой ошибок;
      * корректно останавливать процесс winws.exe (Ctrl+C или пункт меню),
        не оставляя зависших процессов и «застрявших» драйверов WinDivert.

  Идея и набор параметров взяты из проекта
  https://github.com/flowseal/zapret-discord-youtube (MIT).

--------------------------------------------------------------------------------
  НЕОБХОДИМЫЕ БИБЛИОТЕКИ (установка одной командой):

      pip install rich requests

  Если библиотеки не установлены, скрипт сам подскажет эту команду и выйдет.
--------------------------------------------------------------------------------
  ЗАПУСК:

      python main.py

  При запуске без прав администратора скрипт перезапустит себя с запросом UAC
  (winws.exe использует драйвер WinDivert, поэтому требуются права админа).
--------------------------------------------------------------------------------
  ПРИМЕЧАНИЕ ОБ АНТИВИРУСАХ:
  winws.exe использует драйвер WinDivert — антивирусы могут помечать его как
  RiskTool / PUA (класс программ для работы с сетевым трафиком). Это нормально;
  при необходимости добавьте winws.exe и WinDivert64.sys в исключения.
================================================================================
"""

from __future__ import annotations

import ctypes
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# ------------------------------------------------------------------------------
# Проверка наличия сторонних библиотек.
# Импорт сделан в try/except, чтобы сразу подсказать пользователю команду pip.
# ------------------------------------------------------------------------------
try:
    import requests
except ImportError:
    print("Не установлена библиотека 'requests'. Выполните:  pip install requests")
    sys.exit(1)

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeRemainingColumn
    from rich.table import Table
    from rich.text import Text
except ImportError:
    print("Не установлена библиотека 'rich'. Выполните:  pip install rich")
    sys.exit(1)


# ==============================================================================
#  КОНСТАНТЫ ПРОЕКТА
# ==============================================================================

# Рабочая папка скрипта. ВАЖНО: после перезапуска через UAC рабочая папка
# процесса меняется на C:\\Windows\\System32, поэтому все пути строятся
# относительно папки, в которой лежит main.py.
BASE_DIR: Path = Path(__file__).resolve().parent

LOG_FILE: Path = BASE_DIR / "zapretik.log"

# Файлы «ядра» zapret, которые должны лежать в рабочей папке проекта.
WINWS_EXE: Path = BASE_DIR / "winws.exe"
WINDIVERT_DLL: Path = BASE_DIR / "WinDivert.dll"
WINDIVERT_SYS: Path = BASE_DIR / "WinDivert64.sys"

# Источники ядра на GitHub (пробуются по порядку, см. download_core()).
ZAPRET_REPO: str = "bol-van/zapret"                      # официальный репозиторий
FLOWSEAL_REPO: str = "flowseal/zapret-discord-youtube"   # готовые бинарники winws
BUNDLE_ZIP_URL: str = (
    "https://github.com/bol-van/zapret-win-bundle/archive/refs/heads/master.zip"
)

GITHUB_API: str = "https://api.github.com"
GITHUB_UA: str = "Zapretik/1.0.4 (Windows wrapper for bol-van/zapret)"

# Маркеры ошибок, по которым строки вывода winws.exe красятся в красный цвет.
ERROR_MARKERS: Tuple[str, ...] = (
    "error", "fail", "cannot", "unable", "exception", "invalid", "0x",
)


# ==============================================================================
#  ГЛОБАЛЬНОЕ СОСТОЯНИЕ
# ==============================================================================

# Ссылка на запущенный процесс winws.exe (None — процесс не запущен).
_winws_proc: Optional["subprocess.Popen[str]"] = None

# Лениво создаваемая консоль rich (создаётся после настройки кодировки).
_console: Optional[Console] = None


def get_console() -> Console:
    """Возвращает глобальную консоль rich (создаёт её при первом обращении)."""
    global _console
    if _console is None:
        _console = Console()
    return _console


# ==============================================================================
#  СТРАТЕГИИ ЗАПУСКА
# ==============================================================================

@dataclass(frozen=True)
class Strategy:
    """Одна предустановленная конфигурация запуска winws.exe.

    Атрибуты:
        name        — человекочитаемое название для меню;
        description — краткое пояснение режима;
        color       — цвет пункта меню (имя стиля rich);
        args        — аргументы командной строки для winws.exe.
    """

    name: str
    description: str
    color: str
    args: Tuple[str, ...]

    def build_command(self, winws_path: Path) -> List[str]:
        """Собирает полный список аргументов для subprocess (путь + параметры)."""
        return [str(winws_path), *self.args]


# Словарь стратегий, ключ — номер пункта меню.
# Параметры соответствуют заданию; дополнительно добавлен --wf-tcp=443, чтобы
# winws перехватывал только TCP-порт 443 (как в flowseal) — меньше нагрузки на ЦП.
STRATEGIES: Dict[int, Strategy] = {
    1: Strategy(
        name="Discord + YouTube (Стандарт)",
        description="фейковая подмена TLS + фрагментация пакетов, порт TCP 443",
        color="green",
        args=(
            "--wf-tcp=443",
            "--wsize=2",
            "--split-pos=2",
            "--fake-tls",
            "--dpi-desync=fake",
            "--filter-tcp=443",
        ),
    ),
    2: Strategy(
        name="Только YouTube (Агрессивный)",
        description="перестановка сегментов (reorder) + фрагментация, порт TCP 443",
        color="yellow",
        args=(
            "--wf-tcp=443",
            "--wsize=1",
            "--split-pos=1",
            "--fake-tls",
            "--dpi-desync=reorder",
            "--filter-tcp=443",
        ),
    ),
    3: Strategy(
        name="Безопасный режим (Медленный)",
        description="только фрагментация, без фейковых пакетов",
        color="cyan",
        args=(
            "--wf-tcp=443",
            "--wsize=1",
            "--split-pos=1",
            "--filter-tcp=443",
        ),
    ),
}


# ==============================================================================
#  ЛОГИРОВАНИЕ (файл + цветная консоль)
# ==============================================================================

class RichLogHandler(logging.Handler):
    """Обработчик логов, выводящий записи в консоль через rich с цветами."""

    # Соответствие уровня логирования и стиля rich.
    LEVEL_COLORS: Dict[str, str] = {
        "DEBUG": "dim",
        "INFO": "cyan",
        "WARNING": "yellow",
        "ERROR": "bold red",
        "CRITICAL": "white on red",
    }

    def __init__(self) -> None:
        super().__init__()
        self._console = get_console()

    def emit(self, record: logging.LogRecord) -> None:
        """Печатает одну запись лога с цветовой разметкой по уровню."""
        try:
            style = self.LEVEL_COLORS.get(record.levelname, "white")
            self._console.print(f"[{style}]{record.getMessage()}[/{style}]")
        except Exception:
            # Никогда не должны падать из-за логирования.
            pass


def setup_logging() -> logging.Logger:
    """Настраивает двойное логирование.

    Файл zapretik.log получает ВЕСЬ вывод (уровень DEBUG),
    консоль — тоже весь вывод, но с цветами: INFO голубым, ошибки красным.
    """
    logger = logging.getLogger("zapretik")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False

    # 1) Файловый обработчик — вся информация в UTF-8.
    file_handler = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    logger.addHandler(file_handler)

    # 2) Консольный обработчик — цветная разметка через rich.
    console_handler = RichLogHandler()
    console_handler.setLevel(logging.DEBUG)
    logger.addHandler(console_handler)

    return logger


# Глобальный логгер (используется во всех функциях модуля).
logger: logging.Logger = logging.getLogger("zapretik")


# ==============================================================================
#  ПРОВЕРКА ПРАВ АДМИНИСТРАТОРА И ПЕРЕЗАПУСК ЧЕРЕЗ UAC
# ==============================================================================

def check_admin() -> bool:
    """Проверяет, запущен ли процесс с правами администратора Windows.

    Использует WinAPI IsUserAnAdmin() из shell32.dll. На не-Windows
    системах возвращает False (утилита работает только в Windows).
    """
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def restart_as_admin() -> bool:
    """Перезапускает текущий скрипт от имени администратора через UAC.

    Механизм: WinAPI ShellExecuteW с операцией "runas".
    Рабочая папка нового процесса принудительно задаётся BASE_DIR,
    чтобы после повышения прав скрипт продолжил работать в нужной директории.

    Возвращает:
        True  — запрос UAC принят, текущий процесс можно завершать;
        False — UAC отклонён пользователем или перезапуск невозможен.
    """
    script = str(Path(sys.argv[0]).resolve())
    # Передаём исходные аргументы командной строки новому процессу.
    params = " ".join(f'"{arg}"' for arg in sys.argv[1:])
    command = f'"{script}" {params}'.strip()

    try:
        result = ctypes.windll.shell32.ShellExecuteW(
            None,            # hwnd — нет родительского окна
            "runas",         # lpOperation — запрос повышения прав (UAC)
            sys.executable,  # lpFile — наш интерпретатор Python
            command,         # lpParameters — скрипт и его аргументы
            str(BASE_DIR),   # lpDirectory — рабочая папка нового процесса
            1,               # nShowCmd — показать окно
        )
    except Exception as exc:  # на не-Windows системах ctypes.windll отсутствует
        logger.error(f"Не удалось перезапустить с правами администратора: {exc}")
        return False

    # ShellExecuteW возвращает значение > 32 при успехе, иначе — код ошибки.
    if result > 32:
        logger.info("Запрос UAC принят. Новый процесс запущен от администратора.")
        return True

    logger.error("Запрос UAC отклонён или не был показан (код: %s).", result)
    return False


# ==============================================================================
#  ЗАГРУЗКА ЯДРА (winws.exe + WinDivert)
# ==============================================================================

def github_get(path: str) -> Optional[dict]:
    """GET-запрос к GitHub API с обработкой сетевых ошибок и rate-limit.

    Возвращает JSON-объект (dict) или None при неудаче.
    """
    url = f"{GITHUB_API}{path}"
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": GITHUB_UA})
        if resp.status_code == 403:
            logger.error("GitHub API: превышен лимит запросов (403). Повторите позже.")
            return None
        if resp.status_code != 200:
            logger.warning("GitHub API: HTTP %s для %s", resp.status_code, url)
            return None
        return resp.json()
    except requests.RequestException as exc:
        logger.error("Ошибка сети при обращении к GitHub: %s", exc)
        return None


@dataclass(frozen=True)
class ReleaseAsset:
    """Файл (ассет) релиза GitHub."""

    name: str
    url: str
    size: int


def latest_release_assets(repo: str) -> List[ReleaseAsset]:
    """Возвращает список файлов последнего релиза указанного репозитория GitHub."""
    data = github_get(f"/repos/{repo}/releases/latest")
    if not isinstance(data, dict) or "assets" not in data:
        return []
    return [
        ReleaseAsset(
            name=str(asset.get("name", "")),
            url=str(asset.get("browser_download_url", "")),
            size=int(asset.get("size") or 0),
        )
        for asset in data.get("assets", [])
        if asset.get("name")
    ]


def download_file(url: str, dest: Path, label: str) -> bool:
    """Скачивает файл по URL в dest, показывая индикатор прогресса.

    Возвращает True при успешной загрузке, False — при ошибке.
    """
    try:
        with requests.get(
            url, stream=True, timeout=60, headers={"User-Agent": GITHUB_UA}
        ) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length") or 0)
            dest.parent.mkdir(parents=True, exist_ok=True)

            # Индикатор загрузки: спиннер + прогресс-бар + оставшееся время.
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold]{task.description}"),
                BarColumn(bar_width=40),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeRemainingColumn(),
                console=get_console(),
            ) as progress:
                task_id = progress.add_task(label, total=total or None)
                with open(dest, "wb") as fh:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        if total:
                            progress.update(task_id, advance=len(chunk))
            return True
    except requests.RequestException as exc:
        logger.error("Ошибка скачивания %s: %s", label, exc)
        return False


def extract_and_install_core(zip_path: Path, install_dir: Path) -> bool:
    """Распаковывает архив и копирует ядро zapret в рабочую папку проекта.

    Файлы (winws.exe, WinDivert.dll, WinDivert64.sys) ищутся рекурсивно по всему
    архиву, поэтому функция работает с любой структурой релиза: bin/winws.exe,
    winws/x64/winws.exe, файлы в корне и т.п. При наличии нескольких вариантов
    разрядности предпочитается вариант из папки x64.

    Возвращает True, если ядро успешно установлено.
    """
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(zip_path.parent)
    except zipfile.BadZipFile as exc:
        logger.error("Не удалось распаковать %s: %s", zip_path.name, exc)
        return False

    # Список обязательных файлов ядра.
    required: Tuple[str, ...] = ("winws.exe", "WinDivert.dll", "WinDivert64.sys")

    # Собираем кандидатов по каждому файлу: имя файла -> список полных путей.
    found: Dict[str, List[Path]] = {key: [] for key in required}

    # Рекурсивный обход распакованной структуры.
    for root, _dirs, files in os.walk(zip_path.parent):
        for fname in files:
            for key in required:
                if fname.lower() == key.lower():
                    found[key].append(Path(root) / fname)

    missing = [key for key, paths in found.items() if not paths]
    if missing:
        logger.warning(
            "В архиве %s не найдены файлы: %s", zip_path.name, ", ".join(missing)
        )
        return False

    # Выбираем комплект файлов, лежащих в ОДНОЙ папке (чтобы не смешивать
    # разные разрядности/сборки). Группируем кандидатов по родительской папке.
    def dir_score(directory: Path) -> int:
        """Сколько из требуемых файлов лежит в данной папке."""
        return sum(1 for paths in found.values() if any(
            p.parent == directory for p in paths
        ))

    def dir_priority(directory: Path) -> int:
        """Ранжирование папок по разрядности: x64 > универсальная > x86/arm64."""
        low = str(directory).lower()
        if "arm64" in low or "arm" in low:
            return 3
        if "x86" in low or "i686" in low:
            return 2
        if "x64" in low or "amd64" in low:
            return 0
        return 1

    # Все папки, где встречаются требуемые файлы.
    all_dirs: List[Path] = sorted(
        {p.parent for paths in found.values() for p in paths}
    )
    # Лучшая папка: максимальное число файлов, при равенстве — предпочтение
    # разрядности (x64). Отрицательный кортеж — чтобы сортировка по убыванию.
    best_dir: Optional[Path] = max(
        all_dirs, key=lambda d: (dir_score(d), -dir_priority(d))
    )
    assert best_dir is not None

    # Копируем выбранный комплект из лучшей папки в рабочую папку проекта.
    for key in required:
        src = next(p for p in found[key] if p.parent == best_dir)
        dest = install_dir / key
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
            logger.info("Ядро: %s установлен (%s)", key, src)
    logger.info("Комплект ядра взят из папки: %s", best_dir)
    return True


def download_core() -> bool:
    """Скачивает и распаковывает ядро zapret в рабочую папку проекта.

    Источники пробуются по порядку (каскад):
        1) последний релиз bol-van/zapret — если там есть Windows-сборка;
        2) последний релиз flowseal/zapret-discord-youtube — готовые бинарники;
        3) zip-архив ветки master репозитория bol-van/zapret-win-bundle.

    Возвращает True при успешной установке ядра.
    """
    get_console().print(
        Panel.fit("[bold cyan]Загрузка ядра zapret (winws.exe + WinDivert)[/]", border_style="cyan")
    )
    logger.info("Ядро не найдено — начинаю автоматическую загрузку с GitHub.")

    candidates: List[Tuple[str, str]] = []

    # --- Источник 1: bol-van/zapret (ищем ассет «win*.zip»). ---
    for asset in latest_release_assets(ZAPRET_REPO):
        name = asset.name.lower()
        if (
            "win" in name
            and name.endswith(".zip")
            and "cygwin" not in name
            and "msys2" not in name
        ):
            candidates.append((asset.name, asset.url))
            break
    if not candidates:
        logger.info(
            "В релизе bol-van/zapret нет готовой Windows-сборки — пробую запасные источники."
        )

    # --- Источник 2: flowseal/zapret-discord-youtube (внутри лежит bin/winws.exe). ---
    if not candidates:
        for asset in latest_release_assets(FLOWSEAL_REPO):
            if asset.name.lower().endswith(".zip"):
                candidates.append((asset.name, asset.url))
                break

    # --- Источник 3: архив репозитория bol-van/zapret-win-bundle. ---
    if not candidates:
        candidates.append(("zapret-win-bundle.zip", BUNDLE_ZIP_URL))

    # --- Каскадная попытка установки ядра из каждого источника. ---
    with tempfile.TemporaryDirectory(prefix="zapretik_") as tmp:
        tmp_dir = Path(tmp)
        for name, url in candidates:
            zip_path = tmp_dir / name
            logger.info("Скачивание: %s", name)
            if not download_file(url, zip_path, name):
                continue  # сеть — пробуем следующий источник
            if extract_and_install_core(zip_path, BASE_DIR):
                logger.info("Ядро zapret успешно установлено в %s", BASE_DIR)
                return True
            logger.warning("Источник %s не подошёл — пробую следующий.", name)

    logger.error(
        "Не удалось автоматически получить ядро zapret. "
        "Скачайте вручную winws.exe и WinDivert.dll (WinDivert64.sys) "
        "и положите их в папку проекта: %s", BASE_DIR
    )
    return False


def ensure_core() -> bool:
    """Проверяет наличие ядра; при отсутствии скачивает его.

    Возвращает True, когда ядро готово к запуску.
    """
    if WINWS_EXE.exists() and WINDIVERT_DLL.exists():
        return True
    logger.info("winws.exe / WinDivert.dll не обнаружены в %s", BASE_DIR)
    return download_core()


# ==============================================================================
#  УПРАВЛЕНИЕ ПРОЦЕССОМ winws.exe
# ==============================================================================

def start_winws(strategy: Strategy) -> bool:
    """Запускает winws.exe с параметрами выбранной стратегии.

    Возвращает True, если процесс успешно стартовал.
    """
    global _winws_proc

    # Защита от повторного запуска при уже работающем процессе.
    if _winws_proc is not None and _winws_proc.poll() is None:
        logger.warning(
            "winws.exe уже запущен (PID=%s). Сначала остановите сервис "
            "(Ctrl+C или пункт меню «Остановить сервис»).", _winws_proc.pid
        )
        return False

    if not ensure_core():
        return False

    command = strategy.build_command(WINWS_EXE)
    logger.info("Команда: %s", " ".join(command))

    # Кодировка вывода winws — кодировка консоли системы (обычно OEM cp866);
    # при перенаправлении в пайп берём её же, иначе UTF-8.
    encoding = os.device_encoding(1) or "utf-8"

    try:
        _winws_proc = subprocess.Popen(
            command,
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # объединяем stderr со stdout
            text=True,
            encoding=encoding,
            errors="replace",
            bufsize=1,                 # построчная буферизация вывода
        )
    except OSError as exc:
        logger.error("Не удалось запустить winws.exe: %s", exc)
        _winws_proc = None
        return False

    logger.info("winws.exe запущен (PID=%s). Для остановки нажмите Ctrl+C.", _winws_proc.pid)
    return True


def stop_winws() -> None:
    """Корректно останавливает winws.exe, при необходимости принудительно.

    Сначала пробуем мягкое завершение (proc.terminate) и ждём до 10 секунд.
    Если процесс не завершился — «добиваем» его (proc.kill). Благодаря этому
    после остановки не остаётся зависших процессов winws.exe.
    """
    global _winws_proc
    proc = _winws_proc
    if proc is None or proc.poll() is not None:
        _winws_proc = None
        return

    logger.info("Останавливаю winws.exe (PID=%s)...", proc.pid)
    try:
        # terminate() на Windows — это TerminateProcess (жёсткое, но надёжное).
        proc.terminate()
        proc.wait(timeout=10)
        logger.info("winws.exe остановлен.")
    except subprocess.TimeoutExpired:
        logger.warning("winws.exe не завершился за 10 секунд — принудительное завершение.")
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            logger.error("Не удалось завершить winws.exe вручную. Проверьте диспетчер задач.")
    except Exception as exc:
        logger.error("Ошибка при остановке winws.exe: %s", exc)
    finally:
        _winws_proc = None


def log_winws_line(line: str) -> None:
    """Пишет одну строку вывода winws.exe в лог (файл + консоль).

    Если в строке есть маркеры ошибки — строка помечается как ERROR
    и окрашивается в красный цвет в консоли.
    """
    text = line.rstrip()
    if not text:
        return
    if any(marker in text.lower() for marker in ERROR_MARKERS):
        logger.error("winws: %s", text)
    else:
        logger.info("winws: %s", text)


def run_strategy(strategy: Strategy) -> None:
    """Запускает стратегию и следит за процессом до его остановки.

    Выход из цикла наблюдения: Ctrl+C (KeyboardInterrupt), остановка процесса
    winws.exe или завершение winws.exe по любой другой причине.
    """
    if not start_winws(strategy):
        return

    proc = _winws_proc
    assert proc is not None and proc.stdout is not None

    get_console().print(
        Panel.fit(
            f"[{strategy.color}]{strategy.name}[/]\n[dim]{strategy.description}[/]",
            border_style=strategy.color,
        )
    )

    try:
        # Читаем построчно вывод работающего winws.exe до его остановки.
        while proc.poll() is None:
            line = proc.stdout.readline()
            if line:
                log_winws_line(line)
    except KeyboardInterrupt:
        # Ctrl+C во время работы winws — мягко останавливаем сервис.
        logger.warning("Получен Ctrl+C — останавливаю сервис...")
    finally:
        stop_winws()

    # Проверяем, не упал ли winws с ошибкой сам по себе.
    code = proc.returncode
    if code not in (0, None):
        logger.error("winws.exe завершился с кодом %s.", code)
    logger.info("Сервис остановлен. Возврат в меню.")


# ==============================================================================
#  ИНТЕРФЕЙС (меню и баннер)
# ==============================================================================

def show_banner() -> None:
    """Печатает стартовый баннер утилиты."""
    get_console().print(
        Panel.fit(
            Text.assemble(
                ("ZAPRETIK", "bold cyan"),
                ("  — обход DPI для Discord и YouTube", "white"),
            ),
            border_style="cyan",
            subtitle="обёртка над winws.exe (bol-van/zapret)",
        )
    )


def show_menu() -> None:
    """Печатает интерактивное меню выбора режима работы."""
    table = Table(show_header=False, box=None, expand=False, padding=(0, 1))
    table.add_column(width=5, style="bold")
    table.add_column()

    table.add_row("", "[bold]Выберите режим работы:[/]")
    for key, strat in STRATEGIES.items():
        table.add_row(f"[{strat.color}]{key}.[/]", f"[{strat.color}]{strat.name}[/]")
        table.add_row("", f"[dim]       {strat.description}[/]")
    table.add_row("[red]4.[/]", "[red]Остановить сервис[/]")
    table.add_row("[red]0.[/]", "[red]Выход[/]")

    get_console().print(table)


def read_choice() -> Optional[str]:
    """Читает выбор пользователя в меню.

    Возвращает строку выбора либо None при Ctrl+C / EOF (означает «завершить»).
    """
    try:
        return input("> ").strip()
    except KeyboardInterrupt:
        print()  # перенос строки после Ctrl+C
        return None
    except EOFError:
        return None


# ==============================================================================
#  ТОЧКА ВХОДА
# ==============================================================================

def main() -> int:
    """Главная функция: проверка прав, ядра и интерактивный цикл меню."""
    # Zapretik работает только в Windows (winws.exe использует драйвер WinDivert).
    if os.name != "nt":
        print("Zapretik работает только в Windows.")
        return 1

    # Переходим в папку скрипта (важно после перезапуска через UAC,
    # где рабочей папкой становится C:\\Windows\\System32).
    try:
        os.chdir(BASE_DIR)
    except OSError:
        pass

    setup_logging()
    show_banner()

    # --- Проверка прав администратора. ---
    if not check_admin():
        logger.warning("Запущено без прав администратора. Запрашиваю повышение прав (UAC)...")
        if restart_as_admin():
            # UAC принят: новый процесс уже запущен — завершаем текущий.
            return 0
        logger.error(
            "Без прав администратора winws.exe не сможет работать с драйвером WinDivert. "
            "Запустите скрипт от имени администратора."
        )
        return 1

    # --- Проверка / автозагрузка ядра. ---
    if not ensure_core():
        return 1

    # --- Интерактивный цикл меню. ---
    while True:
        try:
            show_menu()
            choice = read_choice()
            if choice is None:            # Ctrl+C / EOF в меню
                break
            if choice == "0":             # выход
                break
            if choice == "4":             # остановить сервис
                stop_winws()
                continue
            if choice in ("1", "2", "3"): # запуск стратегии
                run_strategy(STRATEGIES[int(choice)])
                continue
            logger.warning("Неизвестный пункт меню: %r", choice)
        except KeyboardInterrupt:
            get_console().print("[bold red]Прерывание. Останавливаю сервис...[/]")
            stop_winws()
            break
        except Exception as exc:
            logger.error("Непредвиденная ошибка: %s", exc)

    # Финальная остановка процесса перед выходом (защита от «зависших» winws).
    stop_winws()
    logger.info("Выход. До встречи!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
