# -*- coding: utf-8 -*-
"""Мониторинг сбоев Discord.

Запуск:
    python monitor.py            # проверка каждые 2 минуты
    python monitor.py 5          # проверка каждые 5 минут

При каждом сбое (HTTP != 200) пишет в discord_monitor.log запись с датой,
проверяет статус на detector404.ru/discord и сохраняет картинку/код.
"""
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

os.system("")  # включаем ANSI-цвета в Windows-терминале

# Под pythonw stdout — это не консоль, а cp1251-пайп: эмодзи (✅ и т.п.) крашат
# print() с UnicodeEncodeError. Переводим вывод в utf-8 с безопасной заменой.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"

LOG = Path(r"C:\запрет\discord_monitor.log")
STATUS = Path(r"C:\запрет\discord_status.txt")
BASE_DIR = Path(r"C:\запрет")
REINSTALL = BASE_DIR / "reinstall_service.py"
DISCORD_URL = "https://discord.com/"
GATEWAY_URL = "https://gateway.discord.gg/"
CDN_URL = "https://cdn.discordapp.com/"
# discord.com — акторитетный эндпоинт доступности. gateway.discord.gg НЕ является
# критичным: он штатно отдаёт 404/000 на обычный GET и периодически таймаутится,
# поэтому никогда не считается сбоем. Проба идёт по обоим, но в вердикт и рестарт
# влияет только discord.com (плюс независимый детектор доступа).
HEALTH_URLS = [DISCORD_URL, GATEWAY_URL]
# Несколько детекторов: если основной (detector404.ru) ляжет — пробуем запасной.
DETECTORS = ["https://detector404.ru/discord", "https://www.gstatic.com/generate_204"]

# Проверка голосового пути: реальный WebSocket-хендшейк до шлюза Discord.
# DPI часто режет именно WebSocket (голос/видео), оставляя HTTPS живым — поэтому
# штатный HTTPS-пинг этого не ловит. Хендшейк до wss://gateway.discord.gg и ожидание
# ответа 101 = голосовой путь открыт и не заблокирован.
VOICE_WS_HOST = "gateway.discord.gg"
VOICE_WS_PORT = 443
VOICE_WS_PATH = "/?v=4&encoding=json"

# Защита от флапа: не перезапускаем службу чаще раза в это время (сек).
RESTART_COOLDOWN = 10 * 60
LAST_RESTART_TS = 0.0  # время последнего реального перезапуска (epoch)

NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW — консольные дети не открывают окно (важно для pythonw)

MAX_LOG_SIZE = 2 * 1024 * 1024  # 2 МБ
KEEP_LOGS = 3
RESTART_AFTER_FAILS = 3  # после стольких «настоящих» сбоев подряд — перезапускаем zapret

# Быстрые перепроверки при первом подозрении на сбой — чтобы транзитные
# микро-блики (шлюз/маршрут на пару секунд) не попадали в статус как «ЧАСТИЧНЫЙ СБОЙ».
RETRY_ATTEMPTS = 3   # сколько раз переспросить, прежде чем считать сбой настоящим
RETRY_DELAY = 3      # секунды между перепроверками


def notify(title, text):
    """Системное уведомление Windows при сбое (безопасно — никогда не падает)."""
    try:
        _notify_impl(title, text)
    except Exception:
        pass


def _notify_impl(title, text):
    ps1 = (
        "Add-Type -AssemblyName System.Windows.Forms\n"
        "Add-Type -AssemblyName System.Drawing\n"
        "$n=New-Object System.Windows.Forms.NotifyIcon\n"
        "$n.Icon=[System.Drawing.SystemIcons]::Warning\n"
        "$n.Visible=$true\n"
        f"$n.ShowBalloonTip(15000,'{title}','{text}',[System.Windows.Forms.ToolTipIcon]::Warning)\n"
        "$t=New-Object System.Windows.Forms.Timer\n"
        "$t.Interval=16000\n"
        "$t.Add_Tick({$n.Visible=$false;$n.Dispose();[System.Windows.Forms.Application]::Exit()})\n"
        "$t.Start()\n"
        "[System.Windows.Forms.Application]::Run()\n"
    )
    path = Path(os.environ.get("TEMP", r"C:\запрет")) / "monitor_notify.ps1"
    path.write_text(ps1, encoding="utf-8-sig")
    subprocess.Popen(["powershell", "-NoProfile", "-WindowStyle", "Hidden",
                      "-ExecutionPolicy", "Bypass", "-File", str(path)],
                     creationflags=subprocess.CREATE_NO_WINDOW)


