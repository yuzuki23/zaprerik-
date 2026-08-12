# -*- coding: utf-8 -*-
"""Мониторинг сбоев Discord.

Запуск:
    python monitor.py            # проверка каждые 2 минуты
    python monitor.py 5          # проверка каждые 5 минут

При каждом сбое (HTTP != 200) пишет в discord_monitor.log запись с датой,
проверяет статус на detector404.ru/discord и сохраняет картинку/код.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

os.system("")  # включаем ANSI-цвета в Windows-терминале

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"

LOG = Path(r"C:\запрет\discord_monitor.log")
STATUS = Path(r"C:\запрет\discord_status.txt")
HEALTH_URLS = ["https://discord.com/", "https://gateway.discord.gg/"]
# Несколько детекторов: если основной (detector404.ru) ляжет — пробуем запасной.
DETECTORS = ["https://detector404.ru/discord", "https://www.gstatic.com/generate_204"]

NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW — консольные дети не открывают окно (важно для pythonw)

MAX_LOG_SIZE = 2 * 1024 * 1024  # 2 МБ
KEEP_LOGS = 3
RESTART_AFTER_FAILS = 3  # после стольких «настоящих» сбоев подряд — перезапускаем zapret


def notify(title, text):
    """Системное уведомление Windows при сбое."""
    ps1 = (
        "Add-Type -AssemblyName System.Windows.Forms\n"
        "Add-Type -AssemblyName System.Drawing\n"
        "$n=New-Object System.Windows.Forms.NotifyIcon\n"
        "$n.Icon=[System.Drawing.SystemIcons]::Warning\n"
        "$n.Visible=$true\n"
        f"$n.ShowBalloonTip(15000,'{title}','{text}',[System.Windows.Forms.ToolTipIcon]::Warning)\n"
        "$t=New-Object System.Windows.Forms.Timer\n"
        "$t.Interval=16000\n"
        "$t.Add_Tick({$n.Visible=$false;$n.Dispose();[System.Windows.Forms.Application]::Exit()})\n"
        "$t.Start()\n"
        "[System.Windows.Forms.Application]::Run()\n"
    )
    path = Path(os.environ.get("TEMP", r"C:\запрет")) / "monitor_notify.ps1"
    path.write_text(ps1, encoding="utf-8-sig")
    subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden",
                      "-ExecutionPolicy", "Bypass", "-File", str(path)],
                     creationflags=subprocess.CREATE_NO_WINDOW)


def write_status(ts, codes, detector, detector_src, extra=""):
    """Живой статус-файл: показывает текущее состояние Discord."""
    discord = codes.get("https://discord.com/", "?")
    if discord == "200":
        verdict = "ВСЁ РАБОТАЕТ"
    elif codes.get("https://gateway.discord.gg/", "?") == "200":
        verdict = "ЧАСТИЧНЫЙ СБОЙ (часть сервисов лежит)"
    else:
        verdict = "ЛЕЖИТ / НЕ ДОСТУПЕН"
    det_label = "detector404.ru/discord" if "detector404" in detector_src else detector_src
    lines = [
        f"Discord — живой статус (обновлено: {ts})",
        "==========================================",
        f"discord.com          -> {codes.get('https://discord.com/', '?'):>3}",
        f"gateway.discord.gg   -> {codes.get('https://gateway.discord.gg/', '?'):>3}",
        f"{det_label:<22} -> {detector:>3}",
        "==========================================",
        "ВЕРДИКТ: " + verdict,
    ]
    if extra:
        lines.append("Доп.: " + extra)
    STATUS.write_text("\n".join(lines) + "\n", encoding="utf-8")


def status_api():
    """Парсит официальный статус Discord (discordstatus.com). Возвращает (api, indicator)."""
    try:
        r = subprocess.run(
            ["curl.exe", "-s", "--connect-timeout", "6", "--max-time", "12",
             "https://status.discord.com/api/v2/summary.json"],
            capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
        data = json.loads(r.stdout)
        api = "none"
        for c in data.get("components", []):
            name = (c.get("name") or "").lower()
            if "api" in name:  # ищем компонент по имени, а не по хардкод-id
                api = c.get("status", "unknown")
                break
        if api == "none":  # запасной вариант — по старому id
            for c in data.get("components", []):
                if c.get("id") == "rhznvxg4v7yh":
                    api = c.get("status", "unknown")
                    break
        indicator = data.get("status", {}).get("indicator", "unknown")
        return api, indicator
    except Exception:
        return "?", "?"


def http(url, timeout=12):
    try:
        r = subprocess.run(
            ["curl.exe", "-s", "-o", "NUL", "-w", "%{http_code}",
             "--connect-timeout", "6", "--max-time", str(timeout), url],
            capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW)
        return (r.stdout or "").strip() or "ERR"
    except Exception as exc:
        return f"ERR {exc}"


def check_detector():
    """Проверяет доступность Discord через один из детекторов (с запасным)."""
    for url in DETECTORS:
        code = http(url)
        if code in ("200", "204"):
            return code, url
    return "ERR", DETECTORS[0]


def winws_alive():
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "if (Get-Process winws -ErrorAction SilentlyContinue) { 'yes' } else { 'no' }"],
                           capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
        return (r.stdout or "").strip()
    except Exception:
        return "?"


def rotate_log():
    """Если лог разросся — сдвигает копии (.1, .2, ...) и начинает новый."""
    if not LOG.exists() or LOG.stat().st_size < MAX_LOG_SIZE:
        return
    for i in range(KEEP_LOGS - 1, 0, -1):
        src = LOG.with_name(f"{LOG.name}.{i}")
        dst = LOG.with_name(f"{LOG.name}.{i + 1}")
        if src.exists():
            dst.write_bytes(src.read_bytes())
            src.unlink()
    LOG.with_name(f"{LOG.name}.1").write_bytes(LOG.read_bytes())
    LOG.write_text("", encoding="utf-8")


def restart_zapret_service():
    """Перезапуск службы zapret (winws) через sc/net."""
    try:
        subprocess.run(["net", "stop", "zapret"], capture_output=True, text=True, timeout=30,
                       creationflags=NO_WINDOW)
    except Exception:
        pass
    time.sleep(2)
    try:
        r = subprocess.run(["net", "start", "zapret"], capture_output=True, text=True, timeout=30,
                           creationflags=NO_WINDOW)
        return "OK" if r.returncode == 0 else f"FAIL {r.stdout.strip()[-100:]}"
    except Exception as exc:
        return f"FAIL {exc}"


def restart_zapret():
    """Перезапуск zapret (winws): убить старый процесс и стартовать restart_zapret.bat."""
    try:
        subprocess.run(["taskkill", "/F", "/IM", "winws.exe"],
                       capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW)
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
    interval = int(sys.argv[1]) * 60 if len(sys.argv) > 1 else 120
    print(f"Мониторинг Discord, интервал {interval // 60} мин. Лог: {LOG}")
    was_down = False
    fail_streak = 0  # подряд идущие «настоящие» сбои (маршрутная блокировка)
    while True:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        codes = {u: http(u) for u in HEALTH_URLS}
        detector, detector_src = check_detector()
        ok = all(c == "200" or (c == "404" and "gateway" in u) for u, c in codes.items())
        api, indicator = status_api()  # официальный статус Discord (status.discord.com)
        disc_gone = api in ("major_outage", "partial_outage") or indicator in ("major", "minor", "critical")
        extra = f"discordstatus.com: API={api}, indicator={indicator}"
        write_status(ts, codes, detector, detector_src, extra)  # живой статус-файл
        if was_down and not disc_gone:
            # официальный статус восстановился — радостное уведомление
            notify("Discord снова работает!", f"{ts}\\nAPI: {api} ({indicator}) — можно заходить")
        was_down = disc_gone
        line = (f"{ts} | " + " | ".join(f"{u} -> {c}" for u, c in codes.items())
                + f" | detector({detector_src}) -> {detector} | api: {api}/{indicator}")
        if not ok:
            alive = winws_alive()
            if alive == "no" or alive == "?":
                # winws умер — перезапуск и проверка восстановления
                fail_streak = 0
                restore = restore_discord()
                line += f" | winws -> {alive} | autorestart -> {restore}"
                print(RED + "СБОЙ: " + line + RESET, flush=True)
                LOG.open("a", encoding="utf-8").write("СБОЙ " + line + "\n")
                notify("Zapret: сбой Discord (winws)", f"{ts}\n{restore}")
            else:
                # winws жив — повторная проверка, чтобы отсеять разовые обрывы маршрута
                time.sleep(5)
                if http("https://discord.com/") == "200":
                    # сам восстановился — это НЕ сбой, обычная OK-строка
                    fail_streak = 0
                    print(GREEN + "OK: " + line + " (разовый обрыв, сам ожил)" + RESET, flush=True)
                    LOG.open("a", encoding="utf-8").write(
                        "OK " + line + " (разовый обрыв маршрута, сам восстановился)\n")
                else:
                    # держится недоступным дольше — реальная маршрутная блокировка
                    fail_streak += 1
                    line += f" | winws жив — маршрутная блокировка ({fail_streak}/{RESTART_AFTER_FAILS})"
                    if fail_streak >= RESTART_AFTER_FAILS:
                        # столько подряд — перезапускаем zapret
                        res = restart_zapret_service()
                        line += f" | autorestart -> {res}"
                        fail_streak = 0
                        print(RED + "СБОЙ: " + line + RESET, flush=True)
                        LOG.open("a", encoding="utf-8").write("СБОЙ " + line + "\n")
                        notify("Zapret: перезапуск службы",
                               f"{ts}\n{RESTART_AFTER_FAILS} сбоя подряд, перезапускаю zapret")
                    else:
                        # пока не набралось 3 подряд — это INFO, не тревога
                        print(YELLOW + "INFO: " + line + RESET, flush=True)
                        LOG.open("a", encoding="utf-8").write("INFO " + line + "\n")
                        notify("Zapret: Discord недоступен",
                               f"{ts}\nМаршрутная блокировка, продолжается")
        else:
            fail_streak = 0
            print(GREEN + "OK: " + line + " | всё в порядке" + RESET, flush=True)
            LOG.open("a", encoding="utf-8").write("OK " + line + " | всё в порядке\n")
        rotate_log()
        time.sleep(interval)


if __name__ == "__main__":
    main()
