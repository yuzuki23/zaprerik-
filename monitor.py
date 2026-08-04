# -*- coding: utf-8 -*-
"""Мониторинг сбоев Discord.

Запуск:
    python monitor.py            # проверка каждые 5 минут
    python monitor.py 2          # проверка каждые 2 минуты

При каждом сбое (HTTP != 200) пишет в discord_monitor.log запись с датой,
проверяет статус на detector404.ru/discord и сохраняет картинку/код.
"""
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

os.system("")  # включаем ANSI-цвета в Windows-терминале

GREEN = "\033[32m"
RED = "\033[31m"
RESET = "\033[0m"

LOG = Path(r"C:\запрет\discord_monitor.log")
URLS = ["https://discord.com/", "https://gateway.discord.gg/",
        "https://detector404.ru/discord"]


def notify(title, text):
    """Системное уведомление Windows при сбое."""
    ps = (f"[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms')|Out-Null;"
          f"$n=New-Object System.Windows.Forms.NotifyIcon;$n.Icon=[System.Drawing.SystemIcons]::Warning;"
          f"$n.Visible=$true;$n.ShowBalloonTip(10000,'{title}','{text}',"
          f"[System.Windows.Forms.ToolTipIcon]::Warning)")
    subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                     creationflags=subprocess.CREATE_NO_WINDOW)


def http(url, timeout=12):
    try:
        r = subprocess.run(
            ["curl.exe", "-s", "-o", "NUL", "-w", "%{http_code}",
             "--connect-timeout", "6", "--max-time", str(timeout), url],
            capture_output=True, text=True, timeout=20)
        return (r.stdout or "").strip() or "ERR"
    except Exception as exc:
        return f"ERR {exc}"


def winws_alive():
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "if (Get-Process winws -ErrorAction SilentlyContinue) { 'yes' } else { 'no' }"],
                           capture_output=True, text=True, timeout=15)
        return (r.stdout or "").strip()
    except Exception:
        return "?"


def restart_zapret():
    """Перезапуск zapret (winws): убить старый процесс и стартовать restart_zapret.bat."""
    try:
        subprocess.run(["taskkill", "/F", "/IM", "winws.exe"],
                       capture_output=True, text=True, timeout=20)
    except Exception:
        pass
    time.sleep(2)
    try:
        subprocess.Popen(["cmd", "/c", r"C:\запрет\restart_zapret.bat"],
                         creationflags=subprocess.CREATE_NO_WINDOW)
        return "OK"
    except Exception as exc:
        return f"FAIL {exc}"


def restore_discord():
    """Перезапускает zapret по кругу, пока discord.com не вернётся к 200."""
    for attempt in range(1, 6):
        restart_zapret()
        time.sleep(7)
        if http("https://discord.com/") == "200":
            return f"OK (попытка {attempt})"
    return "FAIL после 5 перезапусков"


def main():
    interval = int(sys.argv[1]) * 60 if len(sys.argv) > 1 else 300
    print(f"Мониторинг Discord, интервал {interval // 60} мин. Лог: {LOG}")
    while True:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        codes = {u: http(u) for u in URLS}
        ok = all(c == "200" or (c == "404" and "gateway" in u) for u, c in codes.items())
        line = f"{ts} | " + " | ".join(f"{u} -> {c}" for u, c in codes.items())
        if not ok:
            alive = winws_alive()
            restore = restore_discord()
            line += f" | winws -> {alive} | autorestart -> {restore}"
            print(RED + "СБОЙ: " + line + RESET, flush=True)
            LOG.open("a", encoding="utf-8").write("СБОЙ " + line + "\n")
        else:
            print(GREEN + "OK: " + line + RESET, flush=True)
            LOG.open("a", encoding="utf-8").write("OK " + line + "\n")
        time.sleep(interval)


if __name__ == "__main__":
    main()