def write_status(ts, codes, detector, detector_src, extra="", voice="?"):
    """Живой статус-файл: показывает текущее состояние Discord."""
    discord = codes.get(DISCORD_URL, "?")
    gateway = codes.get(GATEWAY_URL, "?")
    # 404/000 на шлюзе — это НОРМА (websocket-эндпоинт отвечает 404 на обычный GET
    # и периодически таймаутится). Шлюз НЕ влияет на вердикт: если сайт discord.com
    # отвечает 200 — всё работает, независимо от состояния gateway.
    gw_ok = gateway in ("200", "404")
    if discord == "200":
        verdict = "ВСЁ РАБОТАЕТ"
    else:
        verdict = "САЙТ discord.com НЕДОСТУПЕН" + ("" if gw_ok else " (шлюз тоже недоступен)")
    det_label = "detector404.ru/discord" if "detector404" in detector_src else detector_src
    lines = [
        f"Discord — живой статус (обновлено: {ts})",
        "==========================================",
        f"discord.com          -> {discord:>3}",
        f"gateway.discord.gg   -> {gateway:>3}",
        f"voice ws (голос)     -> {voice:>3}",
        f"{det_label:<22} -> {detector:>3}",
        "==========================================",
        "ВЕРДИКТ: " + verdict,
    ]
    if extra:
        lines.append("Доп.: " + extra)
    STATUS.write_text("\n".join(lines) + "\n", encoding="utf-8")


def status_api():
    """Парсит официальный статус Discord (discordstatus.com). Возвращает (api, indicator)."""
    try:
        r = subprocess.run(
            ["curl.exe", "-s", "--connect-timeout", "6", "--max-time", "12",
             "https://status.discord.com/api/v2/summary.json"],
            capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
        data = json.loads(r.stdout)
        api = "none"
        for c in data.get("components", []):
            name = (c.get("name") or "").lower()
            if "api" in name:  # ищем компонент по имени, а не по хардкод-id
                api = c.get("status", "unknown")
                break
        if api == "none":  # запасной вариант — по старому id
            for c in data.get("components", []):
                if c.get("id") == "rhznvxg4v7yh":
                    api = c.get("status", "unknown")
                    break
        indicator = data.get("status", {}).get("indicator", "unknown")
        return api, indicator
    except Exception:
        return "n/a", "n/a"


def http(url, timeout=12):
    try:
        r = subprocess.run(
            ["curl.exe", "-s", "-o", "NUL", "-w", "%{http_code}",
             "--connect-timeout", "6", "--max-time", str(timeout), url],
            capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW)
        return (r.stdout or "").strip() or "ERR"
    except Exception as exc:
        return f"ERR {exc}"


def check_detector():
    """Проверяет доступность Discord через один из детекторов (с запасным)."""
    for url in DETECTORS:
        code = http(url)
        if code in ("200", "204"):
            return code, url
    return "ERR", DETECTORS[0]


def check_voice_ws():
    """Реальная проверка голосового пути: WebSocket-хендшейк до шлюза Discord.

    DPI нередко режет именно WebSocket (голос/видео в Discord), оставляя обычный
    HTTPS живым — поэтому штатный пинг discord.com этого не ловит. Делаем минимальный
    WS-апгрейд до wss://gateway.discord.gg и ждём ответ 101 Switching Protocols.
    Возвращает 'OK' (путь открыт) или 'ERR <причина>'.
    """
    try:
        import base64 as _b64
        import ssl as _ssl
        raw = _b64.b64encode(os.urandom(16)).decode()
        ctx = _ssl.create_default_context()
        plain = socket.create_connection((VOICE_WS_HOST, VOICE_WS_PORT), timeout=8)
        sock = ctx.wrap_socket(plain, server_hostname=VOICE_WS_HOST)
        sock.settimeout(8)
        req = (
            f"GET {VOICE_WS_PATH} HTTP/1.1\r\n"
            f"Host: {VOICE_WS_HOST}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {raw}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        ).encode()
        sock.sendall(req)
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(1024)
            if not chunk:
                break
            buf += chunk
        sock.close()
        if not buf:
            return "ERR нет ответа"
        status_line = buf.split(b"\r\n", 1)[0].decode(errors="replace")
        if "101" in status_line:
            return "OK"
        return "ERR " + status_line
    except Exception as exc:
        return f"ERR {exc}"


def retry_resolve(discord_url, gateway_url):
    """Серия быстрых перепроверок, чтобы отсечь транзитные микро-блики.

    Возвращает (recovered, last_discord_code, last_gateway_code):
      - recovered=True  — на одной из перепроверок оба эндпоинта вернулись в норму;
      - recovered=False — блик не отпускает, возвращаются коды последней перепроверки.
    """
    last_d, last_g = "?", "?"
    for _ in range(RETRY_ATTEMPTS):
        time.sleep(RETRY_DELAY)
        last_d = http(discord_url)
        last_g = http(gateway_url)
        if last_d == "200":  # шлюз не критичен — ориентируемся на discord.com
            return True, last_d, last_g
    return False, last_d, last_g


def winws_alive():
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "if (Get-Process winws -ErrorAction SilentlyContinue) { 'yes' } else { 'no' }"],
                           capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)
        return (r.stdout or "").strip()
    except Exception:
        return "?"


