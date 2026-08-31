# -*- coding: utf-8 -*-
"""Watchdog для фоновых процессов Zapretik.

Следит за care.py (будильник), monitor.py (мониторинг Discord) и службой zapret
(winws.exe). Если процесс упал — перезапускает его и пишет причину падения в watchdog.log.
Также проверяет целостность winws.exe (SHA256 против первого запуска) и ротирует лог.

Запуск:
    python watchdog.py

По умолчанию процессы запускаются с CREATE_NO_WINDOW и работают фоном.
"""
import hashlib
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

os.system("")

BASE_DIR = Path(r"C:\запрет")
WATCHDOG_LOG = BASE_DIR / "watchdog.log"
PYTHON = Path(sys.executable)
WINWS = BASE_DIR / "bin" / "winws.exe"
HASH_FILE = BASE_DIR / "winws.sha256"
MAX_LOG_SIZE = 2 * 1024 * 1024  # 2 МБ
KEEP_LOGS = 3

# Самоперезапуск сторожа при изменении его собственного кода.
WATCHDOG_SELF = BASE_DIR / "watchdog.py"
WATCHDOG_SELF_MTIME = WATCHDOG_SELF.stat().st_mtime

# Процессы под надзором: имя -> (скрипт, аргументы, частота перезапуска при сбое)
# monitor.py без аргументов = интервал 120 секунд (по умолчанию)
WATCHED = [
    {"name": "care",     "script": "care.py",     "args": []},
    {"name": "monitor",  "script": "monitor.py",  "args": []},
]

NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW

# Heartbeat-живость моника: если процесс жив, но не пишет в лог/статус дольше
# LIVENESS_TIMEOUT секунд — считаем его зависшим и принудительно перезапускаем.
# Иначе сторож не видит Hang (видит только падение, через proc.poll()).
MONITOR_LOG = BASE_DIR / "discord_monitor.log"
LIVENESS_TIMEOUT = 360  # 6 минут

# Singleton: не даём запуститься второму экземпляру watchdog
# (чтобы при запуске через Планировщик заданий не задублировались care/monitor).
LOCK_FILE = Path(os.environ.get("TEMP", str(BASE_DIR))) / "zapretik_watchdog.lock"


def acquire_lock():
    """Возвращает True, если мы — единственный запущенный watchdog.

    При запуске с env ZAPRETIK_REPLACING=1 (самоперезапуск) дожидается выхода
    старого экземпляра, чтобы аккуратно передать управление без дублей.
    """
    replacing = os.environ.get("ZAPRETIK_REPLACING") == "1"
    attempts = 40 if replacing else 1
    for _ in range(attempts):
        try:
            if LOCK_FILE.exists():
                pid = LOCK_FILE.read_text(encoding="utf-8").strip()
                if pid.isdigit():
                    r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                                       capture_output=True, text=True, timeout=10,
                                       creationflags=NO_WINDOW)
                    if str(pid) in r.stdout:
                        if replacing:
                            time.sleep(0.5)
                            continue
                        return False  # старый экземпляр ещё жив
            LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
            return True
        except Exception:
            return True
    return False


def release_lock():
    try:
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()
    except Exception:
        pass



def is_admin():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def rotate(path: Path, max_size=MAX_LOG_SIZE, keep=KEEP_LOGS):
    """Если лог разросся — сдвигает копии (.1, .2, ...) и начинает новый."""
    if not path.exists() or path.stat().st_size < max_size:
        return
    for i in range(keep - 1, 0, -1):
        src = path.with_name(f"{path.name}.{i}")
        dst = path.with_name(f"{path.name}.{i + 1}")
        if src.exists():
            dst.write_bytes(src.read_bytes())
            src.unlink()
    path.with_name(f"{path.name}.1").write_bytes(path.read_bytes())
    path.write_text("", encoding="utf-8")


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with WATCHDOG_LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def start_proc(entry):
    """Запускает дочерний процесс и возвращает Popen.

    Скрипт передаётся абсолютным путём (BASE_DIR / script), чтобы перезапуск
    не зависел от cwd с кириллицей (Python сам резолвит путь через CreateProcessW).
    """
    script = BASE_DIR / entry["script"]
    cmd = [str(PYTHON), str(script)] + entry["args"]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            creationflags=NO_WINDOW,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        log(f"Старт {entry['name']} (PID={proc.pid}): {script}")
        return proc
    except OSError as exc:
        log(f"ОШИББКА запуска {entry['name']}: {exc}")
        return None


