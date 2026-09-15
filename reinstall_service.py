# -*- coding: utf-8 -*-
"""Пересоздаёт службу zapret из активной стратегии (config.json -> strategy).

Сделано идемпотентным (3.0.2): если служба уже зарегистрирована и её binPath
совпадает с вычисленным из активной стратегии — НЕ удаляем и НЕ пересоздаём её
(sc delete/sc create пропускаются). Это устраняет хрупкость, когда служба
«сама удалялась» при каждой попытке поднятия. Пересоздание только если служба
отсутствует либо binPath изменился.

В 5.0.8 активная стратегия читается из config.json (поле strategy), а не
жёстко из general.bat — при падении winws восстанавливается именно она.

In 6.0.1 весь запускаемый код перенесён под if __name__ == "__main__": импорт
модуля больше не убивает winws и не трогает службу.
"""
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(r"C:\запрет")
LOG = BASE / "reinstall.log"
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


def build_binpath():
    """Собирает binPath службы из аргументов активной стратегии.

    Берутся только реальные аргументы winws: строки, начинающиеся с "--"
    после вызова "%BIN%winws.exe", до первого комментария/FALLBACK-блока.
    Возвращает (имя-стратегии, binpath).
    """
    bat = pick_active_bat()
    text = bat.read_text(encoding="utf-8", errors="replace")
    marker = '"%BIN%winws.exe"'
    found = False
    args_parts = []
    for raw in text.splitlines():
        s = raw.strip()
        if not found:
            if marker in s and (s.startswith("start") or s.startswith('"%BIN%winws.exe"')):
                tail = s.split(marker, 1)[1].strip()
                if tail:
                    args_parts.append(tail)
                found = True
            continue
        if s.startswith("--"):
            args_parts.append(s.rstrip("^").strip())
        elif s.startswith("::") or s.startswith("timeout"):
            break
    if not found:
        raise RuntimeError(f"Не найден вызов winws.exe в {bat.name}")
    args = " ".join(args_parts).strip()
    args = args.replace("%BIN%", str(BASE / "bin") + "\\")
    args = args.replace("%LISTS%", str(LISTS) + "\\")
    args = args.replace("%GameFilterTCP%", GAME_TCP)
    args = args.replace("%GameFilterUDP%", GAME_UDP)
    return bat.name, '"' + str(WINWS) + '" ' + args


def run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        print(">>", " ".join(cmd), "->", r.returncode,
              r.stdout.strip()[:200], r.stderr.strip()[:200])
        return r
    except Exception as e:
        print(">>", " ".join(cmd), "EXC", e)
        return None


def log_line(msg):
    """Дублирует вывод в reinstall.log — сторож запускает скрипт с
    capture_output, поэтому stdout иначе не виден при диагностике."""
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    except Exception:
        pass


def norm(p):
    return p.replace('"', '').strip()


def canonical_binpath(p):
    """Канонический вид binPath для сравнения.

    winws понимает и «--flag=value», и «--flag value», а sc qc может вернуть
    одну форму, а build_binpath — другую. Приводим обе к единому виду
    («--flag value»), чтобы reinstall не пересоздавал работающую службу
    из-за чисто синтаксического расхождения (и не рвал WinDivert/winws).
    """
    out = []
    for t in norm(p).split():
        if t.startswith("--") and "=" in t and re.fullmatch(r"--[\w:-]+=.+", t):
            flag, val = t.split("=", 1)
            out.append(flag + " " + val)
        else:
            out.append(t)
    return " ".join(out)


def main():
    bat_name, binpath = build_binpath()
    print("Активная стратегия:", bat_name)
    print("BINPATH length:", len(binpath))
    print(binpath[:200], "...")

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
        state_line = next((l for l in rq.stdout.splitlines() if "STATE" in l), "")
        # ХОТФИКС: работающую службу НЕ трогаем даже при расхождении binPath —
        # пересоздание выгружает WinDivert и валит живой обход.
        if "RUNNING" in state_line:
            print("Служба zapret уже РАБОТАЕТ — не трогаю (пересоздание = сброс WinDivert)")
            log_line("Служба zapret RUNNING — выход без изменений")
            return
        qc = run(["sc.exe", "qc", "zapret"])
        existing = ""
        if qc is not None:
            for ln in qc.stdout.splitlines():
                if "BINARY_PATH_NAME" in ln:
                    existing = ln.split(":", 1)[-1].strip()
        if existing and canonical_binpath(existing) == canonical_binpath(binpath):
            print("Служба уже существует с корректным binPath — пересоздание не требуется")
            log_line("Служба существует, binPath совпадает — пересоздание не требуется")
            need_recreate = False
        else:
            print("Служба есть, но binPath отличается — пересоздаю")
            log_line(f"Пересоздание: binPath отличается. Существующий: {canonical_binpath(existing)[:120]!r} vs новый: {canonical_binpath(binpath)[:120]!r}")
    else:
        print("Служба отсутствует — создаю")
        log_line("Служба отсутствует — создаю")

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


if __name__ == "__main__":
    main()