def self_test():
    """Стартовый self-test: проверяем, что Discord реально доступен через обход.

    Не блокирует запуск — просто сообщает статус. Если обход не поднялся,
    монитор всё равно продолжает наблюдение и сам поднимет службу при сбое.
    """
    code = http("https://discord.com/", timeout=15)
    det, det_src = check_detector()
    if code == "200":
        msg = f"Self-test: Discord доступен через обход ✅ (discord.com -> 200, detector -> {det})"
        print(GREEN + msg + RESET, flush=True)
    else:
        msg = (f"Self-test: Discord НЕ доступен при старте (discord.com -> {code}, "
               f"detector -> {det}) — монитор продолжает наблюдение")
        print(YELLOW + msg + RESET, flush=True)
    LOG.open("a", encoding="utf-8").write("SELF-TEST " + msg + "\n")


def rotate_log():
    """Если лог разросся — сдвигает копии (.1, .2, ...) и начинает новый."""
    if not LOG.exists() or LOG.stat().st_size < MAX_LOG_SIZE:
        return
    for i in range(KEEP_LOGS - 1, 0, -1):
        src = LOG.with_name(f"{LOG.name}.{i}")
        dst = LOG.with_name(f"{LOG.name}.{i + 1}")
        if src.exists():
            dst.write_bytes(src.read_bytes())
            src.unlink()
    LOG.with_name(f"{LOG.name}.1").write_bytes(LOG.read_bytes())
    LOG.write_text("", encoding="utf-8")


def service_exists():
    """True, если служба zapret зарегистрирована в системе (не удалена)."""
    try:
        r = subprocess.run(["sc", "query", "zapret"], capture_output=True, text=True,
                           timeout=15, creationflags=NO_WINDOW)
        return r.returncode == 0 and "STATE" in r.stdout
    except Exception:
        return True  # не удалось проверить — считаем, что служба есть (не трогаем)


