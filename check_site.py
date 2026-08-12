# -*- coding: utf-8 -*-
"""Быстрая проверка сайта через обход zapret.

Запуск:
    python check_site.py crushon.ai
    python check_site.py crushon.ai api.crushon.ai www.crushon.ai

Для каждого домена делает HTTPS-запрос и печатает код ответа.
Код 200/301/403 = сайт отвечает (обход применился, 403 — антибот сайта).
Timeout / 000 = сайт не открывается (блокировка на маршруте).
"""
import subprocess
import sys
from pathlib import Path

NO_WINDOW = 0x08000000


def http(url, timeout=12):
    try:
        r = subprocess.run(
            ["curl.exe", "-s", "-o", "NUL", "-w", "%{http_code}",
             "--connect-timeout", "6", "--max-time", str(timeout), url],
            capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW)
        return (r.stdout or "").strip() or "ERR"
    except Exception as exc:
        return f"ERR {exc}"


def resolve(domain):
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Resolve-DnsName -Name '{domain}' -Type A -ErrorAction SilentlyContinue | Where-Object IPAddress).IPAddress -join ', '"],
            capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
        return (r.stdout or "").strip() or "нет записи"
    except Exception:
        return "?"


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    print("Проверка сайтов через обход zapret:")
    print("=" * 55)
    for dom in sys.argv[1:]:
        dom = dom.strip()
        if not dom:
            continue
        ip = resolve(dom.lstrip("http://").rstrip("/"))
        code = http(f"https://{dom.lstrip('http://').rstrip('/')}/")
        verdict = "OK" if code in ("200", "301", "302", "403") else "NE DOSTUPEN"
        print(f"{dom:30} {code:4}  {verdict}  (DNS: {ip})")
    print("=" * 55)
    print("403 — сайт отвечает, но это антибот (в браузере откроется).")


if __name__ == "__main__":
    main()