def collect_output(entry):
    """Вычитывает накопившийся вывод процесса (если процесс уже умер)."""
    proc = entry.get("proc")
    if proc is None or proc.stdout is None:
        return
    if proc.poll() is None:
        return  # жив — не трогаем
    try:
        out = proc.stdout.read()
    except Exception:
        return
    if out:
        text = out.decode("utf-8", errors="replace").strip()
        if text:
            log(f"Вывод {entry['name']} (до падения):\n{text[:2000]}")


def winws_up():
    """winws работает как служба zapret или как процесс?"""
    try:
        r = subprocess.run(["sc", "query", "zapret"], capture_output=True, text=True,
                           timeout=15, creationflags=NO_WINDOW)
        if "RUNNING" in r.stdout:
            return True
    except Exception:
        pass
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq winws.exe"], capture_output=True,
                           text=True, timeout=15, creationflags=NO_WINDOW)
        return "winws.exe" in r.stdout
    except Exception:
        return True  # не можем проверить — не трогаем


def winws_pid():
    """Текущий PID процесса winws.exe (или None, если процесса нет)."""
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq winws.exe", "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
        for line in r.stdout.splitlines():
            parts = [p.strip().strip('"') for p in line.split(",")]
            if parts and parts[0].lower() == "winws.exe" and len(parts) > 1 and parts[1].isdigit():
                return int(parts[1])
    except Exception:
        pass
    return None


def recent_winws_events(mins=6):
    """Причины остановки winws из журналов Windows за последние {mins} минут.

    Собирает события Service Control Manager (System), касающиеся службы zapret,
    и события сбоев/ошибок приложений (Application), упоминающие winws.
    Возвращает строку 'время [журнал] текст' или "", если ничего не найдено."""
    try:
        since = datetime.fromtimestamp(time.time() - mins * 60).strftime("%Y-%m-%d %H:%M:%S")
        script = (
            "$cut=Get-Date '{since}';"
            "$ev=@();"
            "$ev+=@(Get-WinEvent -FilterHashtable @{{LogName='System';StartTime=$cut}} -ErrorAction SilentlyContinue"
            " | Where-Object {{ $_.ProviderName -eq 'Service Control Manager' -and $_.Message -match 'zapret' }});"
            "$ev+=@(Get-WinEvent -FilterHashtable @{{LogName='Application';StartTime=$cut}} -ErrorAction SilentlyContinue"
            " | Where-Object {{ $_.Message -match 'winws' }});"
            "if($ev.Count -gt 0){{$ev|Sort-Object TimeCreated|ForEach-Object{{"
            "$_.TimeCreated.ToString('HH:mm:ss')+' ['+$_.ProviderName+'] '+"
            "$_.Message.Substring(0,[Math]::Min(160,$_.Message.Length)).Replace(\"`n\",' / ')}}}}"
        ).format(since=since)
        r = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                           capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
        lines = [l.strip() for l in r.stdout.splitlines() if l.strip()]
        return "\n".join(lines) if lines else ""
    except Exception:
        return ""


def service_exists():
    """True, если служба zapret зарегистрирована в системе."""
    try:
        r = subprocess.run(["sc", "query", "zapret"], capture_output=True, text=True,
                           timeout=15, creationflags=NO_WINDOW)
        # returncode 0 + строка STATE => служба есть; 1060 => отсутствует
        return r.returncode == 0 and "STATE" in r.stdout
    except Exception:
        return True  # не удалось проверить — считаем, что служба есть (не трогаем)