def restart_zapret_service():
    """Перезапуск службы zapret (winws).

    Если служба удалена (не просто остановлена) — сначала пересоздаём её через
    reinstall_service.py. Запуск идёт без UAC, если монитор запущен с правами
    админа (наследует elevation от сторожа ZapretikWatchdog).
    """
    created = ""
    if not service_exists():
        # служба отсутствует — скорее всего была удалена. Пересоздаём.
        created = " | служба отсутствовала — вызвано пересоздание"
        notify("Zapret: служба zapret была удалена",
               "Пересоздал и запускаю автоматически (без UAC)")
        try:
            subprocess.run([sys.executable, str(REINSTALL)],
                           capture_output=True, text=True, timeout=120,
                           creationflags=NO_WINDOW)
        except Exception as exc:
            return f"FAIL пересоздание: {exc}"
    try:
        subprocess.run(["net", "stop", "zapret"], capture_output=True, text=True, timeout=30,
                       creationflags=NO_WINDOW)
    except Exception:
        pass
    time.sleep(2)
    try:
        r = subprocess.run(["net", "start", "zapret"], capture_output=True, text=True, timeout=30,
                            creationflags=NO_WINDOW)
        return ("OK" + created) if r.returncode == 0 else f"FAIL {r.stdout.strip()[-100:]}" + created
    except Exception as exc:
        return f"FAIL {exc}" + created


def restart_zapret():
    """Перезапуск zapret (winws): убить старый процесс и стартовать restart_zapret.bat."""
    try:
        subprocess.run(["taskkill", "/F", "/IM", "winws.exe"],
                       capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW)
    except Exception:
        pass
    time.sleep(2)
    try:
        subprocess.Popen(["cmd", "/c", r"C:\запрет\restart_zapret.bat"],
                         creationflags=subprocess.CREATE_NO_WINDOW)
        return "OK"
    except Exception as exc:
        return f"FAIL {exc}"


def restore_discord():
    """Перезапускает службу zapret по кругу, пока discord.com не вернётся к 200.

    ВАЖНО: перезапускаем именно СЛУЖБУ (restart_zapret_service), а не автономный
    winws через restart_zapret.bat — иначе связь со службой теряется и при
    перезагрузке ПК обход не поднимется.
    """
    for attempt in range(1, 6):
        res = restart_zapret_service()
        time.sleep(7)
        if http("https://discord.com/") == "200":
            return f"OK (попытка {attempt}, {res})"
    return "FAIL после 5 перезапусков службы"


