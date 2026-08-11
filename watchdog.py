# -*- coding: utf-8 -*-
"""Watchdog для фоновых процессов Zapretik.

Следит за care.py (будильник) и monitor.py (мониторинг Discord).
Если процесс упал — перезапускает его и пишет причину падения в watchdog.log.

Запуск:
    python watchdog.py

По умолчанию процессы запускаются с CREATE_NO_WINDOW и работают фоном.
"""
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

# Процессы под надзором: имя -> (скрипт, аргументы, частота перезапуска при сбое)
# monitor.py без аргументов = интервал 120 секунд (по умолчанию)
WATCHED = [
    {"name": "care",     "script": "care.py",     "args": []},
    {"name": "monitor",  "script": "monitor.py",  "args": []},
]

NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW


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
            text=True,
            encoding=os.device_encoding(1) or "utf-8",
            errors="replace",
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
    if out and out.strip():
        log(f"Вывод {entry['name']} (до падения):\n{out.strip()[:2000]}")


def main():
    log("Watchdog запущен. Под надзором: " + ", ".join(e["name"] for e in WATCHED))
    for entry in WATCHED:
        entry["proc"] = start_proc(entry)
        entry["down_since"] = None
        time.sleep(1)

    while True:
        for entry in WATCHED:
            proc = entry.get("proc")
            # Процесс мог умереть — собираем его последний вывод (причину падения).
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
                # Процесс ожил после падения
                log(f"{entry['name']} снова работает (PID={proc.pid})")
                entry["down_since"] = None
        time.sleep(10)


if __name__ == "__main__":
    main()
