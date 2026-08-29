# -*- coding: utf-8 -*-
"""Авто-синхронизация папки .service в GitVerse (аналог того, что было на GitHub).

Запускается по расписанию (schtasks). Обновляет .service/version.txt до текущей
версии и коммитит/пушит изменения в .service (hosts, ipset-service.txt, version.txt),
только если они реально изменились.

Пушит в ТЕКУЩУЮ ветку (main) и в дефолтную (master), потому что на GitVerse
дефолтная ветка — master, и именно её видит пользователь. master обновляется
через временный git-worktree, чтобы не трогать живой каталог работающего сервиса.
"""
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

PROJ = Path(r"C:\запрет")
SVC = PROJ / ".service"
SERVICE_BAT = PROJ / "service.bat"
LOG = PROJ / "service_sync.log"
DEFAULT_BRANCH = "master"
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


def run(cmd, cwd=None, check=True):
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


def push_current_branch(ver, branch):
    run(["git", "fetch", "origin", branch], check=False)
    behind = run(["git", "rev-list", "--count", f"{branch}..origin/{branch}"])[1].strip()
    if behind not in ("", "0"):
        log(f"{branch} позади remote на {behind} — пропускаю push (сделай pull вручную)")
        return False

    for f in FILES:
        p = SVC / f
        if p.exists():
            run(["git", "add", "--", str(p)], check=False)
        else:
            run(["git", "rm", "--cached", "--ignore-unmatch", "--", str(p)], check=False)

    rc, out = run(["git", "diff", "--cached", "--stat", "--", ".service"])
    if not out.strip():
        log(f"{branch}: нет изменений в .service")
        return False

    rc, out = run(["git", "commit", "-m", f"bump version.txt to {ver} (label sync)"], check=False)
    if rc != 0:
        log(f"{branch}: коммит не удался: " + out.strip()[:200])
        return False

    rc, out = run(["git", "push", "origin", branch], check=False)
    if rc == 0:
        log(f"OK: запушено в {branch}")
        return True
    log(f"{branch}: PUSH НЕ УДАЛСЯ: " + out.strip()[:200])
    return False


def push_default_branch(ver):
    """Обновляет дефолтную ветку (master) копированием .service через временный worktree."""
    tmp = Path(tempfile.gettempdir()) / "zapret_master_sync"
    shutil.rmtree(tmp, ignore_errors=True)
    run(["git", "fetch", "origin", DEFAULT_BRANCH], check=False)
    run(["git", "worktree", "prune"], check=False)
    rc, out = run(["git", "worktree", "add", "--force", str(tmp), f"origin/{DEFAULT_BRANCH}"], check=False)
    if rc != 0:
        log("master: не удалось создать worktree: " + out.strip()[:200])
        shutil.rmtree(tmp, ignore_errors=True)
        return False
    try:
        dst = tmp / ".service"
        dst.mkdir(parents=True, exist_ok=True)
        for name in FILES:
            src = SVC / name
            if src.exists():
                shutil.copy2(src, dst / name)
        run(["git", "add", "--", ".service"], cwd=tmp, check=False)
        rc, out = run(["git", "diff", "--cached", "--stat", "--", ".service"], cwd=tmp)
        if not out.strip():
            log("master: нет изменений в .service")
            return False
        rc, out = run(["git", "commit", "-m", f"bump version.txt to {ver} (label sync)"], cwd=tmp, check=False)
        if rc != 0:
            log("master: коммит не удался: " + out.strip()[:200])
            return False
        rc, out = run(["git", "push", "origin", "HEAD:refs/heads/" + DEFAULT_BRANCH], cwd=tmp, check=False)
        if rc == 0:
            log("OK: запушено в master (worktree)")
            return True
        log("master: PUSH НЕ УДАЛСЯ: " + out.strip()[:200])
        return False
    finally:
        run(["git", "worktree", "remove", "--force", str(tmp)], check=False)
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    ver = current_version()
    log(f"старт, версия={ver}")
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"])[1].strip() or "main"

    update_version_txt(ver)
    push_current_branch(ver, branch)
    if DEFAULT_BRANCH != branch:
        push_default_branch(ver)


if __name__ == "__main__":
    main()
