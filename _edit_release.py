# -*- coding: utf-8 -*-
"""Редактирование описания релиза на GitVerse через Playwright."""
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

PROJ = Path(r"C:\запрет")
REPO_URL = "https://gitverse.ru/miamura23/zapretik"
USER_DATA = PROJ / ".gitverse_session"

VERSION = "5.0.1"
TAG = f"v{VERSION}"

DESC = f"""## Zapretik {VERSION}

### Что нового:
- Исправлен баг распаковки: теперь требуется WinRAR (убрана ошибочная попытка распаковать .rar как .zip)
- Добавлена проверка диапазонов числовых значений в config.json (watchdog.py)
- Добавлен retry (3 попытки) при проверке обновлений на GitVerse

### Файлы:
- zaprerik-{TAG}.rar — Windows
"""

with sync_playwright() as p:
    browser = p.chromium.launch_persistent_context(
        user_data_dir=str(USER_DATA),
        headless=False,
    )
    page = browser.pages[0] if browser.pages else browser.new_page()

    url = f"{REPO_URL}/releases/edit/{TAG}"
    print(f"Открываю: {url}")
    page.goto(url, timeout=60000)
    time.sleep(5)

    # Куки
    try:
        page.locator('button:has-text("Принимаю")').first.click(timeout=5000)
        time.sleep(1)
    except Exception:
        pass

    # Описание
    try:
        editor = page.locator('[contenteditable="true"]').first
        editor.click()
        time.sleep(0.5)
        editor.fill(DESC)
        print("Описание: OK")
    except Exception as e:
        print(f"Описание: {e}")

    time.sleep(2)

    # Сохранить
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    time.sleep(1)
    try:
        for text in ["Сохранить", "Сохранить изменения", "Обновить"]:
            try:
                btn = page.locator(f'button:has-text("{text}")').first
                if btn.is_visible():
                    btn.click()
                    print(f"Нажата: {text}")
                    break
            except Exception:
                continue
    except Exception as e:
        print(f"Кнопка: {e}")

    time.sleep(5)
    print("Готово!")
    browser.close()
