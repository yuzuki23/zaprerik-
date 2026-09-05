# -*- coding: utf-8 -*-
"""Автоматический релиз Zapretik на GitVerse через Playwright.

Запуск:
    python gitverse_release.py 4.0.4
"""
import subprocess
import sys
import time
from pathlib import Path

PROJ = Path(r"C:\запрет")
RAR = Path(r"C:\Program Files\WinRAR\Rar.exe")
OUT = Path(r"C:\Users\Leonid\AppData\Local\Temp\opencode\zapret_test")
REPO_URL = "https://gitverse.ru/miamura23/zapretik"
USER_DATA = PROJ / ".gitverse_session"


def build_rar(version):
    OUT.mkdir(parents=True, exist_ok=True)
    tag = f"v{version}"
    rar = OUT / f"zaprerik-{tag}.rar"
    if rar.exists():
        rar.unlink()
    subprocess.run(
        [str(RAR), "a", "-ep1", "-r", "-m5",
         "-x*\\.git", "-x*\\.git\\*", "-x*\\__pycache__", "-x*\\__pycache__\\*",
         "-x*.log", str(rar), "*"],
        capture_output=True, text=True, timeout=300, cwd=str(PROJ)
    )
    if not rar.exists():
        raise RuntimeError(f"RAR не создан: {rar}")
    size_mb = rar.stat().st_size / (1024 * 1024)
    if size_mb > 100:
        raise RuntimeError(f"Файл слишком большой: {size_mb:.1f} Мб (лимит GitVerse: 100 Мб)")
    print(f"  Размер: {size_mb:.1f} Мб")
    return rar


def create_release(version):
    from playwright.sync_api import sync_playwright

    tag = f"v{version}"
    rar = build_rar(version)

    print(f"[1/5] Архив: {rar}")

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA),
            headless=False,
        )
        page = browser.pages[0] if browser.pages else browser.new_page()

        url = f"{REPO_URL}/releases/new"
        print(f"[2/5] Открываю: {url}")
        page.goto(url, timeout=60000)
        time.sleep(5)

        # Куки
        try:
            page.locator('button:has-text("Принимаю")').first.click(timeout=5000)
            time.sleep(1)
            print("  Куки: OK")
        except Exception:
            print("  Куки: уже приняты")

        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(1)

        # Тег
        print("[3/5] Тег...")
        try:
            page.locator('button:has-text("Выберите тег")').first.click()
            time.sleep(1)
            page.locator(f'[role="option"]:has-text("{tag}")').first.click()
            time.sleep(2)
            print(f"  Тег: {tag}")
        except Exception as e:
            print(f"  Тег: {e}")

        # Ветка
        time.sleep(2)
        try:
            branch_btn = page.locator('button[role="combobox"]').nth(1)
            if branch_btn.is_enabled():
                branch_btn.click()
                time.sleep(1)
                page.locator('[role="option"]:has-text("main")').first.click()
                time.sleep(1)
                print("  Ветка: main")
            else:
                print("  Ветка: disabled (авто)")
        except Exception as e:
            print(f"  Ветка: {e}")

        # Название
        print("[4/5] Заполняю...")
        try:
            page.locator('input[name="title"]').first.fill(f"Zapretik {version}")
            print(f"  Название: Zapretik {version}")
        except Exception as e:
            print(f"  Название: {e}")

        # Описание
        try:
            desc = (
                f"## Zapretik {version}\n\n"
                f"### Что нового:\n"
                f"- Валидация типов значений в config.json (int, float, bool) при загрузке watchdog\n"
                f"- Автообновление timestamp в status.json каждые N циклов\n"
                f"- care.py: проверка доступности Discord API перед отправкой уведомлений\n"
                f"- general.bat: fallback на упрощённую стратегию если winws.exe не запустился\n\n"
                f"### Файлы:\n"
                f"- zaprerik-{tag}.rar — Windows"
            )
            editor = page.locator('[contenteditable="true"]').first
            editor.click()
            time.sleep(0.5)
            editor.fill(desc)
            print("  Описание: OK")
        except Exception as e:
            print(f"  Описание: {e}")

        # Файл
        try:
            page.locator('input[type="file"]').first.set_input_files(str(rar))
            print(f"  Файл: {rar.name}")
            time.sleep(3)
        except Exception as e:
            print(f"  Файл: {e}")

        # Создать — прокручиваем вниз и ищем кнопку
        print("[5/5] Создаю релиз...")
        for _ in range(5):
            page.evaluate("window.scrollBy(0, 500)")
            time.sleep(0.5)

        page.screenshot(path=str(PROJ / "_debug_bottom.png"))

        # Ищем кнопку "Создать" или "Опубликовать"
        try:
            found = False
            for text in ["Создать", "Опубликовать", "Создать релиз"]:
                try:
                    btn = page.locator(f'button:has-text("{text}")').first
                    if btn.is_visible():
                        btn.click()
                        print(f"  Нажата: {text}")
                        found = True
                        break
                except Exception:
                    continue

            if not found:
                # Пробуем submit
                try:
                    page.locator('button[type="submit"]').first.click()
                    print("  Нажата: submit")
                    found = True
                except Exception:
                    pass

            if not found:
                print("  Кнопка не найдена! Смотри _debug_bottom.png")

            time.sleep(5)
            print(f"\nГотово: {REPO_URL}/-/releases/tag/{tag}")
        except Exception as e:
            print(f"  Ошибка: {e}")

        page.screenshot(path=str(PROJ / "_debug_after.png"))
        browser.close()


def main():
    args = sys.argv[1:]
    if not args:
        print("Использование: python gitverse_release.py 4.0.4")
        sys.exit(1)
    create_release(args[0])


if __name__ == "__main__":
    main()
