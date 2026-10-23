# -*- coding: utf-8 -*-
"""Ночная проверка Zapretik: снимает сводку состояния после сна/за ночь.

Запускается по задаче Планировщика утром (и вручную). Пишёт отчёт в
night_check.log и короткую строку в events.log.

Что ищем (типичные ночные баги):
  - сторож умер ночью (появились новые «Сторож запущен» в events.log);
  - моник не писал OK долгое время (молчание после сна);
  - были сбои Discord (строки «СБОЯ» в discord_monitor.log);
  - пропала служба zapret или winws;
  - lock не обновляется (сторож завис, а не умер).
"""
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE = Path(r"C:\запрет")
OUT = BASE / "night_check.log"
EVENTS = BASE / "events.log"
MONITOR_LOG = BASE / "discord_monitor.log"
WATCHDOG_LOG = BASE / "watchdog.log"
STATUS = BASE / "status.json"
LOCK = BASE / "zapretik_watchdog.lock"
NO_WINDOW = 0x08000000
WINDOW_HOURS = 12


TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def tail_lines(path, hours, marker_from=None):
    """Строки лога за последние N часов.

    Дата ищется в любом месте строки: у моника строки начинаются с префикса
    («OK 2026-10-16 19:43:49 | …»), у сторожа и в events.log — с даты.
    """
    if not path.exists():
        return []
    cutoff = datetime.now() - timedelta(hours=hours)
    out = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        m = TS_RE.search(s)
        if not m:
            continue
        try:
            ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if ts >= cutoff:
            out.append(s)
    return out


def svc_state():
    try:
        r = subprocess.run(["sc.exe", "query", "zapret"], capture_output=True,
                           timeout=20, creationflags=NO_WINDOW)
        raw = r.stdout or b""
        # Вывод sc.exe — в OEM-кодировке консоли (cp866), а не UTF-8:
        for enc in ("cp866", "utf-8", "cp1251"):
            try:
                out = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            out = raw.decode("utf-8", errors="replace")
        # 10.0.6: ищем строку состояния БЕЗ учёта регистра — на русской Windows
        # sc.exe печатает «Состояние», а раньше искали «СОСТОЯНИЕ», не находили
        # и в отчёт падал весь многострочный блок вместо короткого «RUNNING».
        for line in out.splitlines():
            if "state" in line.lower():
                return re.sub(r"\s+", " ", line).strip()
        one_line = re.sub(r"\s+", " ", out).strip()
        return one_line[:120] or "не удалось опросить"
    except Exception as e:
        return f"не удалось опросить ({type(e).__name__})"


def proc_pids():
    found = {}
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "(Get-CimInstance Win32_Process -Filter \"Name='pythonw.exe'\") | "
             "ForEach-Object { ($_.ProcessId.ToString() + '|' + $_.CommandLine) }"],
            capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)
        for line in (r.stdout or "").splitlines():
            pid, _, cmd = line.partition("|")
            if "watchdog.py" in cmd:
                found["watchdog"] = pid.strip()
            elif "care.py" in cmd:
                found["care"] = pid.strip()
            elif "monitor.py" in cmd:
                found["monitor"] = pid.strip()
    except Exception:
        pass
    try:
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq winws.exe", "/FO", "CSV", "/NH"],
                           capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW)
        for line in (r.stdout or "").splitlines():
            parts = [p.strip('" ') for p in line.split('","')]
            if len(parts) >= 2 and parts[0] == "winws.exe":
                found["winws"] = parts[1]
    except Exception:
        pass
    return found


def lock_age():
    try:
        if LOCK.exists():
            return int((datetime.now().timestamp() - LOCK.stat().st_mtime))
    except Exception:
        pass
    return None


