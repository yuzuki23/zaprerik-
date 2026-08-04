# -*- coding: utf-8 -*-
"""Автоматический релиз Zaprerik.

Запуск (из C:\\запрет):
    python release.py <версия> [файл_заметок.txt]

Пример:
    python release.py 1.0.3 notes.txt

Что делает:
    1) Обновляет LOCAL_VERSION в service.bat и User-Agent в main.py;
    2) git commit + push (с ретраями);
    3) создаёт и пушит git-тег v<версия>;
    4) собирает zaprerik-v<версия>.rar через WinRAR;
    5) создаёт GitHub-релиз и загружает архив;
    6) выводит ссылку на релиз.
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

PROJ = Path(r"C:\запрет")
RAR = Path(r"C:\Program Files\WinRAR\Rar.exe")
OUT = Path(r"C:\Users\Leonid\AppData\Local\Temp\opencode\zapret_test")
REPO = "yuzuki23/zaprerik-"
SERVICE_BAT = PROJ / "service.bat"
MAIN_PY = PROJ / "main.py"
RETRIES = 12


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


def git_credential():
    p = subprocess.run(["git", "credential", "fill"], input="protocol=https\nhost=github.com\n",
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15)
    for line in p.stdout.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1]
    raise RuntimeError("токен GitHub не найден (git credential fill)")


def api(method, url, token, body=None, data_file=None, timeout=120):
    args = ["curl.exe", "-s", "-o", "-", "-w", "\n__HTTP__%{http_code}", "--connect-timeout", "15",
            "--max-time", str(timeout), "-X", method,
            "-H", f"Authorization: token {token}",
            "-H", "Accept: application/vnd.github+json"]
    if body is not None:
        tmp = OUT / "_body.json"
        tmp.write_bytes(body.encode("utf-8"))
        args += ["-H", "Content-Type: application/json", "--data-binary", f"@{tmp}"]
    if data_file is not None:
        args += ["-H", "Content-Type: application/octet-stream", "--data-binary", f"@{data_file}"]
    args.append(url)
    out = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=timeout).stdout
    out, _, code = out.rpartition("__HTTP__")
    return int(code), out


def replace_first(path, pattern, repl):
    text = path.read_text(encoding="utf-8-sig")
    new = re.sub(pattern, repl, text, count=1)
    if new == text:
        raise RuntimeError(f"паттерн не найден в {path}: {pattern}")
    path.write_text(new, encoding="utf-8-sig")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    version = sys.argv[1]
    if not re.fullmatch(r"[\w.-]+", version):
        print("Некорректная версия:", version)
        sys.exit(1)
    tag = f"v{version}"
    notes_file = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else None
    notes = notes_file.read_text(encoding="utf-8-sig") if notes_file else f"Релиз {tag}"

    print(f"[1/6] Обновляю версию -> {version}")
    replace_first(SERVICE_BAT, r'set "LOCAL_VERSION=[^"]*"', f'set "LOCAL_VERSION={version}"')
    replace_first(MAIN_PY, r"Zapretik/[\w.-]+", f"Zapretik/{version}")

    print("[2/6] Коммит и push")
    run_retry(["git", "add", "-A"])
    run_retry(["git", "commit", "-m", f"Релиз {version}"], ok_codes=(0, 1))
    run_retry(["git", "push", "origin", "main"])

    print(f"[3/6] Тег {tag}")
    subprocess.run(["git", "tag", "-d", tag], capture_output=True)
    run_retry(["git", "tag", tag])
    run_retry(["git", "push", "origin", tag])

    print("[4/6] Сборка архива")
    rar = OUT / f"zaprerik-{tag}.rar"
    if rar.exists():
        rar.unlink()
    code, out = run([str(RAR), "a", "-ep1", "-r", "-m5",
                     "-x*\\.git", "-x*\\.git\\*", "-x*\\__pycache__", "-x*\\__pycache__\\*",
                     "-x*.log", str(rar), "*"])
    if code != 0:
        raise RuntimeError(f"RAR не собрал архив:\n{out}")

    token = git_credential()
    print("[5/6] Создаю GitHub-релиз")
    body = json.dumps({"tag_name": tag, "target_commitish": "main",
                       "name": f"Zaprerik {tag}", "body": notes,
                       "draft": False, "prerelease": False}, ensure_ascii=False)
    rel_id = None
    for _ in range(RETRIES):
        code, out = api("POST", f"https://api.github.com/repos/{REPO}/releases",
                        token, body=body)
        if code == 201:
            rel_id = json.loads(out)["id"]
            break
        time.sleep(10)
    if rel_id is None:
        raise RuntimeError("не удалось создать релиз")

    print("[6/6] Загружаю архив")
    for _ in range(RETRIES):
        code, out = api("POST",
                        f"https://uploads.github.com/repos/{REPO}/releases/{rel_id}/assets?name={rar.name}",
                        token, data_file=str(rar))
        if code == 201:
            break
        time.sleep(10)

    print("\nГотово:")
    print(f"  Релиз: https://github.com/{REPO}/releases/tag/{tag}")
    print(f"  Архив: https://github.com/{REPO}/releases/download/{tag}/{rar.name}")


if __name__ == "__main__":
    main()
