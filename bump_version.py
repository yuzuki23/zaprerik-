# -*- coding: utf-8 -*-
"""Повышение версии Zapretik.

Единый источник версии — config.json. Этот скрипт при выпуске новой версии
обновляет config.json и все зависимые файлы (version.txt, service.bat,
fallback внутри watchdog.py):

    python bump_version.py 5.0.5

main.py и care.py читают версию прямо из config.json в рантайме, их править не нужно.
"""
import json
import re
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent


def version_ok(v):
    return isinstance(v, str) and re.fullmatch(r"\d+\.\d+\.\d+", v) is not None


def bump(new_ver: str):
    if not version_ok(new_ver):
        print(f"ОШИБКА: версия должна быть в формате X.Y.Z, получено: {new_ver!r}")
        sys.exit(1)

    # config.json — главный источник
    cfg_path = PROJ / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    old = str(cfg.get("version", ""))
    cfg["version"] = new_ver
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # .service/version.txt
    (PROJ / ".service" / "version.txt").write_text(new_ver + "\n", encoding="utf-8")

    # service.bat
    sb = PROJ / "service.bat"
    sb.write_text(
        re.sub(
            r'set "LOCAL_VERSION=[^"]+"',
            f'set "LOCAL_VERSION={new_ver}"',
            sb.read_text(encoding="utf-8"),
        ),
        encoding="utf-8",
    )

    # watchdog.py: fallback-значения версии (если config битый) обновляем целиком
    wd = PROJ / "watchdog.py"
    wt = wd.read_text(encoding="utf-8")
    if version_ok(old) and old != new_ver:
        wt = wt.replace(old, new_ver)
        wd.write_text(wt, encoding="utf-8")

    print(f"Версия {old or '(отсутствует)'} -> {new_ver} обновлена: config.json, .service/version.txt, service.bat, watchdog.py")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python bump_version.py 5.0.5")
        sys.exit(1)
    bump(sys.argv[1])