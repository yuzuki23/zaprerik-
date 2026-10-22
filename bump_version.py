# -*- coding: utf-8 -*-
"""Повышение версии Zapretik.

Единый источник версии — config.json. Этот скрипт при выпуске новой версии
обновляет config.json и все зависимые файлы (version.txt, fallback внутри
watchdog.py):

    python bump_version.py 5.0.5

service.bat читает версию из config.json динамически, его править не нужно.
main.py и care.py читают версию прямо из config.json в рантайме.
"""
import json
import os
import re
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent


def version_ok(v):
    return isinstance(v, str) and re.fullmatch(r"\d+\.\d+\.\d+", v) is not None


def atomic_write_text(path: Path, text: str):
    """Атомарная запись текста (временный файл + os.replace) — от обнуления файла."""
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def bump(new_ver: str):
    if not version_ok(new_ver):
        print(f"ОШИБКА: версия должна быть в формате X.Y.Z, получено: {new_ver!r}")
        sys.exit(1)

    # config.json — главный источник
    cfg_path = PROJ / "config.json"
    raw = cfg_path.read_text(encoding="utf-8")
    try:
        cfg = json.loads(raw)
    except Exception as e:
        print(f"ОШИБКА: config.json битый/пустой ({e}) — версию не поднимаю, чтобы не затереть")
        sys.exit(1)
    if not isinstance(cfg, dict) or not cfg:
        print("ОШИБКА: config.json пуст/не объект — версию не поднимаю")
        sys.exit(1)
    old = str(cfg.get("version", ""))
    cfg["version"] = new_ver
    atomic_write_text(cfg_path, json.dumps(cfg, ensure_ascii=False, indent=2) + "\n")

    # .service/version.txt
    atomic_write_text(PROJ / ".service" / "version.txt", new_ver + "\n")

    # service.bat больше не обновляем — он читает версию из config.json динамически

    # fallback-значения версии (если config битый) в watchdog.py, main.py, care.py
    if version_ok(old) and old != new_ver:
        for name in ("watchdog.py", "main.py", "care.py"):
            p = PROJ / name
            atomic_write_text(p, p.read_text(encoding="utf-8").replace(old, new_ver))

    print(f"Версия {old or '(отсутствует)'} -> {new_ver} обновлена: config.json, .service/version.txt, watchdog.py, main.py, care.py")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python bump_version.py 5.0.5")
        sys.exit(1)
    bump(sys.argv[1])