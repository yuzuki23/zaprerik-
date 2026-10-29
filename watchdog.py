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
import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    os.system("")
except Exception:
    pass
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
try:
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE_DIR = Path(r"C:\запрет")
CONFIG_FILE = BASE_DIR / "config.json"
WATCHDOG_LOG = BASE_DIR / "watchdog.log"
STATUS_FILE = BASE_DIR / "status.json"
PYTHON = Path(sys.executable)
WINWS = BASE_DIR / "bin" / "winws.exe"
HASH_FILE = BASE_DIR / "winws.sha256"
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW

sys.path.insert(0, str(BASE_DIR))

# Загрузка конфига
def load_config():
    defaults = {
        "version": "11.0.8",
        "watchdog": {
            "daily_restart_hour": 4,
            "liveness_timeout_sec": 360,
            "cycle_sleep_sec": 10,
            "memory_check_interval": 60,
            "max_log_lines": 2000,
            "keep_log_lines": 500,
        },
        "winws": {
            "restart_delay_sec": 45,
            "verification_attempts": 10,
            "verification_sleep_sec": 2,
        },
        "logs": {
            "rotate_by_date": True,
            "max_size_mb": 5,
            "backup_count": 3,
            "keep_days": 14,
        },
    }
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                user = json.load(f)
            if not isinstance(user, dict):
                raise ValueError("config.json — не JSON-объект")
            for k, v in user.items():
                if isinstance(v, dict) and k in defaults:
                    for sk, sv in v.items():
                        if sk in defaults[k] and type(defaults[k][sk]) == type(sv):
                            defaults[k][sk] = sv
                        elif sk in defaults[k]:
                            pass
                    defaults[k].update(v)
                else:
                    defaults[k] = v
        except json.JSONDecodeError as e:
            print(f"[WARN] config.json повреждён ({e}) — используются настройки по умолчанию")
        except Exception as e:
            print(f"[WARN] Ошибка чтения config.json: {e} — используются настройки по умолчанию")
    return defaults

CFG = load_config()

# Валидация типов и диапазонов числовых значений
EXPECTED_TYPES = {
    ("watchdog", "daily_restart_hour"): int,
    ("watchdog", "liveness_timeout_sec"): int,
    ("watchdog", "cycle_sleep_sec"): (int, float),
    ("watchdog", "memory_check_interval"): int,
    ("watchdog", "max_log_lines"): int,
    ("watchdog", "keep_log_lines"): int,
    ("winws", "restart_delay_sec"): (int, float),
    ("winws", "verification_attempts"): int,
    ("winws", "verification_sleep_sec"): (int, float),
    ("logs", "rotate_by_date"): bool,
    ("logs", "max_size_mb"): (int, float),
    ("logs", "backup_count"): int,
    ("logs", "keep_days"): int,
}
RANGES = {
    ("watchdog", "daily_restart_hour"): (0, 23),
    ("watchdog", "liveness_timeout_sec"): (30, 3600),
    ("watchdog", "cycle_sleep_sec"): (1, 300),
    ("watchdog", "memory_check_interval"): (10, 600),
    ("watchdog", "max_log_lines"): (100, 50000),
    ("watchdog", "keep_log_lines"): (50, 5000),
    ("winws", "restart_delay_sec"): (5, 300),
    ("winws", "verification_attempts"): (1, 100),
    ("winws", "verification_sleep_sec"): (1, 30),
    ("logs", "max_size_mb"): (1, 100),
    ("logs", "backup_count"): (0, 20),
    ("logs", "keep_days"): (1, 365),
}
for (section, key), expected in EXPECTED_TYPES.items():
    val = CFG.get(section, {}).get(key)
    if val is not None and not isinstance(val, expected):
        default_val = CFG.get(section, {}).get(key)
        print(f"[WARN] config.json {section}.{key}={val!r} ({type(val).__name__}) — ожидался {expected} — сброшено")
        CFG[section].pop(key, None)
for (section, key), (lo, hi) in RANGES.items():
    val = CFG.get(section, {}).get(key)
    if isinstance(val, (int, float)):
        if val < lo or val > hi:
            print(f"[WARN] config.json {section}.{key}={val} вне диапазона [{lo}..{hi}] — сброшено")
            CFG[section][key] = RANGES[(section, key)][0] if isinstance(val, int) else float(RANGES[(section, key)][0])

