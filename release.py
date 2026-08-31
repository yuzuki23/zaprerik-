# -*- coding: utf-8 -*-
"""Автоматический релиз Zapretik (GitHub API).

Запуск (из C:\\запрет):
    python release.py            # создать релизы GitHub для ВСЕХ тегов, которых ещё нет
    python release.py all        # то же самое
    python release.py 4.0.2      # полный релиз версии: bump -> commit -> push -> tag -> RAR -> релиз GitHub
    python release.py 4.0.2 notes.txt

Создание релиза на GitHub:
 - Через GitHub REST API с токеном: токен берётся из переменной GITHUB_TOKEN
   или файла github_token.txt (в .gitignore, не коммитится).
"""
import json
import os
import re
import shutil
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
API_BASE = "https://api.github.com"
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


# ---------- RAR ----------
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
    """Собрать RAR для исторического тега, не трогая живой сервис."""
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


# ---------- GitHub API ----------
def get_github_token():
    env = os.environ.get("GITHUB_TOKEN")
    if env:
        return env.strip()
    f = PROJ / "github_token.txt"
    if f.exists():
        return f.read_text(encoding="utf-8-sig").strip()
    return None


def _api(method, url, token, data=None, raw=None, ctype="application/json"):
    body = json.dumps(data).encode() if data is not None else raw
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", "zapretik")
    if body is not None:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return -1, str(e)


def find_release_id(tag, token):
    st, out = _api("GET", f"{API_BASE}/repos/{REPO_GH}/releases?per_page=100", token)
    if st != 200:
        return None
    try:
        items = json.loads(out)
    except Exception:
        return None
    for rel in items:
        if rel.get("tag_name") == tag:
            return rel.get("id")
    return None


def find_release_upload_url(tag, token):
    st, out = _api("GET", f"{API_BASE}/repos/{REPO_GH}/releases?per_page=100", token)
    if st != 200:
        return None
    try:
        items = json.loads(out)
    except Exception:
        return None
    for rel in items:
        if rel.get("tag_name") == tag:
            return rel.get("upload_url")
    return None


def create_release_api(tag, prev, desc_override=None, asset_path=None, token=None):
    if token is None:
        token = get_github_token()
    if not token:
        return False, "нет GitHub токена (GITHUB_TOKEN / github_token.txt)"
    desc = desc_override if desc_override is not None else (notes_for(tag) or changelog(tag, prev))
    rid = find_release_id(tag, token)
    if rid is None:
        st, out = _api("POST", f"{API_BASE}/repos/{REPO_GH}/releases", token,
                       data={"tag_name": tag, "name": tag, "body": desc,
                             "draft": False, "prerelease": False})
        if st not in (200, 201):
            return False, f"создание релиза {st}: {out[:300]}"
        try:
            rid = json.loads(out).get("id")
            upload_url = json.loads(out).get("upload_url")
        except Exception:
            rid = None
            upload_url = None
    else:
        _api("PATCH", f"{API_BASE}/repos/{REPO_GH}/releases/{rid}", token,
             data={"body": desc, "name": tag})
        upload_url = find_release_upload_url(tag, token)

    if rid and asset_path and Path(asset_path).exists():
        data = Path(asset_path).read_bytes()
        name = Path(asset_path).name
        if upload_url:
            asset_url = upload_url.replace("{?name,label}", f"?name={urllib.parse.quote(name)}")
        else:
            asset_url = f"{API_BASE}/repos/{REPO_GH}/releases/{rid}/assets?name={urllib.parse.quote(name)}"
        st, out = _api("POST", asset_url, token, raw=data, ctype="application/octet-stream")
        if st not in (200, 201):
            low = (out or "").lower()
            if st != 409 and "already" not in low:
                return False, f"загрузка ассета {st}: {out[:300]}"
    return True, f"https://github.com/{REPO_GH}/releases/tag/{tag}"


def publish_release(tag, notes=None, rar=None):
    """Создать релиз через GitHub API."""
    tags = git_tags()
    prev = None
    for t in tags:
        if t == tag:
            break
        prev = t
    token = get_github_token()
    if not token:
        return False, "нет GitHub токена (GITHUB_TOKEN / github_token.txt)"
    return create_release_api(tag, prev, desc_override=notes, asset_path=rar, token=token)


# ---------- режимы ----------
def cmd_all():
    tags = git_tags()
    prev = None
    for tag in tags:
        ok, msg = publish_release(tag)
        print(f"[{'+' if ok else '='}] {tag}: {msg}")
        prev = tag
    print("[*] готово ->", f"https://github.com/{REPO_GH}/releases")


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
        print("  релиз:", f"https://github.com/{REPO_GH}/releases/tag/{tag}")
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