def monitor_last_activity():
    """Время последней записи моника (лог или файл статуса). None, если файлов нет."""
    best = None
    for p in (MONITOR_LOG, BASE_DIR / "discord_status.txt"):
        try:
            if p.exists():
                m = p.stat().st_mtime
                if best is None or m > best:
                    best = m
        except Exception:
            pass
    return best


def start_zapret():
    """Поднимает службу zapret (winws). Если служба отсутствует — пересоздаёт её.
    Возвращает True, если winws реально поднялся (проверено опросом STATE/RUNNING)."""
    try:
        if not service_exists():
            log("Служба zapret отсутствует — пересоздаю через reinstall_service.py")
            try:
                subprocess.run([str(PYTHON), str(BASE_DIR / "reinstall_service.py")],
                               capture_output=True, text=True, timeout=120,
                               creationflags=NO_WINDOW)
            except Exception as e:
                log(f"ОШИБКА пересоздания службы: {e}")
        if is_admin():
            r = subprocess.run(["sc", "start", "zapret"], capture_output=True, text=True,
                               timeout=30, creationflags=NO_WINDOW)
            msg = "sc start" if r.returncode == 0 else f"sc start -> {r.returncode}"
        else:
            subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden",
                              "-Command", "Start-Process 'sc.exe' -ArgumentList 'start','zapret' -Verb RunAs"],
                             creationflags=NO_WINDOW)
            msg = "UAC sc start"
        log(f"Поднятие winws: {msg}")
    except Exception as exc:
        log(f"ОШИБКА поднятия winws: {exc}")
        return False
    # Верификация: winws реально RUNNING? sc start может вернуть успех, но служба
    # ещё в START_PENDING или упала сразу — опрашиваем STATE до ~20 секунд.
    for _ in range(10):
        if winws_up():
            return True
        time.sleep(2)
    # Фолбэк: net start (иногда sc start не поднимает из-за гонки WinDivert/драйвера)
    log("winws не поднялся через sc start — пробуем net start zapret")
    try:
        subprocess.run(["net", "start", "zapret"], capture_output=True, text=True,
                       timeout=30, creationflags=NO_WINDOW)
    except Exception as exc:
        log(f"ОШИБКА net start: {exc}")
    for _ in range(10):
        if winws_up():
            return True
        time.sleep(2)
    log("winws НЕ поднялся после всех попыток (вероятен краш winws.exe)")
    return False


# Ежедневный перезапуск сторожа в заданный час, чтобы правки кода
# (watchdog.py / monitor.py / care.py) подхватывались без ручного .bat.
# Службу zapret не трогаем — Discord не дёргаем понапрасну.
DAILY_RESTART_HOUR = 4
daily_restart_done_day = None
planned_restart = set()


def self_restart():
    """Перезапускает сам сторож с новым кодом.

    Останавливаем подопечных, запускаем свежий python watchdog.py (с флагом
    замены ZAPRETIK_REPLACING) и выходим — новый экземпляр берёт lock и
    поднимает все скрипты уже с обновлённым кодом.
    """
    log("Самоперезапуск сторожа — подхват нового кода")
    for entry in WATCHED:
        proc = entry.get("proc")
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
    try:
        subprocess.Popen(
            [str(PYTHON), str(WATCHDOG_SELF)],
            cwd=str(BASE_DIR),
            creationflags=NO_WINDOW,
            env={**os.environ, "ZAPRETIK_REPLACING": "1"},
        )
    except Exception as exc:
        log(f"ОШИБКА самоперезапуска сторожа: {exc}")
    release_lock()
    sys.exit(0)


def maybe_daily_restart(entries):
    """Раз в сутки (в DAILY_RESTART_HOUR) полностью перезапускает сторожа.

    Новый экземпляр сам поднимет care/monitor уже с обновлённым кодом.
    Запуск службы zapret не затрагивается.
    """
    global daily_restart_done_day
    now = datetime.now()
    day = now.strftime("%Y-%m-%d")
    if now.hour == DAILY_RESTART_HOUR and daily_restart_done_day != day:
        daily_restart_done_day = day
        log("Ежедневный перезапуск сторожа в %02d:00 (подхват обновлений кода)" % DAILY_RESTART_HOUR)
        self_restart()


