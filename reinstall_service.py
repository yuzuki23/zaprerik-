# -*- coding: utf-8 -*-
"""Пересоздаёт службу zapret из активной стратегии (config.json -> strategy).

Сделано идемпотентным (3.0.2): если служба уже зарегистрирована и её binPath
совпадает с вычисленным из активной стратегии — НЕ удаляем и НЕ пересоздаём её
(sc delete/sc create пропускаются). Это устраняет хрупкость, когда служба
«сама удалялась» при каждой попытке поднятия. Пересоздание только если служба
отсутствует либо binPath изменился.

В 5.0.8 активная стратегия читается из config.json (поле strategy), а не
жёстко из general.bat — при падении winws восстанавливается именно она.
"""
import json
import subprocess
import sys
from pathlib import Path

BASE = Path(r"C:\запрет")
WINWS = BASE / "bin" / "winws.exe"
LISTS = BASE / "lists"
GAME_TCP = "12"   # game-фильтр выключен
GAME_UDP = "12"


def pick_active_bat():
    """Возвращает путь к .bat активной стратегии из config.json (fallback general.bat)."""
    cfg = {}
    try:
        cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    name = str(cfg.get("strategy", "") or "general").strip()
    for candidate in (name if name.lower().endswith(".bat") else name + ".bat",
                      "general.bat"):
        p = BASE / candidate
        if p.exists():
            return p
    return BASE / "general.bat"


BAT = pick_active_bat()

text = BAT.read_text(encoding="utf-8", errors="replace")
# убираем переносы строк и символы продолжения строк '^'
flat = text.replace("\r\n", " ").replace("\n", " ").replace("^", "")
marker = '"%BIN%winws.exe"'
idx = flat.find(marker)
if idx == -1:
    print(f"Не найден вызов winws.exe в {BAT.name}")
    sys.exit(1)
args = flat[idx + len(marker):].strip()
args = args.replace("%BIN%", str(BASE / "bin") + "\\")
args = args.replace("%LISTS%", str(LISTS) + "\\")
args = args.replace("%GameFilterTCP%", GAME_TCP)
args = args.replace("%GameFilterUDP%", GAME_UDP)

binpath = '"' + str(WINWS) + '" ' + args
print(f"Активная стратегия: {BAT.name}")
print("BINPATH length:", len(binpath))
print(binpath[:200], "...")


def run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        print(">>", " ".join(cmd), "->", r.returncode,
              r.stdout.strip()[:200], r.stderr.strip()[:200])
        return r
    except Exception as e:
        print(">>", " ".join(cmd), "EXC", e)
        return None


def norm(p):
    return p.replace('"', '').strip()


# убиваем автономный winws (если есть), чтобы не конфликтовал со службой
try:
    subprocess.run(["taskkill", "/F", "/IM", "winws.exe"], capture_output=True, text=True, timeout=20)
    print("taskkill winws -> ok")
except Exception as e:
    print("taskkill winws EXC", e)

# Проверяем, существует ли служба и совпадает ли binPath
need_recreate = True
rq = run(["sc.exe", "query", "zapret"])
if rq is not None and rq.returncode == 0 and "STATE" in rq.stdout:
    qc = run(["sc.exe", "qc", "zapret"])
    existing = ""
    if qc is not None:
        for ln in qc.stdout.splitlines():
            if "BINARY_PATH_NAME" in ln:
                existing = ln.split(":", 1)[-1].strip()
    if existing and norm(existing) == norm(binpath):
        print("Служба уже существует с корректным binPath — пересоздание не требуется")
        need_recreate = False
    else:
        print("Служба есть, но binPath отличается — пересоздаю")
else:
    print("Служба отсутствует — создаю")

if need_recreate:
    run(["sc.exe", "stop", "zapret"])
    run(["sc.exe", "delete", "zapret"])
    r = run(["sc.exe", "create", "zapret", "binPath=", binpath,
             "DisplayName=", "zapret", "start=", "auto"])
    if r is None or r.returncode != 0:
        print("CREATE FAIL — выход")
        sys.exit(1)
else:
    print("Пропускаем sc create (служба в порядке)")

r2 = run(["sc.exe", "start", "zapret"])
print("START ->", r2.returncode if r2 else "none",
      (r2.stdout.strip()[:200] if r2 else ""),
      (r2.stderr.strip()[:200] if r2 else ""))
