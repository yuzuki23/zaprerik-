# -*- coding: utf-8 -*-
"""Заботливый будильник: периодически шлёт Windows-уведомления с тёплыми фразами.

Запуск:
    python care.py
"""
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

os.system("")

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
MAX_LOG_SIZE = 512 * 1024  # 512 КБ
KEEP_LOGS = 3


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


def morning_report(day):
    """Утренний отчёт в дневник: сколько слотов вчера отправлено будильником."""
    rotate(SENT)
    if not SENT.exists():
        return
    yesterday = SENT.read_text(encoding="utf-8").splitlines()
    sent = sum(1 for ln in yesterday if ln.startswith(day))
    text = f"- 🔔 Будильник: {sent} слотов отправлено ({day}).\n"
    try:
        with REPORTS.open("a", encoding="utf-8") as f:
            f.write("\n" + text)
    except Exception:
        pass


def notify(title, text):
    ps1 = (
        "Add-Type -AssemblyName System.Windows.Forms\n"
        "Add-Type -AssemblyName System.Drawing\n"
        "$n=New-Object System.Windows.Forms.NotifyIcon\n"
        "$n.Icon=[System.Drawing.SystemIcons]::Information\n"
        "$n.Visible=$true\n"
        f"$n.ShowBalloonTip(15000,'{title}','{text}',[System.Windows.Forms.ToolTipIcon]::Info)\n"
        "$t=New-Object System.Windows.Forms.Timer\n"
        "$t.Interval=16000\n"
        "$t.Add_Tick({$n.Visible=$false;$n.Dispose();[System.Windows.Forms.Application]::Exit()})\n"
        "$t.Start()\n"
        "[System.Windows.Forms.Application]::Run()\n"
    )
    path = Path(os.environ.get("TEMP", r"C:\запрет")) / "care_notify.ps1"
    path.write_text(ps1, encoding="utf-8-sig")
    subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden",
                      "-ExecutionPolicy", "Bypass", "-File", str(path)],
                     creationflags=subprocess.CREATE_NO_WINDOW)


def already_sent(day, slot):
    if not SENT.exists():
        return False
    return f"{day} {slot}" in SENT.read_text(encoding="utf-8")


def mark_sent(day, slot):
    with SENT.open("a", encoding="utf-8") as f:
        f.write(f"{day} {slot}\n")


def morning_report(day):
    """Утренний отчёт в дневник: сколько слотов вчера отправлено будильником."""
    rotate(SENT)
    if not SENT.exists():
        return
    lines = SENT.read_text(encoding="utf-8").splitlines()
    sent = sum(1 for ln in lines if ln.startswith(day))
    text = f"- 🔔 Будильник: за вчера ({day}) отправлено слотов: {sent}.\n"
    try:
        with REPORTS.open("a", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass


def main():
    print("Заботливый будильник запущен. Слоты:", ", ".join(SLOTS.keys()))
    last_day = None
    while True:
        now = datetime.now()
        key = now.strftime("%H:%M")
        day = now.strftime("%Y-%m-%d")
        # Раз в день (утром, до слотов) пишем отчёт о вчерашнем дне
        if day != last_day:
            last_day = day
            if now.hour >= 9:
                from datetime import timedelta
                yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
                morning_report(yesterday)
                print(f"{now:%H:%M:%S} утренний отчёт за {yesterday} записан", flush=True)
        if key in SLOTS and not already_sent(day, key):
            try:
                phrases = SLOTS[key]
                text = phrases[len(str(int(now.timestamp()))) % len(phrases)]
                notify("Лия: \"коть\"", text)
                mark_sent(day, key)
                print(f"{now:%H:%M:%S} отправлено уведомление ({key})", flush=True)
            except Exception as e:
                print(f"{now:%H:%M:%S} ОШИБКА уведомления ({key}): {e}", flush=True)
        time.sleep(30)


if __name__ == "__main__":
    main()
