"""Помощник самоперезапуска сторожа через задачу ZapretikWatchdog.

Зачем он нужен. Проверено 05.10.2026: `schtasks /Run` на УЖЕ выполняющейся
задаче отвечает кодом 0 и «currently running», но новый процесс не создаёт.
Текущий сторож при этом сам обычно запущен этой же задачей, поэтому /Run
всегда был холостым: старый код 30 секунд ждал lock, не дожидался и уходил на
запасной pythonw — задача как механизм самоперезапуска не работала.

Спасает порядок `schtasks /End` → `schtasks /Run` (как в AGENTS.md), но /End
убивает и текущий экземпляр — то есть и нас. Поэтому перезапуск поручается
отдельному процессу: он не входит в дерево задачи и переживает /End.

Имя файла намеренно НЕ содержит подстроки "watchdog.py" — иначе новый сторож
снимет помощника в kill_stray_scripts() (он ищет care.py/monitor.py/watchdog.py).

Запуск: pythonw.exe watchdog_relaunch.py <старый_PID_сторожа>
"""

import os
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
TASK = "ZapretikWatchdog"
LOCK_FILE = BASE_DIR / "zapretik_watchdog.lock"
WATCHDOG = BASE_DIR / "watchdog.py"
WATCHDOG_LOG = BASE_DIR / "watchdog.log"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def log(msg):
    try:
        with WATCHDOG_LOG.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} Помощник: {msg}\n")
    except Exception:
        pass


def run(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           creationflags=NO_WINDOW)
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as exc:
        return -1, repr(exc)


def pid_alive(pid):
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=15,
                             creationflags=NO_WINDOW).stdout or ""
        return str(pid) in out
    except Exception:
        return True


def lock_pid():
    try:
        if LOCK_FILE.exists():
            pid = LOCK_FILE.read_text(encoding="utf-8").strip()
            if pid.isdigit():
                return int(pid)
    except Exception:
        pass
    return None


def wait_new_watchdog(old_pid, seconds):
    for _ in range(seconds):
        time.sleep(1)
        pid = lock_pid()
        if pid and pid != old_pid and pid_alive(pid):
            return pid
    return None


def direct_start():
    log("запасной путь: запускаю сторож напрямую через pythonw")
    env = {**os.environ, "ZAPRETIK_REPLACING": "1"}
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")
    launch = pyw if pyw.exists() else exe
    subprocess.Popen([str(launch), str(WATCHDOG)], cwd=str(BASE_DIR),
                     creationflags=NO_WINDOW, env=env)


def main():
    old_pid = 0
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        old_pid = int(sys.argv[1])
    log(f"старт (старый сторож PID={old_pid or 'не указан'})")

    for _ in range(30):
        if not old_pid or not pid_alive(old_pid):
            break
        time.sleep(1)
    if old_pid and pid_alive(old_pid):
        log(f"старый сторож PID={old_pid} ещё жив — снимаю задачу через /End")
    else:
        log("старый сторож завершился штатно")

    code, out = run(["schtasks", "/End", "/TN", TASK])
    log(f"schtasks /End: код={code} {out[:150]}")
    time.sleep(3)

    code, out = run(["schtasks", "/Run", "/TN", TASK])
    log(f"schtasks /Run: код={code} {out[:150]}")
    if "currently running" in out.lower():
        log("задача всё ещё числится выполняемой — повторяю /End и /Run")
        time.sleep(4)
        code, out = run(["schtasks", "/End", "/TN", TASK])
        log(f"schtasks /End (повтор): код={code} {out[:150]}")
        time.sleep(3)
        code, out = run(["schtasks", "/Run", "/TN", TASK])
        log(f"schtasks /Run (повтор): код={code} {out[:150]}")

    pid = wait_new_watchdog(old_pid, 30)
    if pid:
        log(f"УСПЕХ: сторож поднят задачей ZapretikWatchdog (PID={pid})")
        return

    log("задача не подняла сторожа — беру запасной путь")
    direct_start()
    pid = wait_new_watchdog(old_pid, 25)
    if pid:
        log(f"УСПЕХ: сторож поднят напрямую через pythonw (PID={pid})")
        return
    log("ОШИБКА: не удалось поднять сторож ни через задачу, ни напрямую")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"НЕОЖИДАННАЯ ОШИБКА помощника: {exc!r}")