def event_kind(msg: str) -> str:
    """Короткий тип события для отчёта (10.0.8).

    Нужен, чтобы в журнале не оставалось нераспознанных «?». Раньше запись
    «ПАДЕНИЕ monitor (код 1) — перезапускаю» (17.10 11:49:42) читалась как «?»,
    хотя это реальное падение воркера, которое сторож перезапустил.
    """
    # Строки в журнале начинаются с даты («2026-10-20 11:01:17 …») — отбрасываем
    # её, иначе проверка по началу строки не срабатывала (тип «К» терялся).
    body = msg
    if len(body) > 19 and body[4] == "-" and body[10] == " ":
        body = body[20:]
    if "пульс" in body:
        return "П"          # пульс в норме
    if body.startswith("Код ") and "изменился" in body:
        return "К"          # правка кода воркера
    if "завершился" in body:
        return "В"          # выход экземпляра
    if "выход из процесса" in body:
        return "в"
    if "SystemExit" in body:
        return "x"
    if "запущен" in body:
        return "С"          # старт сторожа
    if "ПАДЕНИЕ" in body:
        return "п"          # падение воркера
    if "Выход дубля" in body:
        return "д"          # выход дубля сторожа (не сбой)
    if "Сеть требует стратегию" in body or "Желаемая стратегия" in body:
        return "т"          # требуется другая стратегия (11.0.0+)
    if "СМЕНА СТРАТЕГИИ" in body:
        return "г"          # смена стратегии обхода
    if "ПК спал" in body or "сон ПК" in body:
        return "с"          # сон ПК (10.0.7: событие сна в events.log)
    if "молчит" in body:
        return "м"
    if "winws" in body:
        return "W"
    if "Ночная проверка" in body:
        return "Н"
    if "Зависший" in body:
        return "З"
    return "?"