def main():
    global LAST_RESTART_TS
    self_test()
    # Запрос на перезапуск службы zapret БЕЗ прав админа: если есть флаг-файл —
    # моник (запущен с повышенными правами от сторожа) перезапускает службу сам.
    # Создать флаг может кто угодно (без админа); применяет его привилегированный моник.
    RESTART_REQUEST = BASE_DIR / ".restart_zapret_request"
    if RESTART_REQUEST.exists():
        try:
            RESTART_REQUEST.unlink()
            print(YELLOW + "Запрошен перезапуск службы zapret (флаг-файл)..." + RESET, flush=True)
            restart_zapret_service()
        except Exception as exc:
            print(RED + f"Ошибка перезапуска по флагу: {exc}" + RESET, flush=True)
    interval = int(sys.argv[1]) * 60 if len(sys.argv) > 1 else 120
    print(f"Мониторинг Discord, интервал {interval // 60} мин. Лог: {LOG}")
    was_down = False
    fail_streak = 0  # подряд идущие «настоящие» сбои (маршрутная блокировка)
    while True:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        codes = {u: http(u) for u in HEALTH_URLS}
        detector, detector_src = check_detector()
        # Вердикт «всё ок» = сайт discord.com отвечает 200 И независимый детектор
        # подтверждает доступ. gateway.discord.gg игнорируется (штатно 404/000).
        ok = (codes.get(DISCORD_URL) == "200") and (detector in ("200", "204"))
        api, indicator = status_api()  # официальный статус Discord (status.discord.com)
        cdn = http(CDN_URL)  # Discord CDN (аватары/картинки)
        voice = check_voice_ws()  # реальная проверка голосового WebSocket-пути
        disc_gone = api in ("major_outage", "partial_outage") or indicator in ("major", "minor", "critical")
        extra = f"discordstatus.com: API={api}, indicator={indicator} | cdn.discordapp.com -> {cdn} | voice_ws:{voice}"
        line = (f"{ts} | " + " | ".join(f"{u} -> {c}" for u, c in codes.items())
                + f" | detector({detector_src}) -> {detector} | api: {api}/{indicator} | voice_ws -> {voice}")

        if ok:
            # всё в порядке — пишем статус и сбрасываем счётчик сбоев
            fail_streak = 0
            write_status(ts, codes, detector, detector_src, extra, voice)  # живой статус-файл
            if was_down and not disc_gone:
                # официальный статус восстановился — радостное уведомление
                notify("Discord снова работает!", f"{ts}\\nAPI: {api} ({indicator}) — можно заходить")
            was_down = disc_gone
            print(GREEN + "OK: " + line + " | всё в порядке" + RESET, flush=True)
            LOG.open("a", encoding="utf-8").write("OK " + line + " | всё в порядке\n")
        else:
            # первичный признак сбоя. НЕ пишем «ЧАСТИЧНЫЙ СБОЙ» сразу — сначала
            # быстрые перепроверки, чтобы транзитный микро-блип не попал в статус.
            alive = winws_alive()
            svc = "есть" if service_exists() else "ОТСУТСТВУЕТ (удалена)"
            if alive == "no" or alive == "?":
                # winws мёртв/неизвестен — сразу перезапуск и проверка восстановления
                fail_streak = 0
                restore = restore_discord()
                codes = {u: http(u) for u in HEALTH_URLS}
                write_status(ts, codes, detector, detector_src, extra, voice)
                line2 = line + f" | winws -> {alive} | service -> {svc} | autorestart -> {restore}"
                print(RED + "СБОЙ: " + line2 + RESET, flush=True)
                LOG.open("a", encoding="utf-8").write("СБОЙ " + line2 + "\n")
                notify("Zapret: сбой Discord (winws)", f"{ts}\n{restore}")
                was_down = disc_gone
            else:
                # winws жив — серия быстрых перепроверок (retry), чтобы отсечь
                # разовые обрывы маршрута. Если на перепроверке всё вернулось в норму,
                # это НЕ сбой — тихо пишем «ВСЁ РАБОТАЕТ» (микро-блип отпущен).
                recovered, d2, g2 = retry_resolve(DISCORD_URL, GATEWAY_URL)
                if recovered:
                    fail_streak = 0
                    codes = {DISCORD_URL: d2, GATEWAY_URL: g2}
                    # Пересобираем строку из РЕАЛЬНЫХ (восстановленных) кодов,
                    # чтобы в логе не висело противоречивое «OK … 000».
                    line = (f"{ts} | " + " | ".join(f"{u} -> {c}" for u, c in codes.items())
                            + f" | detector({detector_src}) -> {detector} | api: {api}/{indicator} | voice_ws -> {voice}")
                    write_status(ts, codes, detector, detector_src,
                                 extra + " | микро-блип отпущен на перепроверке — работает", voice)
                    if was_down and not disc_gone:
                        notify("Discord снова работает!", f"{ts}\\nAPI: {api} ({indicator}) — можно заходить")
                    was_down = disc_gone
                    print(GREEN + "OK: " + line + " (микро-блип, сам ожил на перепроверке)" + RESET, flush=True)
                    LOG.open("a", encoding="utf-8").write(
                        "OK " + line + " (микро-блип маршрута, сам восстановился на перепроверке)\n")
                else:
                    # Перепроверки не помогли. Решаем: настоящий блок или мимолётный блип.
                    write_status(ts, codes, detector, detector_src, extra, voice)
                    disc_down = codes.get(DISCORD_URL) != "200"
                    det_ok = detector in ("200", "204")

                    if not disc_down:
                        # discord.com жив — «сбой» был на шлюзе/в пробе, а не на сайте.
                        # Не трогаем обход: это штатное поведение gateway.discord.gg.
                        fail_streak = 0
                        line2 = line + " | discord.com доступен — микро-блип не на сайте, обход не трогаем"
                        print(YELLOW + "INFO: " + line2 + RESET, flush=True)
                        LOG.open("a", encoding="utf-8").write("INFO " + line2 + "\n")
                    elif det_ok:
                        # Сайт не отвечает при прямой пробе, НО независимый детектор
                        # подтверждает, что Discord доступен. Значит это транзитный
                        # затык/особенность пробы, а не блок — обход не перезапускаем.
                        fail_streak = 0
                        line2 = line + " | discord.com недоступен при пробе, но detector404 доступен — транзитный блип, обход не трогаем"
                        print(YELLOW + "INFO: " + line2 + RESET, flush=True)
                        LOG.open("a", encoding="utf-8").write("INFO " + line2 + "\n")
                    elif detector == "ERR":
                        # ОБА детектора недоступны — не можем независимо подтвердить
                        # блок Discord. Не дёргаем обход из-за отказа самих детекторов:
                        # ждём ещё цикл, счётчик сбоев не накручиваем.
                        fail_streak = 0
                        line2 = line + " | оба детектора недоступны — блок не подтверждён, ждём ещё цикл (обход не трогаем)"
                        print(YELLOW + "INFO: " + line2 + RESET, flush=True)
                        LOG.open("a", encoding="utf-8").write("INFO " + line2 + "\n")
                    else:
                        # Оба упали: и сайт, и независимый детектор — настоящий блок/падение.
                        failed = ["discord.com"]
                        if codes.get(GATEWAY_URL) not in ("200", "404"):
                            failed.append("gateway.discord.gg")
                        fail_streak += 1
                        line2 = line + (f" | winws жив — маршрутная блокировка "
                                        f"({fail_streak}/{RESTART_AFTER_FAILS}): " + ", ".join(failed))
                        if fail_streak >= RESTART_AFTER_FAILS:
                            if disc_gone:
                                # подтверждённый глобальный сбой Discord — перезапуск не поможет
                                line2 += " | глобальный сбой Discord (status.discord.com) — перезапуск пропущен"
                                fail_streak = 0
                                print(YELLOW + "INFO: " + line2 + RESET, flush=True)
                                LOG.open("a", encoding="utf-8").write("INFO " + line2 + "\n")
                            else:
                                now = time.time()
                                if now - LAST_RESTART_TS < RESTART_COOLDOWN:
                                    # защита от флапа: не перезапускаем чаще раза в RESTART_COOLDOWN
                                    line2 += (" | autorestart пропущен (cooldown: перезапуск был менее "
                                              f"{RESTART_COOLDOWN // 60} мин назад)")
                                    fail_streak = 0
                                    print(YELLOW + "INFO: " + line2 + RESET, flush=True)
                                    LOG.open("a", encoding="utf-8").write("INFO " + line2 + "\n")
                                else:
                                    # столько подряд — перезапускаем службу zapret (winws),
                                    # чтобы сбросить DPI-состояние и поднять обход
                                    res = restart_zapret_service()
                                    LAST_RESTART_TS = now
                                    line2 += f" | autorestart -> {res}"
                                    fail_streak = 0
                                    print(RED + "СБОЙ: " + line2 + RESET, flush=True)
                                    LOG.open("a", encoding="utf-8").write("СБОЙ " + line2 + "\n")
                                    notify("Zapret: перезапуск службы",
                                           f"{ts}\n{RESTART_AFTER_FAILS} сбоя подряд (сайт+детектор), перезапускаю zapret")
                        else:
                            # пока не набралось RESTART_AFTER_FAILS подряд — INFO, не тревога
                            print(YELLOW + "INFO: " + line2 + RESET, flush=True)
                            LOG.open("a", encoding="utf-8").write("INFO " + line2 + "\n")
                            notify("Zapret: Discord недоступен",
                                    f"{ts}\nМаршрутная блокировка ({', '.join(failed)}), продолжается")
                    was_down = disc_gone
        rotate_log()
        time.sleep(interval)


if __name__ == "__main__":
    main()
