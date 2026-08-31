# -*- coding: utf-8 -*-
"""Автоматический релиз Zapretik (GitHub).

Запуск (из C:\\запрет):
    python release.py            # создать релизы GitHub для ВСЕХ тегов, которых ещё нет
    python release.py all        # то же самое
    python release.py 3.0.7      # полный релиз версии: bump -> commit -> push -> tag -> RAR -> релиз GitHub
    python release.py 3.0.7 notes.txt

Создание релиза на GitHub:
 - Через GitHub CLI (gh): скрипт вызывает `gh release create` с архивом.
 - Иначе — через GitHub API с токеном: токен берётся из переменной GITHUB_TOKEN
   или файла github_token.txt (он в .gitignore, не коммитится). PAT создаётся
   один раз в настройках GitHub (Settings → Developer settings → Fine-grained tokens).
 - Иначе — запасной путь через твой Chrome (Playwright + CDP): скрипт
   подключается к уже открытому Chrome с --remote-debugging-port=9222,
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
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PROJ = Path(r"C:\запрет")
RAR = Path(r"C:\Program Files\WinRAR\Rar.exe")
OUT = Path(r"C:\Users\Leonid\AppData\Local\Temp\opencode\zapret_test")
REPO_GH = "yuzuki23/zaprerik-"
BASE = "https://github.com"
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
    return f"{BASE}/{REPO_GH}/releases/edit/{tag}"


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


RELEASE_PROFILE = PROJ / "_release_profile"
_PROFILE_EXCLUDES = ["Cache", "Code Cache", "GPUCache", "Service Worker", "Session Storage",
                     "IndexedDB", "blob_storage", "Extensions", "File System", "Media Cache",
                     "Optimization Guide", "Segmentation", "Download Service", "Subresource Filter",
                     "Crashpad", "Recovery", "GrShaderCache", "ShaderCache", "Site Settings"]


def ensure_chrome():
    if chrome_debug_up():
        return
    exe = find_chrome()
    if not exe:
        raise RuntimeError("Chrome не найден")
    # Копируем живой профиль во временный каталог, чтобы не трогать открытый Chrome
    # и не требовать его закрытия. Cookies (v10/v20) привязаны к учётке, поэтому
    # скопированные куки расшифровываются (нужен Local State = ключ шифрования).
    # ВАЖНО: если во временном профиле уже есть своя база кук (например, после
    # ручного входа в GitHub один раз) — НЕ перезатираем её свежей копией,
    # иначе потеряем рабочую сессию релиза.
    has_cookies = (RELEASE_PROFILE / "Default" / "Network" / "Cookies").exists()
    if not has_cookies:
        ls_src = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\Local State")
        if os.path.exists(ls_src):
            try:
                shutil.copy2(ls_src, str(RELEASE_PROFILE / "Local State"))
            except Exception:
                pass
        src = os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data\Default")
        dst = str(RELEASE_PROFILE / "Default")
        if os.path.exists(src):
            args = ["robocopy", src, dst, "/E", "/COPY:DAT", "/R:1", "/W:1",
                    "/NFL", "/NDL", "/NJH", "/NJS"]
            for e in _PROFILE_EXCLUDES:
                args += ["/XD", e]
            args += ["/XF", "Lock", "Cookies-journal", "SingletonLock"]
            try:
                subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
            except Exception:
                pass
    subprocess.Popen(
        [exe, "--remote-debugging-port=9222", "--remote-allow-origins=*",
         f"--user-data-dir={str(RELEASE_PROFILE)}", "--no-first-run", "--no-default-browser-check"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        if chrome_debug_up():
            return
        time.sleep(1)
    raise RuntimeError("Chrome с отладкой не запустился")


def connect():
    ensure_chrome()
    p = sync_playwright().start()
    browser = p.chromium.connect_over_cdp(CDP)
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.set_default_timeout(30000)
    return p, browser, page


# ---------- создание релиза на GitHub ----------
def create_release(page, tag, prev, desc_override=None, asset_path=None, _retry=True):
    page.goto(f"{BASE}/{REPO_GH}/releases/new", wait_until="domcontentloaded")
    page.wait_for_url("**/yuzuki23/zaprerik-/releases/new", timeout=60000)
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


# ---------- API-релиз (GitHub PAT, без Chrome/входа) ----------
API_BASE = "https://api.github.com"


def get_github_token():
    env = os.environ.get("GITHUB_TOKEN")
    if env:
        return env.strip()
    f = PROJ / "github_token.txt"
    if f.exists():
        return f.read_text(encoding="utf-8-sig").strip()
    return None


def _api(method, path, token, data=None, raw=None, ctype="application/json"):
    url = API_BASE + path
    body = json.dumps(data).encode() if data is not None else raw
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:  # pragma: no cover
        return -1, str(e)


def find_release_id(tag, token):
    st, out = _api("GET", f"/repos/{REPO_GH}/releases?per_page=100", token)
    if st != 200:
        return None
    try:
        items = json.loads(out)  # GitHub returns array directly, not wrapped in "data"
    except Exception:
        return None
    for rel in items:
        if rel.get("tag_name") == tag:
            return rel.get("id")
    return None


def create_release_api(tag, prev, desc_override=None, asset_path=None, token=None):
    if token is None:
        token = get_github_token()
    if not token:
        return False, "нет GitHub токена (GITHUB_TOKEN / github_token.txt)"
    desc = desc_override if desc_override is not None else (notes_for(tag) or changelog(tag, prev))
    rid = find_release_id(tag, token)
    if rid is None:
        st, out = _api("POST", f"/repos/{REPO_GH}/releases", token,
                       data={"tag_name": tag, "name": tag, "body": desc,
                             "draft": False, "prerelease": False})
        if st not in (200, 201):
            return False, f"создание релиза {st}: {out[:300]}"
        try:
            rid = json.loads(out).get("id")
        except Exception:
            rid = None
    else:
        _api("PATCH", f"/repos/{REPO_GH}/releases/{rid}", token,
             data={"body": desc, "name": tag})
    if rid and asset_path and Path(asset_path).exists():
        data = Path(asset_path).read_bytes()
        name = Path(asset_path).name
        st, out = _api("POST",
                       f"/repos/{REPO_GH}/releases/{rid}/assets?name={urllib.parse.quote(name)}",
                       token, raw=data, ctype="application/octet-stream")
        if st not in (200, 201):
            low = (out or "").lower()
            if st != 409 and "already" not in low:
                return False, f"загрузка ассета {st}: {out[:300]}"
    return True, f"{BASE}/{REPO_GH}/releases/tag/{tag}"


def publish_release(tag, notes=None, rar=None):
    """Создать релиз: по API при наличии токена, иначе (или при ошибке API) — через Chrome."""
    tags = git_tags()
    prev = None
    for t in tags:
        if t == tag:
            break
        prev = t
    token = get_github_token()
    if token:
        ok, msg = create_release_api(tag, prev, desc_override=notes, asset_path=rar, token=token)
        if ok:
            return ok, msg
        print(f"[!] API-релиз не вышел ({msg}), фолбэк на Chrome")
    _, _, page = connect()
    return create_release(page, tag, prev, desc_override=notes, asset_path=rar)


# ---------- режимы ----------
def cmd_all():
    tags = git_tags()
    prev = None
    for tag in tags:
        ok, msg = publish_release(tag)
        print(f"[{'+' if ok else '='}] {tag}: {msg}")
        prev = tag
    print("[*] готово ->", f"{BASE}/{REPO_GH}/releases")


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

    print("[5/5] релиз GitHub")
    ok, msg = publish_release(tag, notes, rar)
    if ok:
        print("  релиз:", f"{BASE}/{REPO_GH}/releases/tag/{tag}")
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