def detect_sleep_gap(mon):
    """Ищет провал в записях моника больше 30 мин — признак сна/гибернации ПК.

    Возвращает (начало, конец, минуты) или None.
    """
    if len(mon) < 2:
        return None
    prev = None
    for s in mon:
        m = TS_RE.search(s)
        if not m:
            continue
        try:
            t = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
        if prev and (t - prev).total_seconds() > 1800:
            return (prev, t, int((t - prev).total_seconds() // 60))
        prev = t
    return None


def build_report():
    now = datetime.now()
    lines = []
    add = lines.append
    add("=" * 64)
    add(f"НОЧНАЯ ПРОВЕРКА — {now:%Y-%m-%d %H:%M:%S}")
    add("=" * 64)

    problems = []
    # Сначала определяем, спал ли ПК: после сна перезапуск сторожа — это
    # ожидаемое поведение (процесс был заморожен, lock устарел), а не сбой.
    sleep_gap = detect_sleep_gap(tail_lines(MONITOR_LOG, WINDOW_HOURS))

    # --- версия и статус ---
    add("")
    add("--- Состояние ---")
    add(f"Служба zapret: {svc_state()}")
    pids = proc_pids()
    for name in ("watchdog", "care", "monitor", "winws"):
        pid = pids.get(name)
        add(f"{name:<9}: " + (f"PID {pid}" if pid else "НЕТ ПРОЦЕССА"))
        if not pid:
            problems.append(f"{name} не запущен")
    age = lock_age()
    if age is None:
        add("lock: файла нет (сторож точно умер)")
        problems.append("нет lock-файла")
    else:
        add(f"lock: возраст {age} сек" + ("  <= ВНИМАНИЕ: не обновляется!" if age > 180 else "  (пульс в норме)"))
        if age > 180:
            problems.append(f"lock не обновляется {age} сек — сторож завис")

    try:
        st = STATUS.read_text(encoding="utf-8", errors="replace")
        add(f"status.json: {st.strip()[:300]}")
    except Exception:
        add("status.json: не читается")

    # --- сторож за ночь ---
    add("")
    add(f"--- Сторож за {WINDOW_HOURS} ч (по events.log) ---")
    ev = tail_lines(EVENTS, WINDOW_HOURS)
    starts = [e for e in ev if "Сторож запущен" in e]
    deaths = [e for e in ev if "завершился" in e or "выход из процесса" in e]
    falls = [e for e in ev if "ПАДЕНИЕ" in e]
    # 10.0.8: старт рядом с правкой кода — это штатный самоперезапуск сторожа
    # (он сам подхватывает новый код), а не загадка. Считаем такие отдельно.
    code_changes = [e for e in ev if event_kind(e) == "К"]
    if starts:
        for e in starts:
            # 10.0.6: не размазываем отчёт — оставляем время и хвост строки
            add("  " + (e[:16] + " … " + e[-46:]) if len(e) > 64 else e)
        # Перезапуск сторожа сам по себе — не баг: кипер страхует, Discord при
        # этом работает (проверяется ниже по сбоям моника). Поэтому это
        # информация, а не замечание: смотрим сбои и живость lock.
        reason = ""
        if code_changes:
            reason = f" (правок кода за ночь: {len(code_changes)} — часть стартов это самоперезапуск под новый код)"
        if sleep_gap:
            add(f"  всего стартов: {len(starts)} (часть — самоперезапуск по коду и после сна ПК){reason}")
        else:
            add(f"  всего стартов: {len(starts)}{reason}")
    else:
        add("  стартов не было — сторож жил всю ночь")
    if deaths:
        for e in deaths:
            add("  выход: " + e)
    if falls:
        # 10.0.8: падение воркера — не сбой пользователя (сторож его перезапускает),
        # но раньше такое событие читалось как «?». Теперь тип «п» и счётчик.
        for e in falls:
            add("  падение воркера: " + e)
        add(f"  падений воркеров: {len(falls)} (сторож их перезапускает)")
    beats = [e for e in ev if "пульс в норме" in e]
    if beats:
        add(f"  пульс: {len(beats)} отметок, последняя — {beats[-1]}")
    # 10.0.8: контроль нераспознанных записей — чтобы «?» не возвращались
    unknown = [e for e in ev if event_kind(e) == "?"]
    if unknown:
        add(f"  нераспознанных записей: {len(unknown)} — стоит добавить тип")
        for e in unknown[:3]:
            add("    " + e[:80])

    # --- моник ---
    add("")
    add(f"--- Монитор за {WINDOW_HOURS} ч ---")
    mon = tail_lines(MONITOR_LOG, WINDOW_HOURS)
    ok = [m for m in mon if m.startswith("OK ")]
    bad = [m for m in mon if m.startswith("СБОЯ")]
    warm = [m for m in mon if m.startswith("WARMUP")]
    add(f"OK: {len(ok)}, СБОЯ: {len(bad)}, WARMUP: {len(warm)}")
    if mon:
        add(f"последняя запись: {mon[-1][:220]}")
    # Провал в записях моника = ПК спал (сон/гибернация). Такой перерыв
    # объясняет и «перезапуск» сторожа после сна: процесс был заморожен,
    # lock остался старым, и новый экземпляр корректно перехватил надзор.
    if sleep_gap:
        add(f"сон ПК: с {sleep_gap[0].strftime('%H:%M')} до {sleep_gap[1].strftime('%H:%M')} ({sleep_gap[2]} мин) — "
            "перезапуск сторожа после сна ожидаем, это не сбой")
    if bad:
        problems.append(f"сбоев Discord за ночь: {len(bad)}")
        for b in bad[-3:]:
            add("  СБОЯ: " + b[:200])
    if not ok and not bad:
        problems.append("моник за ночь не писал ни одной проверки")

    # --- журнал сторожа ---
    add("")
    add(f"--- Журнал сторожа (ошибки за {WINDOW_HOURS} ч) ---")
    wl = [w for w in tail_lines(WATCHDOG_LOG, WINDOW_HOURS) if "СБОЙ" in w or "Traceback" in w]
    if wl:
        for w in wl[-3:]:
            add("  " + w[:220])
        problems.append(f"сбоев дерева сторожа за ночь: {len(wl)}")
    else:
        add("  сбоев нет")

    # --- итог ---
    add("")
    add("--- ИТОГ ---")
    if problems:
        for p in problems:
            add(f"  ! {p}")
        add("ИТОГ: есть замечания, разобрать в дневнике")
    else:
        add("ИТОГ: всё в порядке, багов за ночь не найдено ✓")
    add("=" * 64)

    return "\n".join(lines), problems


def main():
    report, problems = build_report()
    try:
        with OUT.open("a", encoding="utf-8") as f:
            f.write(report + "\n")
    except OSError:
        pass
    try:
        note = ("Ночная проверка: всё в порядке" if not problems
                else f"Ночная проверка: замечаний — {len(problems)}")
        with EVENTS.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {note}\n")
    except OSError:
        pass
    print(report)


if __name__ == "__main__":
    main()