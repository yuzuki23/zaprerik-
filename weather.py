# -*- coding: utf-8 -*-
"""Погода из Яндекс.Погоды для Ессентуков или Ставрополя.

Запуск:
    python weather.py essentuki
    python weather.py stavropol

Для города делает запрос к yandex.ru/pogoda/<город>, берёт HTML и вытаскивает
температуру, состояние, ветер, влажность, давление — текст рядом со словом «сейчас».
"""
import html
import re
import sys
from urllib.request import Request, urlopen

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CITIES = {
    "essentuki": {"url": "https://yandex.ru/pogoda/region/essentuki", "name": "Ессентуки"},
    "essentuki2": {"url": "https://yandex.ru/pogoda/essentuki", "name": "Ессентуки"},
    "yessentuki": {"url": "https://yandex.ru/pogoda/region/yessentuki", "name": "Ессентуки"},
    "stavropol": {"url": "https://yandex.ru/pogoda/stavropol", "name": "Ставрополь"},
}


def fetch(url, timeout=15):
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    with urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def strip_tags(s):
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def fact_extract(html_text):
    """Достаёт фактические параметры погоды «сейчас» из HTML."""
    out = {}

    # 1) Универсальный источник: текст рядом со словом «сейчас»
    #    «погода сейчас: Облачно с прояснениями... Температура воздуха +31°, ощущается как +31°.
    #    Скорость ветра 4 м/с, восточный. Давление 716 мм рт.ст.. Влажность 34%.»
    m = re.search(r'(?:сейчас|Сейчас)[:.»\s]{0,20}([^<]{10,400})', html_text)
    if m:
        seg = m.group(1)
        m2 = re.search(r'([:]\s*)?([А-ЯЁа-яё][^.,\n]{2,40}?)[.,]', seg)
        if m2:
            out["cond"] = m2.group(2).strip()
        m2 = re.search(r'Температур[а-яё\s]*\s+([+-]?\d+°?)', seg)
        if m2:
            out["temp"] = m2.group(1)
        m2 = re.search(r'ощущается как\s+([+-]?\d+°?)', seg, re.I)
        if m2:
            out["feels"] = m2.group(1)
        m2 = re.search(r'Скорость ветра\s+(\d+)\s*м/с', seg, re.I)
        if m2:
            out["wind"] = m2.group(1) + " м/с"
        m2 = re.search(r'Давление\s+(\d+)\s*мм', seg, re.I)
        if m2:
            out["pressure"] = m2.group(1) + " мм"
        m2 = re.search(r'Влажность\s+(\d+)\s*%', seg, re.I)
        if m2:
            out["humidity"] = m2.group(1) + "%"
        if out:
            return out

    # 2) Fallback из факт-блока: температура/состояние/ветер/влажность
    m = re.search(r'temp__value[^>]*>\s*([^<]+?°)\s*<', html_text)
    if m:
        out["temp"] = m.group(1).strip()
    m = re.search(r'class="link__condition[^"]*"[^>]*>\s*([^<]+?)\s*<', html_text)
    if m:
        out["cond"] = strip_tags(m.group(1))
    m = re.search(r'[Оо]щущается[^<]{0,40}([+-]?\d+°?)', html_text)
    if m:
        out["feels"] = m.group(1)
    m = re.search(r'([+-]?\d+)\s*м/с', html_text)
    if m:
        out["wind"] = m.group(1) + " м/с"
    m = re.search(r'Влажность[^<]{0,60}?(\d+)\s*%', html_text)
    if m:
        out["humidity"] = m.group(1) + "%"
    m = re.search(r'Давление[^<]{0,60}?(\d+)\s*мм', html_text)
    if m:
        out["pressure"] = m.group(1) + " мм"

    return out


def main():
    if len(sys.argv) < 2:
        print("Использование: python weather.py essentuki | stavropol")
        sys.exit(1)
    city = sys.argv[1].strip().lower()
    if city not in CITIES:
        print(f"Не знаю город '{city}'. Доступны: essentuki, stavropol")
        sys.exit(1)

    for key in (city,):
        info = CITIES[key]
        try:
            page = fetch(info["url"])
        except Exception as exc:
            print(f"Не получилось загрузить {info['url']}: {exc}")
            sys.exit(1)
        f = fact_extract(page)

        print(f"Погода сейчас — {info['name']}")
        print("=" * 32)
        print(f"Температура:   {f.get('temp', '?')}")
        print(f"Состояние:     {f.get('cond', '?')}")
        print(f"Ощущается как: {f.get('feels', '?')}")
        print(f"Ветер:         {f.get('wind', '?')}")
        print(f"Влажность:     {f.get('humidity', '?')}")
        print(f"Давление:      {f.get('pressure', '?')}")
        if not f:
            print("(не удалось распарсить — Яндекс мог изменить вёрстку)")


if __name__ == "__main__":
    main()