# Валидация формата версии X.Y.Z
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
if not isinstance(CFG.get("version"), str) or not _VERSION_RE.fullmatch(str(CFG.get("version"))):
    print(f"[WARN] config.json version={CFG.get('version')!r} — ожидался формат X.Y.Z — сброшено на 12.0.2")
    CFG["version"] = "12.0.2"

# Конфиг -> переменные
DAILY_RESTART_HOUR = CFG["watchdog"]["daily_restart_hour"]
LIVENESS_TIMEOUT = CFG["watchdog"]["liveness_timeout_sec"]
CYCLE_SLEEP = CFG["watchdog"]["cycle_sleep_sec"]
MEMORY_CHECK_INTERVAL = CFG["watchdog"]["memory_check_interval"]
MAX_LOG_LINES = CFG["watchdog"]["max_log_lines"]
KEEP_LOG_LINES = CFG["watchdog"]["keep_log_lines"]
RESTART_DELAY = CFG["winws"]["restart_delay_sec"]
VERIFY_ATTEMPTS = CFG["winws"]["verification_attempts"]
VERIFY_SLEEP = CFG["winws"]["verification_sleep_sec"]
ROTATE_BY_DATE = CFG["logs"]["rotate_by_date"]

# Самоперезапуск сторожа при изменении его собственного кода.
# Следим за СОДЕРЖИМЫМ (sha256), а не за mtime: антивирус или копирование
# могут менять время файла без изменения кода — это вызывало лишние
# самоперезапуски сторожа (и потерю утренних слотов будильника).
WATCHDOG_SELF = BASE_DIR / "watchdog.py"


def _self_hash():
    try:
        return hashlib.sha256(WATCHDOG_SELF.read_bytes()).hexdigest()
    except Exception:
        return None


WATCHDOG_SELF_HASH = _self_hash()

# Debounce самоперезапуска: если код изменился, ждём 5 циклов (50 сек) перед
# перезапуском — чтобы антивирус/сохранение не вызвали серию перезапусков.
RESTART_COOLDOWN_CYCLES = 5
restart_cooldown_remaining = 0

# Процессы под надзором: имя -> (скрипт, аргументы, частота перезапуска при сбое)
WATCHED = [
    {"name": "care",     "script": "care.py",     "args": []},
    {"name": "monitor",  "script": "monitor.py",  "args": []},
]

# Heartbeat-живость моника
MONITOR_LOG = BASE_DIR / "discord_monitor.log"

# Singleton: не даём запуститься второму экземпляру watchdog.
# Единый фиксированный путь в BASE_DIR (НЕ в TEMP!): процессы имеют разное
# окружение (сторож из сессии, keeper из Планировщика) и разные TEMP —
# из-за этого keeper не видел живой сторож и не мог его поднять.
LOCK_FILE = BASE_DIR / "zapretik_watchdog.lock"

# Глобальное состояние winws (вынесено до main)
entry_up = {"last_down": None}
winws_state = {"pid": None, "since": None}
daily_restart_done_day = None
planned_restart = set()
strategy_state = {"name": None}


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


def heartbeat_lock():
    """Обновляет lock-файл каждый цикл — heartbeat для night_check.py."""
    try:
        LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass



def is_admin():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def rotate(path: Path, max_size=None, keep=None):
    """Если лог разросся — сдвигает копии (.1, .2, ...) и начинает новый.

    max_size/keep по умолчанию берутся из config.json (logs.max_size_mb / logs.backup_count)."""
    if max_size is None:
        max_size = int(CFG["logs"]["max_size_mb"]) * 1024 * 1024
    if keep is None:
        keep = CFG["logs"]["backup_count"]
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


def cleanup_old_logs(keep_days=None):
    """Автоочистка старых логов: удаляет повёрнутые копии (*.log.*), старше keep_days.

    Основные .log не трогаем — только бэкапы .1/.2/.3 в BASE_DIR."""
    if keep_days is None:
        keep_days = CFG["logs"]["keep_days"]
    cutoff = time.time() - keep_days * 86400
    try:
        for p in BASE_DIR.glob("*.log.*"):
            if p.is_file() and p.stat().st_mtime < cutoff:
                p.unlink()
                log(f"Автоочистка логов: удалён устаревший бэкап {p.name}")
    except Exception:
        pass


