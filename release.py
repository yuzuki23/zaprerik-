# -*- coding: utf-8 -*-
"""Автоматический релиз Zapretik (GitVerse).

Запуск (из C:\\запрет):
    python release.py            # создать релизы GitVerse для ВСЕХ тегов, которых ещё нет
    python release.py all        # то же самое
    python release.py 3.0.7      # полный релиз версии: bump -> commit -> push -> tag -> RAR -> релиз GitVerse
    python release.py 3.0.7 notes.txt

Создание релиза на GitVerse делается через твой Chrome (Playwright + CDP):
скрипт подключается к уже открытому Chrome с --remote-debugging-port=9222,
а если его нет — сам запускает Chrome с твоим профилем и отладкой.
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

PROJ = Path(r"C:\запрет")
RAR = Path(r"C:\Program Files\WinRAR\Rar.exe")
OUT = Path(r"C:\Users\Leonid\AppData\Local\Temp\opencode\zapret_test")
REPO_GV = "miamura23/zapretik"
BASE = "https://gitverse.ru"
CDP = "http://127.0.0.1:9222"
SERVICE_BAT = PROJ / "service.bat"
MAIN_PY = PROJ / "main.py"
RETRIES = 12


# ---------- утилиты git ----------
def run(cmd, timeout=120):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, cwd=str(PROJ))
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def run_retry(cmd, ok_codes=(0,), timeout=120, sleep=12):
    last = None
    for _ in range(RETRIES):
        try:
            code, out = run(cmd, timeout)
        except subprocess.TimeoutExpired:
            time.sleep(sleep)
            continue
        if code in ok_codes:
            return code, out
        last = (code, out)
        time.sleep(sleep)
    raise RuntimeError(f"команда не выполнена после {RETRIES} попыток: {cmd}\n{last}")


def git_tags():
    out = subprocess.check_output(["git", "tag"], cwd=str(PROJ)).decode().split()
    def key(t):
        nums = re.findall(r"\d+", t)
        return tuple(int(x) for x in nums[:3])
    return sorted(out, key=key)


def changelog(tag, prev):
    rng = f"{prev}..{tag}" if prev else tag
    try:
        out = subprocess.check_output(
            ["git", "log", "--reverse", "--pretty=format:- %s", rng],
            cwd=str(PROJ)).decode().strip()
    except Exception:
        out = ""
    return out or f"Релиз {tag}"


def notes_for(tag):
    """Найти файл с заметками релиза (как раньше на GitHub)."""
    version = tag.lstrip("v")
    for name in (
        f"release_notes_{version}.txt",
        f"{tag}_notes.txt",
        f"notes_{version}.txt",
        f"{version}_notes.txt",
    ):
        c = PROJ / name
        if c.exists():
            return c.read_text(encoding="utf-8-sig").strip()
    return None


def replace_first(path, pattern, repl):
    text = path.read_text(encoding="utf-8-sig")
    if not re.search(pattern, text):
        raise RuntimeError(f"паттерн не найден в {path}: {pattern}")
    new = re.sub(pattern, repl, text, count=1)
    if new != text:
        path.write_text(new, encoding="utf-8")


def build_rar(tag):
    OUT.mkdir(parents=True, exist_ok=True)
    rar = OUT / f"zaprerik-{tag}.rar"
    if rar.exists():
        rar.unlink()
    code, out = run([str(RAR), "a", "-ep1", "-r", "-m5",
                     "-x*\\.git", "-x*\\.git\\*", "-x*\\__pycache__", "-x*\\__pycache__\\*",
                     "-x*.log", str(rar), "*"])
    if code != 0:
        raise RuntimeError(f"RAR не собрал архив:\n{out}")
    return rar


def build_rar_for_tag(tag):
    """Собрать RAR для исторического тега, не трогая живой сервис:
    git archive тега -> tmp, копия бинарей (winws/WinDivert) из PROJ, упаковка в RAR."""
    OUT.mkdir(parents=True, exist_ok=True)
    rar = OUT / f"zaprerik-{tag}.rar"
    if rar.exists():
        return rar
    tmp = OUT / f"_build_{tag}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    tar = tmp / "_a.tar"
    code, out = run(["git", "archive", tag, "--output", str(tar)], timeout=300)
    if code != 0:
        raise RuntimeError(f"git archive {tag} не удался:\n{out}")
    code, out = run(["tar", "-xf", str(tar), "-C", str(tmp)], timeout=300)
    if code != 0:
        raise RuntimeError(f"распаковка архива не удалась:\n{out}")
    tar.unlink()
    for f in ("winws.exe", "WinDivert.dll", "WinDivert64.sys"):
        src = PROJ / f
        if src.exists():
            shutil.copy(src, tmp / f)
    code, out = run([str(RAR), "a", "-ep1", "-r", "-m5",
                     "-x*\\.git", "-x*\\.git\\*", "-x*\\__pycache__", "-x*\\__pycache__\\*",
                     "-x*.log", str(rar), str(tmp / "*")], timeout=300)
    if code != 0:
        raise RuntimeError(f"RAR не собрал архив для {tag}:\n{out}")
    shutil.rmtree(tmp, ignore_errors=True)
    return rar


def release_edit_url(tag):
    return f"{BASE}/{REPO_GV}/releases/edit/{tag}"


def delete_release(page, tag):
    page.goto(release_edit_url(tag), wait_until="domcontentloaded")
    page.wait_for_url(f"**/releases/edit/{tag}", timeout=60000)
    page.wait_for_selector(".ProseMirror", timeout=15000)
    page.wait_for_timeout(500)
    delbtn = page.locator('button:has-text("Удалить релиз")')
    if delbtn.count() == 0:
        return False, "нет кнопки удаления"
    delbtn.first.click()
    try:
        page.wait_for_selector('div[role="dialog"]', timeout=5000)
    except Exception:
        return False, "модалка удаления не открылась"
    cfm = page.locator('div[role="dialog"] button:has-text("Удалить")')
    if cfm.count() == 0:
        return False, "нет кнопки подтверждения"
    cfm.first.click()
    page.wait_for_timeout(4000)
    return True, page.url


# ---------- Chrome / CDP ----------
def chrome_debug_up():
    try:
        s = socket.create_connection(("127.0.0.1", 9222), timeout=2)
        s.close()
        return True
    except OSError:
        return False


def find_chrome():
    for p in [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]:
        if os.path.exists(p):
            return p
    return None


def ensure_chrome():
    if chrome_debug_up():
        return
    exe = find_chrome()
    if not exe:
        raise RuntimeError("Chrome не найден")
    profile = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
    subprocess.Popen(
        [exe, "--remote-debugging-port=9222", "--remote-allow-origins=*",
         f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        if chrome_debug_up():
            return
        time.sleep(1)
    raise RuntimeError("Chrome с отладкой не запустился — закрой Chrome и повтори")


def connect():
    ensure_chrome()
    p = sync_playwright().start()
    browser = p.chromium.connect_over_cdp(CDP)
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.set_default_timeout(30000)
    return p, browser, page


# ---------- создание релиза на GitVerse ----------
def create_release(page, tag, prev, desc_override=None, asset_path=None, _retry=True):
    page.goto(f"{BASE}/{REPO_GV}/releases/new", wait_until="domcontentloaded")
    page.wait_for_url("**/miamura23/zapretik/releases/new", timeout=60000)
    page.wait_for_timeout(500)

    cb = page.locator('button:has-text("Выберите тег")')
    if cb.count() == 0:
        return False, "нет комбобокса тега"
    cb.first.click()
    page.wait_for_timeout(600)
    opt = page.get_by_role("option", name=tag, exact=True)
    if opt.count() == 0:
        return False, "тег не найден в списке"
    opt.first.click()
    page.wait_for_timeout(300)

    page.locator('input[name="title"]').fill(tag)

    desc = desc_override if desc_override is not None else (notes_for(tag) or changelog(tag, prev))
    page.locator(".ProseMirror").click()
    page.keyboard.insert_text(desc)
    page.wait_for_timeout(300)

    if asset_path:
        fi = page.locator('input[type="file"]')
        if fi.count():
            fi.first.set_input_files(str(asset_path))
            page.wait_for_timeout(1500)
        else:
            print("[!] нет file input для вложения", tag)

    pub = page.locator('button:has-text("Опубликовать релиз")')
    if pub.count() == 0:
        return False, "нет кнопки публикации"
    page.wait_for_timeout(300)
    if pub.first.is_disabled():
        return False, "кнопка заблокирована (релиз уже есть?)"
    pub.first.click()
    try:
        page.wait_for_function("() => !location.href.includes('releases/new')", timeout=30000)
        return True, page.url
    except Exception as e:
        if not _retry:
            return False, f"ожидание публикации: {e}"
        # фолбэк: 403 на создании — удаляем (если есть) и пересоздаём
        print(f"[!] создание {tag} не прошло ({e}), фолбэк удалить+пересоздать")
        try:
            delete_release(page, tag)
        except Exception:
            pass
        return create_release(page, tag, prev, desc_override, asset_path, _retry=False)


# ---------- режимы ----------
def cmd_all():
    _, _, page = connect()
    tags = git_tags()
    prev = None
    for tag in tags:
        ok, msg = create_release(page, tag, prev)
        print(f"[{'+' if ok else '='}] {tag}: {msg}")
        prev = tag
        page.wait_for_timeout(800)
    print("[*] готово ->", f"{BASE}/{REPO_GV}/releases")


def cmd_version(version, notes_file=None):
    if not re.fullmatch(r"[\w.-]+", version):
        print("Некорректная версия:", version)
        sys.exit(1)
    tag = f"v{version}"
    notes = notes_file.read_text(encoding="utf-8-sig") if notes_file else None

    print(f"[1/5] версия -> {version}")
    replace_first(SERVICE_BAT, r'set "LOCAL_VERSION=[^"]*"', f'set "LOCAL_VERSION={version}"')
    replace_first(MAIN_PY, r"Zapretik/[\w.-]+", f"Zapretik/{version}")

    print("[2/5] commit + push")
    run_retry(["git", "add", "-A"])
    run_retry(["git", "commit", "-m", f"Релиз {version}"], ok_codes=(0, 1))
    run_retry(["git", "push", "origin", "main"])

    print(f"[3/5] тег {tag}")
    subprocess.run(["git", "tag", "-d", tag], capture_output=True, cwd=str(PROJ))
    run_retry(["git", "tag", tag])
    run_retry(["git", "push", "origin", tag])

    print("[4/5] архив")
    rar = build_rar_for_tag(tag)
    print("  архив:", rar)

    print("[5/5] релиз GitVerse")
    _, _, page = connect()
    tags = git_tags()
    prev = None
    for t in tags:
        if t == tag:
            break
        prev = t
    ok, msg = create_release(page, tag, prev, desc_override=notes, asset_path=rar)
    if ok:
        print("  релиз:", f"{BASE}/{REPO_GV}/releases/tag/{tag}")
    else:
        print("  не удалось создать релиз:", msg)


def main():
    args = sys.argv[1:]
    if not args or args[0].lower() in ("all", "все"):
        cmd_all()
    else:
        notes = Path(args[1]).resolve() if len(args) > 1 else None
        cmd_version(args[0], notes)


if __name__ == "__main__":
    main()
