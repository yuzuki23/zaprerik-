# -*- coding: utf-8 -*-
"""Авто-синхронизация папки .service в GitHub.

Запускается по расписанию (schtasks). Обновляет .service/version.txt до текущей
версии и коммитит/пушит изменения в .service (hosts, ipset-service.txt, version.txt),
только если они реально изменились.

Пушит в ТЕКУЩУЮ ветку (main). Master = main на GitHub, отдельная синхронизация не нужна.
"""
import re
import subprocess
from datetime import datetime
from pathlib import Path

PROJ = Path(r"C:\запрет")
SVC = PROJ / ".service"
SERVICE_BAT = PROJ / "service.bat"
LOG = PROJ / "service_sync.log"
FILES = ["version.txt", "hosts", "ipset-service.txt"]


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    print(line, end="")


def run(cmd, cwd=None):
    r = subprocess.run(cmd, cwd=str(cwd) if cwd else str(PROJ),
                        capture_output=True, text=True,
                        encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def current_version():
    try:
        t = SERVICE_BAT.read_text(encoding="utf-8-sig")
    except Exception:
        return None
    m = re.search(r'set "LOCAL_VERSION=([^"]+)"', t)
    return m.group(1) if m else None


def update_version_txt(ver):
    if not ver:
        return False
    vt = SVC / "version.txt"
    try:
        cur = vt.read_text(encoding="utf-8-sig").strip()
    except Exception:
        cur = None
    if cur != ver:
        vt.write_text(ver + "\n", encoding="utf-8")
        log(f"version.txt: {cur} -> {ver}")
        return True
    return False


def main():
    ver = current_version()
    log(f"старт, версия={ver}")
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])[1].strip() or "main"

    update_version_txt(ver)

    run(["git", "fetch", "origin", branch], check=False)
    behind = run(["git", "rev-list", "--count", f"{branch}..origin/{branch}"])[1].strip()
    if behind not in ("", "0"):
        log(f"{branch} позади remote на {behind} — пропускаю push (сделай pull вручную)")
        return

    for f in FILES:
        p = SVC / f
        if p.exists():
            run(["git", "add", "--", str(p)], check=False)
        else:
            run(["git", "rm", "--cached", "--ignore-unmatch", "--", str(p)], check=False)

    rc, out = run(["git", "diff", "--cached", "--stat", "--", ".service"])
    if not out.strip():
        log(f"{branch}: нет изменений в .service")
        return

    rc, out = run(["git", "commit", "-m", f"bump version.txt to {ver} (label sync)"], check=False)
    if rc != 0:
        log(f"{branch}: коммит не удался: " + out.strip()[:200])
        return

    rc, out = run(["git", "push", "origin", branch], check=False)
    if rc == 0:
        log(f"OK: запушено в {branch}")
    else:
        log(f"{branch}: PUSH НЕ УДАЛСЯ: " + out.strip()[:200])


if __name__ == "__main__":
    main()