def active_strategy():
    """Имя активной стратегии обхода — файла .bat, указанного в параметре службы zapret."""
    try:
        r = subprocess.run(
            ["reg", "query", r"HKLM\System\CurrentControlSet\Services\zapret", "/v", "zapret-discord-youtube"],
            capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW,
        )
        for line in r.stdout.splitlines():
            line = line.strip()
            if "zapret-discord-youtube" in line.lower():
                parts = line.split(None, 2)  # имя, тип, значение
                if len(parts) == 3:
                    data = parts[2].strip()
                elif parts:
                    data = parts[-1].strip()
                else:
                    continue
                base = os.path.basename(data)
                if base.lower().endswith(".bat"):
                    return base
                if data:
                    return data
    except Exception:
        pass
    return None


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    with WATCHDOG_LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def _atomic_write_json(path, data):
    """Атомарная запись JSON: временный файл + os.replace.

    open(..., "w") сначала обнуляет файл и только потом пишет данные —
    если процесс убит в этот момент, файл остаётся пустым (баг 11.0.6:
    config.json обнулился при смене стратегии). os.replace атомарен на
    Windows: файл заменяется целиком, читатель всегда видит либо старую,
    либо новую версию.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def write_status(status, details=None):
    """Записывает JSON-статус в status.json для внешних программ."""
    data = {
        "version": CFG.get("version", "12.0.2"),
        "timestamp": datetime.now().isoformat(),
        "status": status,
    }
    if details:
        data.update(details)
    try:
        _atomic_write_json(STATUS_FILE, data)
    except Exception:
        pass


def update_strategy_in_config(name):
    """Сохраняет активную стратегию в config.json (поле strategy).

    Единый источник активной стратегии: reinstall_service.py читает его,
    чтобы при падении winws восстанавливалась именно активная стратегия,
    а не general.bat по умолчанию.
    """
    if not name:
        return
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            cfg = json.load(f)
        if cfg.get("strategy") == name:
            return
        cfg["strategy"] = name
        _atomic_write_json(CONFIG_FILE, cfg)
        log(f"Активная стратегия сохранена в config.json: {name}")
    except Exception as e:
        log(f"ОШИБКА сохранения стратегии в config.json: {e}")


def start_proc(entry):
    """Запускает дочерний процесс и возвращает Popen.

    Скрипт передаётся абсолютным путём (BASE_DIR / script), чтобы перезапуск
    не зависел от cwd с кириллицей (Python сам резолвит путь через CreateProcessW).

    stdout перенаправляется в ФАЙЛ <name>_out.log, а не в pipe: pipe при живом
    процессе никто не читает (collect_output работает только после смерти) —
    его буфер переполнялся, print() моника упирался в полный pipe и блокировался
    навсегда. Так рождалось зависание «МОНИК ЗАВИС: живой, но молчит» (23.10 —
    6 мин тишины, завис на print после write_status).
    """
    script = BASE_DIR / entry["script"]
    cmd = [str(PYTHON), str(script)] + entry["args"]
    out_path = BASE_DIR / f"{entry['name']}_out.log"
    try:
        out_f = open(out_path, "wb")  # каждая инкарнация начинает вывод заново
    except OSError as exc:
        log(f"Не смогла открыть {out_path.name} для вывода {entry['name']}: {exc} — stdout в DEVNULL")
        out_f = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(BASE_DIR),
            creationflags=NO_WINDOW,
            stdout=out_f if out_f is not None else subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},  # вывод сразу в файл, без буфера Python
        )
        log(f"Старт {entry['name']} (PID={proc.pid}): {script}")
        return proc
    except OSError as exc:
        log(f"ОШИББКА запуска {entry['name']}: {exc}")
        return None
    finally:
        if out_f is not None:
            out_f.close()  # дескриптор уже продублирован в дочерний процесс


def collect_output(entry):
    """После смерти процесса — хвост его вывода (из <name>_out.log) в лог сторожа.

    Вывод идёт сразу в файл (см. start_proc), поэтому здесь просто читаем
    накопившееся — pipe больше нет, живой процесс ничем не блокируется.
    """
    proc = entry.get("proc")
    if proc is None:
        return
    if proc.poll() is None:
        return  # жив — не трогаем
    try:
        text = (BASE_DIR / f"{entry['name']}_out.log").read_text(
            encoding="utf-8", errors="replace").strip()
    except Exception:
        return
    if text:
        log(f"Вывод {entry['name']} (до падения, хвост):\n{text[-2000:]}")


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
    """Время последней записи моника (лог, heartbeat или файл статуса). None, если файлов нет."""
    best = None
    # Heartbeat — приоритетнее лога: если монитор застрял внутри цикла,
    # лог не обновляется, но heartbeat показывает, что процесс жив.
    # Читаем СОДЕРЖИМОЕ файла (timestamp), а не st_mtime — надёжнее.
    # Поддерживаем два формата: ISO с T и простой "YYYY-MM-DD HH:MM:SS"
    hb = BASE_DIR / "monitor_heartbeat.txt"
    if hb.exists():
        try:
            ts_str = hb.read_text(encoding="utf-8").strip()
            if ts_str:
                # Пробуем оба формата
                for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                    try:
                        hb_time = datetime.strptime(ts_str, fmt)
                        hb_ts = hb_time.timestamp()
                        if best is None or hb_ts > best:
                            best = hb_ts
                        break  # если формат подошёл — выходим
                    except ValueError:
                        continue  # пробуем следующий формат
        except Exception:
            pass
    for p in (MONITOR_LOG, BASE_DIR / "discord_status.txt"):
        try:
            if p.exists():
                m = p.stat().st_mtime
                if best is None or m > best:
                    best = m
        except Exception:
            pass
    return best


def monitor_silence_diagnosis():
    """Что моник успел сделать до того, как замолчал (для отладки зависаний).

    Возвращает строку с временем последней активности и последней строкой лога —
    чтобы понять, где моник «застрял» (на какой проверке/эндпоинте).
    """
    try:
        last = monitor_last_activity()
        if last is None:
            return "файлов активности не найдено"
        stamp = datetime.fromtimestamp(last).strftime("%Y-%m-%d %H:%M:%S")
        tail = ""
        try:
            with MONITOR_LOG.open("r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            if lines:
                tail = lines[-1].strip()[-220:]
        except Exception:
            pass
        return f"последняя активность {stamp}, последняя строка лога: {tail!r}"
    except Exception as exc:
        return f"ошибка диагностики: {exc}"


def _start_winws_process():
    """Запускает winws.exe напрямую как процесс (без службы и прав админа).

    Используется когда нет прав админа — сторож не может ни sc start, ни
    пересоздать службу. Собирает аргументы из активной стратегии (как
    reinstall_service.build_binpath) и запускает winws процессом. Возвращает
    True, если winws реально появился в тасклисте."""
    try:
        import reinstall_service as rs
        name, binpath = rs.build_binpath()
        wins = shlex.split(binpath)
    except Exception as exc:
        log(f"НЕ удалось собрать команду winws из стратегии: {exc}")
        return False
    log(f"winws процессом (стратегия {name}): права админа не нужны")
    try:
        subprocess.Popen(wins, cwd=str(WINWS.parent), creationflags=NO_WINDOW)
    except Exception as exc:
        log(f"ОШИБКА запуска winws процессом: {exc}")
        return False
    for _ in range(max(3, VERIFY_ATTEMPTS)):
        if winws_up():
            return True
        time.sleep(VERIFY_SLEEP)
    return winws_up()


def start_zapret():
    """Поднимает службу zapret (winws). Если служба отсутствует — пересоздаёт её.
    Возвращает True, если winws реально поднялся (проверено опросом STATE/RUNNING).

    Без прав админа (наблюдательный режим) службу/sc не трогаем — запускаем
    winws.exe напрямую процессом из активной стратегии."""
    if not is_admin():
        return _start_winws_process()
    try:
        if not service_exists():
            log("Служба zapret отсутствует — пересоздаю через reinstall_service.py")
            try:
                subprocess.run([str(PYTHON), str(BASE_DIR / "reinstall_service.py")],
                               capture_output=True, text=True, timeout=120,
                               creationflags=NO_WINDOW)
            except Exception as e:
                log(f"ОШИБКА пересоздания службы: {e}")
        r = subprocess.run(["sc", "start", "zapret"], capture_output=True, text=True,
                           timeout=30, creationflags=NO_WINDOW)
        log("Поднятие winws: " + ("sc start" if r.returncode == 0 else f"sc start -> {r.returncode}"))
    except Exception as exc:
        log(f"ОШИБКА поднятия winws: {exc}")
        return False
    # Верификация: winws реально RUNNING? sc start может вернуть успех, но служба
    # ещё в START_PENDING или упала сразу — опрашиваем STATE до ~20 секунд.
    for _ in range(VERIFY_ATTEMPTS):
        if winws_up():
            return True
        time.sleep(VERIFY_SLEEP)
    # Фолбэк: net start (иногда sc start не поднимает из-за гонки WinDivert/драйвера)
    log("winws не поднялся через sc start — пробуем net start zapret")
    try:
        subprocess.run(["net", "start", "zapret"], capture_output=True, text=True,
                       timeout=30, creationflags=NO_WINDOW)
    except Exception as exc:
        log(f"ОШИБКА net start: {exc}")
    for _ in range(VERIFY_ATTEMPTS):
        if winws_up():
            return True
        time.sleep(VERIFY_SLEEP)
    log("winws НЕ поднялся после всех попыток (вероятен краш winws.exe)")
    return False


# Ежедневный перезапуск сторожа в заданный час, чтобы правки кода
# (watchdog.py / monitor.py / care.py) подхватывались без ручного .bat.
# Службу zapret не трогаем — Discord не дёргаем понапрасну.
daily_restart_done_day = None
planned_restart = set()


def self_restart():
    """Перезапускает сам сторож с новым кодом — через помощника watchdog_relaunch.py.

    Всегда используем watchdog_relaunch.py (schetasks /End → /Run), потому что
    прямой Popen наследует токен родителя: если текущий сторож запущен без прав
    админа (задача ZapretikWatchdog), дочерний тоже теряет права и не может
    поднять winws (WinError 740 «запрашивается повышенный режим»). Помощник
    делает schtasks /End → /Run — новый сторож стартует уже с правами самой
    задачи (RunLevel), а не с potentially заниженным токеном родительского pythonw.
    """
    log("Самоперезапуск сторожа — подхват нового кода")
    for entry in WATCHED:
        proc = entry.get("proc")
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
    # Всегда через помощника — он гарантирует запуск через schtasks,
    # который подхватит права задачи (а не унаследованный токен)
    try:
        subprocess.Popen(
            [str(PYTHON), str(BASE_DIR / "watchdog_relaunch.py"), str(os.getpid())],
            cwd=str(BASE_DIR),
            creationflags=NO_WINDOW,
        )
    except Exception as exc:
        log(f"ОШИБКА запуска помощника самоперезапуска: {exc} — пробую прямой Popen")
        try:
            subprocess.Popen(
                [str(PYTHON), str(WATCHDOG_SELF)],
                cwd=str(BASE_DIR),
                creationflags=NO_WINDOW,
                env={**os.environ, "ZAPRETIK_REPLACING": "1"},
            )
        except Exception as exc2:
            log(f"ОШИБКА прямого самоперезапуска: {exc2}")
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
    if not is_admin():
        # Задача ZapretikWatchdog при незавышенной сессии даёт не-админский
        # токен (InteractiveToken + HighestAvailable), поэтому попытка
        # перезапуска через планировщик зацикливается. Не выходим: работаем
        # в «наблюдательном» режиме — статусы, логи, восстановление winws
        # процесса. Служба zapret живёт сама, пока это возможно.
        log("Сторож запущен БЕЗ прав админа — работаю в наблюдательном режиме (службу не пересоздаю)")
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
    cleanup_old_logs()
    log(f"Watchdog запущен (v{CFG.get('version', '12.0.2')}). Под надзором: " + ", ".join(e["name"] for e in WATCHED) + " + zapret/winws")
    write_status("starting")
    kill_stray_scripts()
    check_winws_hash()
    for entry in WATCHED:
        entry["proc"] = start_proc(entry)
        entry["down_since"] = None
        time.sleep(1)

    procs = {e["name"]: e["proc"].pid if e.get("proc") and e["proc"].poll() is None else None for e in WATCHED}
    procs["winws"] = winws_pid()
    write_status("running", {"processes": procs})
    # winws (служба) может подниматься с задержкой — повторный опрос, чтобы
    # в свежем status.json стоял реальный PID, а не первый None.
    for _ in range(3):
        if procs["winws"] is not None:
            break
        time.sleep(3)
        procs["winws"] = winws_pid()
        if procs["winws"] is not None:
            write_status("running", {"processes": procs})
    cycle = 0

    while True:
        # сам перезапуск, если изменился собственный код сторожа (по хэшу)
        # Debounce: ждём RESTART_COOLDOWN_CYCLES циклов перед перезапуском,
        # чтобы антивирус/сохранение не вызвали серию перезапусков
        try:
            if restart_cooldown_remaining > 0:
                restart_cooldown_remaining -= 1
            else:
                cur_hash = _self_hash()
                if cur_hash is not None and cur_hash != WATCHDOG_SELF_HASH:
                    log("Обнаружено изменение watchdog.py — самоперезапуск для подхвата нового кода")
                    restart_cooldown_remaining = RESTART_COOLDOWN_CYCLES
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
                        diag = monitor_silence_diagnosis()
                        log(f"МОНИК ЗАВИС (молчит {int(idle // 60)} мин при живом процессе; {diag}) — принудительный перезапуск")
                        # Своё убийство — не падение: помечаем как плановый рестарт,
                        # иначе следующий цикл напишет ложное «ПАДЕНИЕ monitor».
                        planned_restart.add(entry["name"])
                        try:
                            proc.terminate()
                        except Exception:
                            pass

        # Обновляем status.json после обработки ВСЕХ воркеров — свежий PID
        # каждого перезапущенного процесса, не ждём MEMORY_CHECK_INTERVAL.
        try:
            procs = {e["name"]: e["proc"].pid if e.get("proc") and e["proc"].poll() is None else None for e in WATCHED}
            procs["winws"] = winws_pid()
            write_status("running", {"processes": procs, "cycle": cycle, "strategy": strategy_state.get("name")})
        except Exception:
            pass

        # Проверка: если все 3 процесса умерли одновременно — логируем причину
        all_dead = all(
            e.get("proc") is not None and e["proc"].poll() is not None
            for e in WATCHED
        )
        if all_dead:
            log("КРИТИЧНО: все процессы (care, monitor, watchdog) упали одновременно!")
            log("Возможные причины: нехватка памяти, crash Python, убийство антивирусом")
            try:
                import psutil
                mem = psutil.virtual_memory()
                log(f"Память: {mem.percent}% занято ({mem.available // (1024*1024)} Мб свободно)")
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
                    log(f"winws НЕ поднялся — повторная попытка через {RESTART_DELAY}с")
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
        time.sleep(CYCLE_SLEEP)
        cycle += 1
        # Heartbeat lock — чтобы night_check.py видел, что сторож жив
        heartbeat_lock()
        # Отслеживание активной стратегии обхода: при смене — уведомление в лог
        strat = active_strategy()
        if strat and strat != strategy_state.get("name"):
            if strategy_state.get("name") is not None:
                log(f"СМЕНА СТРАТЕГИИ: {strategy_state['name']} -> {strat}")
            else:
                log(f"Активная стратегия обхода: {strat}")
            update_strategy_in_config(strat)
            strategy_state["name"] = strat
        # Каждые N циклов — логируем память winws и обновляем status.json
        if cycle % MEMORY_CHECK_INTERVAL == 0:
            log_winws_memory()
            rotate_by_lines(WATCHDOG_LOG)
            cleanup_old_logs()
            procs = {e["name"]: e["proc"].pid if e.get("proc") and e["proc"].poll() is None else None for e in WATCHED}
            procs["winws"] = winws_pid()
            write_status("running", {"processes": procs, "cycle": cycle, "strategy": strategy_state.get("name")})


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        try:
            log("КРИТИЧЕСКИЙ СБОЙ СТОРОЖА:\n" + traceback.format_exc())
        except Exception:
            pass
        raise