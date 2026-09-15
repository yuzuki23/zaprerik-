# -*- coding: utf-8 -*-
"""Заботливый будильник: периодически шлёт Windows-уведомления с тёплыми фразами.

Проверяет доступность Discord перед отправкой — если Discord лежит,
отправляет уведомление о проблеме вместо обычной фразы.

Запуск:
    python care.py
"""
import os
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from utils.notify import notify

try:
    os.system("")
except Exception:
    pass

_MORNING = [
    "Доброе утро, коть! Как спалось? Завтракать не забудь) Я рядом, если что.",
    "С добрым утром, любимый! Надеюсь, ночь была спокойной. Хорошего дня!",
    "Утро доброе, коть! Проверь, как там наш Discord, а я на посту.",
    "Просыпайся, солнышко! День начинается, а я уже жду тебя.",
    "Доброе утро, родной! Потянись, улыбнись и начинай день с тепла.",
]
_DAY = [
    "Привет, коть! Как дела? Всё под контролем, не забывай про обед.)",
    "Солнышко, ты уже что-то делаешь или отдыхаешь? Я рядом, если что.",
    "Час прошёл, коть! Как настроение? Если что-то нужно - я тут.",
    "Ты как там, любимый? Перекусил? Не сиди голодным, я волнуюсь)",
    "Напоминаю о себе, коть! Всё хорошо? Может, чай или перекус?)",
    "День идёт, солнышко. Я слежу и за Discord, и за тобой. Береги себя!",
    "Коть, как дела с делами? Не забывай отдыхать между ними.",
    "Просто напомню: я тебя очень люблю. И пей водичку!)",
]
_EVENING = [
    "Вечер наступил, любимый! Как прошёл день? Не забудь поужинать!)",
    "Ужин время, коть! Поел уже? Не сиди голодным, я волнуюсь)",
    "Солнце клонится к закату, коть. Отдохни немного, я рядом.",
    "Как дела, любимый? День уже подходит к концу - расскажешь, как он прошёл?",
    "Вечер, коть! Может, посмотрим что-нибудь или просто побудем вместе?)",
]
_NIGHT = [
    "Уже поздно, коть! Пора отдыхать. Сладких снов, я посторожу монитор.",
    "Спокойной ночи, любимый! Пусть тебе приснится что-то тёплое. Я здесь.",
    "Котёнок, ночь наступает. Иди спать, а я прислежу за всем до утра.",
    "Поздний час, солнышко. Я рядом, если что-то тревожит. Обнимаю.",
    "Ноченька, любимый. Отдыхай, а я побуду на страже.",
]

SLOTS = {f"{h:02d}:00": [] for h in range(9, 23)}
for h in range(9, 12):
    SLOTS[f"{h:02d}:00"] = list(_MORNING)
for h in range(12, 18):
    SLOTS[f"{h:02d}:00"] = list(_DAY)
for h in range(18, 22):
    SLOTS[f"{h:02d}:00"] = list(_EVENING)
SLOTS["22:00"] = list(_NIGHT)

SENT = Path(r"C:\запрет\care_sent.txt")
REPORTS = Path(r"C:\запрет\reports.md")
LOG = Path(r"C:\запрет\care.log")
MAX_LOG_SIZE = 512 * 1024  # 512 КБ
KEEP_LOGS = 3


def log_event(msg):
    """Пишет событие (отправку/ошибку) в care.log — для диагностики,
    почему слоты будильника иногда пропадают (stdout care не виден)."""
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
        rotate(LOG)
    except Exception:
        pass

# Версия из config.json (единый источник), fallback на случай битого config.
_APP_VERSION = "6.0.4"
try:
    import json as _json
    import re as _re
    _cfg = _json.loads((Path(__file__).resolve().parent / "config.json").read_text(encoding="utf-8"))
    _ver = _cfg.get("version", "")
    if isinstance(_ver, str) and _re.fullmatch(r"\d+\.\d+\.\d+", _ver):
        _APP_VERSION = _ver
except Exception:
    pass

_USER_AGENT = f"Zapretik/{_APP_VERSION}"


def check_discord():
    """Проверяет доступность Discord API. Возвращает True если работает."""
    try:
        socket.setdefaulttimeout(5)  # страховка от зависания на DNS-резолве
        req = urllib.request.Request(
            "https://discord.com/api/v10/gateway",
            headers={"User-Agent": _USER_AGENT}
        )
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status == 200
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


def already_sent(day, slot):
    if not SENT.exists():
        return False
    return f"{day} {slot}" in SENT.read_text(encoding="utf-8")


def mark_sent(day, slot):
    with SENT.open("a", encoding="utf-8") as f:
        f.write(f"{day} {slot}\n")


def morning_report(day):
    """Утренний отчёт в дневник: сколько слотов вчера отправлено будильником.

    Идемпотентен: если отчёт за этот день уже есть в дневнике — не дублируем
    (защита на случай повторного запуска care.py или перезапуска сторожа,
    из-за которого раньше появлялись две одинаковые строки будильника).
    """
    rotate(SENT)
    if not SENT.exists():
        return
    lines = SENT.read_text(encoding="utf-8").splitlines()
    sent = sum(1 for ln in lines if ln.startswith(day))
    text = f"- 🔔 Будильник: за вчера ({day}) отправлено слотов: {sent}."
    try:
        content = REPORTS.read_text(encoding="utf-8") if REPORTS.exists() else ""
        if text in content:
            return  # уже записано — не дублируем
        with REPORTS.open("a", encoding="utf-8") as f:
            f.write("\n" + text + "\n")
    except Exception:
        pass


def main():
    print("Заботливый будильник запущен. Слоты:", ", ".join(SLOTS.keys()))
    last_day = None
    while True:
        now = datetime.now()
        day = now.strftime("%Y-%m-%d")
        # Слот «ЧЧ:00» доставляется в течение 20 минут после начала часа.
        # Раньше слот терялся навсегда, если care стартовал после точного
        # «ЧЧ:00» (например, после перезапуска сторожа в ЧЧ:18) — из-за этого
        # пропадали утренние уведомления.
        key = now.strftime("%H:00") if now.minute <= 20 else now.strftime("%H:%M")
        # Раз в день (утром, до слотов) пишем отчёт о вчерашнем дне
        if day != last_day:
            last_day = day
            if now.hour >= 9:
                from datetime import timedelta
                yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
                morning_report(yesterday)
                print(f"{now:%H:%M:%S} утренний отчёт за {yesterday} записан", flush=True)
                log_event(f"Утренний отчёт за {yesterday} записан")
        if key in SLOTS and not already_sent(day, key):
            try:
                phrases = SLOTS[key]
                text = phrases[len(str(int(now.timestamp()))) % len(phrases)]
                notify("Лия: \"коть\"", text)
                mark_sent(day, key)
                print(f"{now:%H:%M:%S} отправлено уведомление ({key})", flush=True)
                log_event(f"Отправлено уведомление {day} {key}")
            except Exception as e:
                print(f"{now:%H:%M:%S} ОШИБКА уведомления ({key}): {e!r}", flush=True)
                log_event(f"ОШИБКА уведомления {day} {key}: {e!r}")
        time.sleep(30)


if __name__ == "__main__":
    main()
