# -*- coding: utf-8 -*-
"""Лёгкий страж сторожа (watchdog keepalive).

Запускается по расписанию (schtasks, каждые 5 минут) и проверяет, жив ли
watchdog.py. Если сторож сам упал (весь стек мониторинга лёг, как 29.08 в
окне 13:57–14:44), этот скрипт поднимает его заново — без ручного вмешательства.

Сам страж не держит долгоживущих процессов: отработал проверку и вышел,
поэтому «умереть» в ожидании не может. Запускается через pythonw (без окон).

Детект живости — по lock-файлу сторожа (zapretik_watchdog.lock в TEMP), а не по
CommandLine процесса: у процессов, поднятых Планировщиком заданий, поле
CommandLine в WMI часто пустое, из-за чего проверка по командной строке
не работает.
"""
import os
import subprocess
import sys
from pathlib import Path

BASE = Path(r"C:\запрет")
WATCHDOG = BASE / "watchdog.py"
PYTHON = sys.executable
NO_WINDOW = 0x08000000
LOCK_FILE = Path(os.environ.get("TEMP", str(BASE))) / "zapretik_watchdog.lock"


def watchdog_running():
    """True, если жив экземпляр сторожа (по lock-файлу с актуальным PID)."""
    try:
        if LOCK_FILE.exists():
            pid = LOCK_FILE.read_text(encoding="utf-8").strip()
            if pid.isdigit():
                r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                                   capture_output=True, text=True, timeout=10,
                                   creationflags=NO_WINDOW)
                if pid in r.stdout:
                    return True
    except Exception:
        # не смогли проверить — считаем НЕ живым, чтобы подстраховаться
        # (новый сторож упрётся в свой же lock и просто выйдет, без дублей)
        return False
    return False


def main():
    if watchdog_running():
        return
    try:
        subprocess.Popen([PYTHON, str(WATCHDOG)], cwd=str(BASE),
                         creationflags=NO_WINDOW)
    except Exception:
        pass


if __name__ == "__main__":
    main()