def check_winws_hash():
    """Сверяет SHA256 winws.exe с первым запуском. Если изменился — предупреждает."""
    if not WINWS.exists():
        log("winws.exe НЕ НАЙДЕН в bin/")
        return
    h = hashlib.sha256(WINWS.read_bytes()).hexdigest()
    if not HASH_FILE.exists():
        HASH_FILE.write_text(h, encoding="utf-8")
        log("Сохранён первый хэш winws.exe (эталон)")
        return
    known = HASH_FILE.read_text(encoding="utf-8").strip()
    if known != h:
        log("ВНИМАНИЕ: winws.exe ИЗМЕНИЛСЯ (антивирус/подмена). Эталон: " + known[:16] + "... сейчас: " + h[:16] + "...")


def log_winws_memory():
    """Логирует потребление памяти winws (RSS в МБ) для диагностики тихих падений."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='winws.exe'\" | "
             "ForEach-Object { [math]::Round($_.WorkingSetSize / 1MB, 1) }"],
            capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
        for line in r.stdout.splitlines():
            line = line.strip()
            if line and line.replace(".", "").isdigit():
                mb = float(line)
                log(f"winws память: RSS {mb} МБ")
                if mb > 400:
                    log(f"ВНИМАНИЕ: winws использует {mb} МБ — возможна утечка памяти")
                return
    except Exception:
        pass


def rotate_by_lines(path: Path, max_lines=2000, keep_lines=500):
    """Если лог превысил max_lines — оставляет только последние keep_lines."""
    if not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) > max_lines:
            trimmed = lines[-keep_lines:]
            path.write_text("".join(trimmed), encoding="utf-8")
            log(f"Ротация лога: {len(lines)} -> {len(trimmed)} строк")
    except Exception:
        pass


def main():
    if not acquire_lock():
        print("Watchdog уже запущен (lock-файл занят) — выход.", flush=True)
        sys.exit(0)
    try:
        _run()
    finally:
        release_lock()


def kill_stray_scripts():
    """Снимаем осиротевшие копии наших скриптов (care/monitor/watchdog),
    чтобы при перезапусках не плодились дубли. Себя и своих детей не трогаем."""
    ours = {os.getpid()}
    for e in WATCHED:
        p = e.get("proc")
        if p is not None:
            ours.add(p.pid)
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\" | "
             "ForEach-Object { ($_.ProcessId.ToString() + '|' + $_.CommandLine) }"],
            capture_output=True, text=True, timeout=25, creationflags=NO_WINDOW)
        out = r.stdout
    except Exception:
        return
    for line in out.splitlines():
        if "|" not in line:
            continue
        pid_s, cmd = line.split("|", 1)
        if not pid_s.strip().isdigit():
            continue
        pid = int(pid_s.strip())
        if pid in ours:
            continue
        if any(s in cmd for s in ("care.py", "monitor.py", "watchdog.py")):
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                               capture_output=True, text=True, timeout=10,
                               creationflags=NO_WINDOW)
                log(f"Снят осиротевший процесс {pid} ({cmd[:70]})")
            except Exception:
                pass


def _run():
    rotate(WATCHDOG_LOG)
    rotate_by_lines(WATCHDOG_LOG)
    log("Watchdog запущен. Под надзором: " + ", ".join(e["name"] for e in WATCHED) + " + zapret/winws")
    kill_stray_scripts()
    check_winws_hash()
    for entry in WATCHED:
        entry["proc"] = start_proc(entry)
        entry["down_since"] = None
        time.sleep(1)

    cycle = 0

    while True:
        # сам перезапуск, если изменился собственный код сторожа
        try:
            if WATCHDOG_SELF.stat().st_mtime != WATCHDOG_SELF_MTIME:
                self_restart()
        except Exception:
            pass
        maybe_daily_restart(WATCHED)
        for entry in WATCHED:
            proc = entry.get("proc")
            if proc is not None and proc.poll() is not None:
                collect_output(entry)
                code = proc.poll()
                if entry["name"] in planned_restart:
                    planned_restart.discard(entry["name"])
                    log(f"Плановый перезапуск {entry['name']} (код {code})")
                elif entry.get("down_since") is None:
                    entry["down_since"] = time.time()
                    log(f"ПАДЕНИЕ {entry['name']} (код {code}) — перезапускаю")
                else:
                    log(f"{entry['name']} всё ещё лежит (код {code}) — повторный запуск")
                entry["proc"] = start_proc(entry)
                continue
            if proc is not None and entry.get("down_since") is not None:
                log(f"{entry['name']} снова работает (PID={proc.pid})")
                entry["down_since"] = None

            # Heartbeat-живость моника: процесс жив, но не пишет в лог > LIVENESS_TIMEOUT.
            # Зависший (молчащий) моник сторож иначе не лечит — он видит только падение.
            if entry["name"] == "monitor" and proc is not None and proc.poll() is None:
                last = monitor_last_activity()
                if last is not None:
                    idle = time.time() - last
                    if idle > LIVENESS_TIMEOUT:
                        log(f"МОНИК ЗАВИС (молчит {int(idle // 60)} мин при живом процессе) — принудительный перезапуск")
                        try:
                            proc.terminate()
                        except Exception:
                            pass

        # Надзор за winws
        if not winws_up():
            # winws упал/остановлен. Прежде чем поднимать — выясняем ПОЧЕМУ:
            # собираем события SCM/ошибки приложений за последние ~6 минут
            # (код выхода службы, «перезапускается», сбои winws.exe и т.п.).
            now = time.time()
            last = entry_up.get("last_down")
            if last is None or now - last > 45:
                pid_before = winws_state.get("pid")
                since = winws_state.get("since")
                live = "?" if since is None else f"~{max(0, int((now - since) // 60))} мин"
                reason = recent_winws_events(6)
                if reason:
                    log(f"winws остановился (был PID {pid_before}, жил {live}). Причина из событий Windows:\n{reason}")
                else:
                    log(f"winws остановился (был PID {pid_before}, жил {live}) — событий об остановке не найдено")
                ok = start_zapret()
                if ok:
                    new_pid = winws_pid()
                    log(f"winws поднят (авто-восстановление, новый PID {new_pid})")
                else:
                    log("winws НЕ поднялся — повторная попытка через 45с")
                entry_up["last_down"] = now
                winws_state["pid"] = winws_pid()
                winws_state["since"] = time.time()
        else:
            # winws жив. Ловим «молчаливые» автоперезапуски без сбоя Discord:
            # смена PID процесса winws.exe (возможна из-за Recovery службы).
            pid = winws_pid()
            old = winws_state.get("pid")
            if pid is not None:
                if old is not None and old != pid:
                    since = winws_state.get("since")
                    live = "?" if since is None else f"~{max(0, int((time.time() - since) // 60))} мин (с момента последнего чека)"
                    log(f"winws ПЕРЕЗАПУЩЕН в фоне: PID {old} -> {pid} ({live})")
                winws_state["pid"] = pid
                winws_state["since"] = time.time()
            else:
                # процесса в тасклисте нет, хотя служба RUNNING — неопределённое
                # состояние, даём следующему циклу разобраться.
                winws_state["pid"] = None
                winws_state["since"] = None
        time.sleep(10)
        cycle += 1
        # Каждые ~10 минут (60 циклов * 10 сек) — логируем память winws
        if cycle % 60 == 0:
            log_winws_memory()
            rotate_by_lines(WATCHDOG_LOG)


entry_up = {"last_down": None}
winws_state = {"pid": None, "since": None}


if __name__ == "__main__":
    main()