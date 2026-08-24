# -*- coding: utf-8 -*-
"""Погода с Яндекс.Погоды (ТОЛЬКО Яндекс, не wttr.in) по координатам.

Яндекс засовывает невидимые разделители (WORD JOINER и ко) внутрь слов и
дробит сводку вложенными тегами, поэтому парсим по ключевым фразам по всему
тексту, предварительно вычистив невидимки и сущность &deg;. Пишет
weather_out.txt рядом с собой и выводит в консоль.
"""
import os
import re
import requests

HEAD = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# (имя для дневника, lat, lon)
CITIES = [
    ("Ессентуки (Пятигорск)", "44.0486", "43.0578"),
    ("Ставрополь", "45.0448", "41.9694"),
    ("Минеральные Воды", "44.2114", "43.1313"),
]


def _clean(html):
    s = html.replace("&deg;", "°").replace("\u200c", "")
    for ch in ("\u2060", "\u200b", "\u200d", "\u00ad", "\ufeff", "\u202f", "\u200a"):
        s = s.replace(ch, "")
    return s


def parse(html):
    s = _clean(html)
    # состояние: слово(а) перед первой запятой, предшествующей
    # «температура воздуха» (текущая сводка, а не виджет «на карте»)
    cm = re.search(r'([А-Яа-яёЁ\-]+)\s*,\s*[^.]+?температура воздуха', s)
    cond = cm.group(1).strip() if cm else "?"
    # температура (текущая «воздуха»)
    tm = re.search(r'температура воздуха[^\d]{0,15}(\d+)\s*°', s)
    temp = (tm.group(1) + "°") if tm else "?"
    # ветер (допускаем десятичную запятую, напр. «1,7 м/с», и любой регистр)
    wm = re.search(r'[Вв]етер\s*(\d+(?:[,.]\d+)?)\s*м/с', s)
    wind = (wm.group(1) + " м/с") if wm else "?"
    return temp, cond, wind


def fetch(name, lat, lon):
    try:
        url = f"https://yandex.ru/pogoda/?lat={lat}&lon={lon}"
        r = requests.get(url, headers=HEAD, timeout=25)
        temp, cond, wind = parse(r.text)
        return f"{name}: {cond} {temp}, ветер {wind}"
    except Exception as e:
        return f"{name}: ошибка ({e})"


def main():
    lines = [fetch(n, la, lo) for n, la, lo in CITIES]
    text = "\n".join(lines)
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "weather_out.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
