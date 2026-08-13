# -*- coding: utf-8 -*-
"""Пересоздаёт службу zapret из аргументов general.bat (используется при восстановлении)."""
import subprocess
import sys
from pathlib import Path

BASE = Path(r"C:\запрет")
BAT = BASE / "general.bat"
WINWS = BASE / "bin" / "winws.exe"
LISTS = BASE / "lists"
GAME_TCP = "12"   # game-фильтр выключен
GAME_UDP = "12"

text = BAT.read_text(encoding="utf-8", errors="replace")
# убираем переносы строк и символы продолжения строк '^'
flat = text.replace("\r\n", " ").replace("\n", " ").replace("^", "")
marker = '"%BIN%winws.exe"'
idx = flat.find(marker)
if idx == -1:
    print("Не найден вызов winws.exe в general.bat")
    sys.exit(1)
args = flat[idx + len(marker):].strip()
args = args.replace("%BIN%", str(BASE / "bin") + "\\")
args = args.replace("%LISTS%", str(LISTS) + "\\")
args = args.replace("%LISTS%", str(LISTS) + "\\")
args = args.replace("%GameFilterTCP%", GAME_TCP)
args = args.replace("%GameFilterUDP%", GAME_UDP)

binpath = '"' + str(WINWS) + '" ' + args
print("BINPATH length:", len(binpath))
print(binpath[:200], "...")

# убиваем автономный winws (если есть), чтобы не конфликтовал со службой
try:
    subprocess.run(["taskkill", "/F", "/IM", "winws.exe"], capture_output=True, text=True, timeout=20)
    print("taskkill winws -> ok")
except Exception as e:
    print("taskkill winws EXC", e)

for cmd in (
    ["sc.exe", "stop", "zapret"],
    ["sc.exe", "delete", "zapret"],
):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        print(">>", " ".join(cmd), "->", r.returncode, r.stdout.strip()[:120], r.stderr.strip()[:120])
    except Exception as e:
        print(">>", " ".join(cmd), "EXC", e)

r = subprocess.run(
    ["sc.exe", "create", "zapret", "binPath=", binpath, "DisplayName=", "zapret", "start=", "auto"],
    capture_output=True, text=True, timeout=60,
)
print("CREATE ->", r.returncode, r.stdout.strip()[:300], r.stderr.strip()[:300])
r2 = subprocess.run(["sc.exe", "start", "zapret"], capture_output=True, text=True, timeout=60)
print("START ->", r2.returncode, r2.stdout.strip()[:300], r2.stderr.strip()[:300])
