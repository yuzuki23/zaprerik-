# -*- coding: utf-8 -*-
"""Watchdog для фоновых процессов Zapretik.

Следит за care.py (будильник), monitor.py (мониторинг Discord) и службой zapret
(winws.exe). Если процесс упал — перезапускает его и пишет причину падения в watchdog.log.
Также проверяет целостность winws.exe (SHA256 против первого запуска) и ротирует лог.

Запуск:
    python watchdog.py

По умолчанию процессы запускаются с CREATE_NO_WINDOW и работают фоном.
"""
import hashlib
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

os.system("")

BASE_DIR = Path(r"C:\запрет")
WATCHDOG_LOG = BASE_DIR / "watchdog.log"
PYTHON = Path(sys.executable)
WINWS = BASE_DIR / "bin" / "winws.exe"
HASH_FILE = BASE_DIR / "winws.sha256"
MAX_LOG_SIZE = 2 * 1024 * 1024  # 2 МБ
KEEP_LOGS = 3

# Процессы под надзором: имя -> (скрипт, аргументы, частота перезапуска при сбое)
# monitor.py без аргументов = интервал 120 секунд (по умолчанию)
WATCHED = [
    {"name": "care",     "script": "care.py",     "args": []},
    {"name": "monitor",  "script": "monitor.py",  "args": []},
]

NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


def is_admin():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def rotate(path: Path, max_size=MAX_LOG_SIZE, keep=KEEP_LOGS):
    """Если лог разросся — сдвигает копии (.1, .2, ...) и начинает новый."""
    if not path.exists() or path.stat().st_size < max_size:
        return
    for i in range(keep - 1, 0, -1):
        src = path.with_name(f"{path.name}.{i}")
        dst = path.with_name(f"{path.name}.{i + 1}")
        if src.exists():
            dst.write_bytes(src.read_bytes())
            src.unlink()
    path.with_name(f"{path.name}.1").write_bytes(path.read_bytes())
    path.write_text("", encoding="utf-8")


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with WATCHDOG_LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def start_proc(entry):
    """Запускает дочерний процесс и возвращает Popen."""
    cmd = [str(PYTHON), entry["script"]] + entry["args"]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            creationflags=NO_WINDOW,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        log(f"Старт {entry['name']} (PID={proc.pid}): {entry['script']}")
        return proc
    except OSError as exc:
        log(f"ОШИБКА запуска {entry['name']}: {exc}")
        return None


def collect_output(entry):
    """Вычитывает накопившийся вывод процесса (если процесс уже умер)."""
    proc = entry.get("proc")
    if proc is None or proc.stdout is None:
        return
    if proc.poll() is None:
        return  # жив — не трогаем
    try:
        out = proc.stdout.read()
    except Exception:
        return
    if out:
        text = out.decode("utf-8", errors="replace").strip()
        if text:
            log(f"Вывод {entry['name']} (до падения):\n{text[:2000]}")


def winws_up():
    """winws работает как служба zapret или как процесс?"""
    try:
        r = subprocess.run(["sc", "query", "zapret"], capture_output=True, text=True,
                           timeout=15, creationflags=NO_WINDOW)
        if "RUNNING" in r.stdout:
            return True
    except Exception:
        pass
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq winws.exe"], capture_output=True,
                           text=True, timeout=15, creationflags=NO_WINDOW)
        return "winws.exe" in r.stdout
    except Exception:
        return True  # не можем проверить — не трогаем


def start_zapret():
    """Пытается поднять службу zapret (winws)."""
    try:
        if is_admin():
            r = subprocess.run(["sc", "start", "zapret"], capture_output=True, text=True,
                               timeout=30, creationflags=NO_WINDOW)
            msg = "sc start" if r.returncode == 0 else f"sc start -> {r.returncode}"
        else:
            subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden",
                              "-Command", "Start-Process 'sc.exe' -ArgumentList 'start','zapret' -Verb RunAs"],
                             creationflags=NO_WINDOW)
            msg = "UAC sc start"
        log(f"Поднятие winws: {msg}")
    except Exception as exc:
        log(f"ОШИБКА поднятия winws: {exc}")


def check_winws_hash():
    """Сверяет SHA256 winws.exe с первым запуском. Если изменился — предупреждает."""
    if not WINWS.exists():
        log("winws.exe НЕ НАЙДЕН в bin/")
        return
    h = hashlib.sha256(WINWS.read_bytes()).hexdigest()
    if not HASH_FILE.exists():
        HASH_FILE.write_text(h, encoding="utf-8")
        log("Сохранён первый хэш winws.exe (эталон)")
        return
    known = HASH_FILE.read_text(encoding="utf-8").strip()
    if known != h:
        log("ВНИМАНИЕ: winws.exe ИЗМЕНИЛСЯ (антивирус/подмена). Эталон: " + known[:16] + "... сейчас: " + h[:16] + "...")


def main():
    rotate(WATCHDOG_LOG)
    log("Watchdog запущен. Под надзором: " + ", ".join(e["name"] for e in WATCHED) + " + zapret/winws")
    check_winws_hash()
    for entry in WATCHED:
        entry["proc"] = start_proc(entry)
        entry["down_since"] = None
        time.sleep(1)

    while True:
        for entry in WATCHED:
            proc = entry.get("proc")
            if proc is not None and proc.poll() is not None:
                collect_output(entry)
                code = proc.poll()
                if entry.get("down_since") is None:
                    entry["down_since"] = time.time()
                    log(f"ПАДЕНИЕ {entry['name']} (код {code}) — перезапускаю")
                else:
                    log(f"{entry['name']} всё ещё лежит (код {code}) — повторный запуск")
                entry["proc"] = start_proc(entry)
                continue
            if proc is not None and entry.get("down_since") is not None:
                log(f"{entry['name']} снова работает (PID={proc.pid})")
                entry["down_since"] = None

        # Надзор за winws
        if not winws_up():
            now = time.time()
            last = entry_up.get("last_down") if entry_up else None
            if last is None or now - last > 90:
                log("winws НЕ РАБОТАЕТ — поднимаю службу zapret")
                start_zapret()
            entry_up["last_down"] = now
        time.sleep(10)


entry_up = {"last_down": None}