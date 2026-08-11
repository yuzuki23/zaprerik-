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


def main():
    print("Заботливый будильник запущен. Слоты:", ", ".join(SLOTS.keys()))
    while True:
        now = datetime.now()
        key = now.strftime("%H:%M")
        day = now.strftime("%Y-%m-%d")
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
