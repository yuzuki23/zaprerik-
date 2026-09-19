# -*- coding: utf-8 -*-
"""Лёгкий страж сторожа (watchdog keepalive).

Запускается по расписанию (schtasks, каждые 5 минут) и проверяет, жив ли
watchdog.py. Если сторож сам упал (весь стек мониторинга лёг, как 29.08 в
окне 13:57–14:44), этот скрипт поднимает его заново — без ручного вмешательства.

Сам страж не держит долгоживущих процессов: отработал проверку и вышел,
поэтому «умереть» в ожидании не может. Запускается через pythonw (без окон).

Детект живости — по lock-файлу сторожа (zapretik_watchdog.lock в C:\запрет).
Путь фиксированный (НЕ в TEMP!): у процессов из Планировщика и из сессии
разные TEMP-окружения, из-за чего keeper не видел живой сторож, бесконечно
дёргал schtasks /Run (задача падала с кодом 2), и сторож не восстанавливался.

Подъём: напрямую pythonw watchdog.py (без плашщика и подсказки прав) —
надёжнее, чем полагаться на ZapretikWatchdog из Планировщика.
"""
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE = Path(r"C:\запрет")
WATCHDOG = BASE / "watchdog.py"
PYTHON = sys.executable
NO_WINDOW = 0x08000000
KEEPER_LOG = BASE / "watchdog_keepalive.log"
# Тот же путь, что и у сторожа в watchdog.py — единая точка правды.
LOCK_FILE = BASE / "zapretik_watchdog.lock"

WAIT_AFTER_START = 6  # сек после запуска, чтобы сторож успел встать


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    try:
        with KEEPER_LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


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


def start_watchdog():
    """Поднимает сторож напрямую pythonw watchdog.py (без UAC и планировщика).
    Возвращает True, если сторож реально встал (проверено по lock-файлу)."""
    try:
        subprocess.Popen([PYTHON, str(WATCHDOG)], cwd=str(BASE),
                         creationflags=NO_WINDOW)
    except Exception as exc:
        log(f"ОШИБКА запуска watchdog.py напрямую: {exc}")
        return False
    for _ in range(WAIT_AFTER_START):
        time.sleep(1)
        if watchdog_running():
            return True
    return watchdog_running()


def main():
    if watchdog_running():
        return
    log("Сторож НЕ живой — поднимаю напрямую")
    ok = start_watchdog()
    if ok:
        log("Сторож поднят напрямую (pythonw watchdog.py)")
    else:
        log("Сторож НЕ поднялся — пробую через Планировщик (schtasks /Run)")
        try:
            r = subprocess.run(["schtasks", "/Run", "/TN", "ZapretikWatchdog"],
                               capture_output=True, text=True, timeout=20,
                               creationflags=NO_WINDOW)
            log(f"schtasks /Run создал задачу (код {r.returncode})")
        except Exception as exc:
            log(f"ОШИБКА schtasks /Run: {exc}")
        time.sleep(WAIT_AFTER_START)
        if not watchdog_running():
            log("Сторож НЕ поднялся ни напрямую, ни через Планировщик")


if __name__ == "__main__":
    main()