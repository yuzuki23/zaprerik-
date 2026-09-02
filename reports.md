### 🌅 Утро 02.09.2026 (среда)
- Служба zapret: **Running**. Обход Discord жив: `discord.com` -> 200, `detector404.ru/discord` -> 200. `winws` (PID 4824) запущен; мониторинг восстановлен — 3 процесса pythonw (watchdog PID 10784, care PID 12524, monitor PID 1088). За ночь watchdog падал (pythonw не мог запустить), утром восстановлен вручную.
- Погода (Яндекс.Погода):
  - Ставрополь: **+19°** (ясно, ощущается +17°, ветер 4 м/с В, влажность 62%).
  - Ессентуки: **+19°** (ясно, ощущается +17°, ветер 4 м/с, влажность 62%).
- Активная версия: **4.0.5**, стратегия `general.bat`.
- Важное: выпущена 4.0.5 — добавлена проверка winws перед стартом (general.bat), проверка размера файла (<100 Мб) в gitverse_release.py, логирование причины при падении всех процессов (watchdog.py). Миграция завершена: вернулись на **GitVerse** (gitverse.ru/miamura23/zapretik), GitHub удалён как remote. Все релизы (v1.0.0–v4.0.5) опубликованы на GitVerse. Linux обёртка загружена только на GitHub (34 архива).
- Настроение: доброе утро, солнышко поздоровалось ❤️

### 📋 Дневник 01.09.2026

**Выпуск патча 4.0.3:**
1. watchdog.py: добавлен `sys.stdout.reconfigure(encoding="utf-8")` — исправлены кракозябры в логе
2. service.bat: добавлена проверка Python при старте (если не найден — ошибка + ссылка на скачивание)
3. main.py: добавлен пункт **5. Текущая версия** в меню
4. .service/version.txt: bump до 4.0.3
5. py_compile OK для всех скриптов
6. Релиз **v4.0.3** создан и опубликован на GitHub (RAR 461 Кб)

**Коммиты дня:**
- `08dc9cf` — 4.0.3: UTF-8 watchdog, проверка Python, пункт «Версия» в меню
- `da1c671` — fix: ZapretikWatchdog BootTrigger + LogonTrigger, работает от батареи
- `4655db2` — Linux: обёртка Zapretik для nfqws (Arch Linux)
- `45701e1` — 4.0.4: Linux обёртка + BootTrigger fix

**Выпуск патча 4.0.4:**
1. service.bat: LOCAL_VERSION -> 4.0.4
2. main.py: GITHUB_UA -> Zapretik/4.0.4
3. .service/version.txt: 4.0.4
4. RAR архив: zaprerik-v4.0.4.rar (461 Кб)
5. Linux архив: zapretik-linux-v4.0.4.tar.gz (113 Кб)
6. Релиз **v4.0.4** опубликован на GitHub

**Linux обёртка (34 архива загружены на GitHub):**
- `linux/zapretik.sh` — основная обёртка (аналог main.py) для nfqws
- `linux/zapretik.service` — systemd-сервис
- `linux/zapretik-watchdog.sh` — сторож (аналог watchdog.py)
- `linux/install.sh` — установщик для Arch Linux
- `linux/README-linux.md` — документация
- Все архивы (v1.0.0–v4.0.3) загружены на GitHub

**Проверка доступности:**
- discord.com -> 200 ✅
- detector404.ru/discord -> 200 ✅
- crushon.ai/ru -> таймаут (заблокирован, в списках есть)
- pulsesync.dev -> Cloudflare challenge (норма)

### 🌙 Итог дня 01.09.2026 (вторник)
- **Статус Discord**: работает (discord.com -> 200)
- **Активная версия**: 4.0.4
- **Стратегия**: general.bat
- **Служба**: ZapretikWatchdog работает, BootTrigger + LogonTrigger, от батареи
- **Выпущено**: 2 релиза (4.0.3, 4.0.4)
- **Коммиты**: 4 (UTF-8 watchdog, BootTrigger fix, Linux обёртка, 4.0.4)
- **Linux**: создана обёртка для nfqws, 34 архива загружены на GitHub
- **Настроение**: продуктивный день, всё работает ❤️

---

### 🌙 Итог дня 31.08.2026 (понедельник)
(записан вчера, см. выше)

---

### 🌙 Итог дня 30.08.2026 (воскресенье)
(записано 30.08, см. выше)
- 🔔 Будильник: за вчера (2026-08-31) отправлено слотов: 7.
- 🔔 Будильник: за вчера (2026-09-01) отправлено слотов: 4.
