# -*- coding: utf-8 -*-
"""Удаление ассета с релиза GitVerse через Playwright."""
import sys
import time
from pathlib import Path

PROJ = Path(r"C:\запрет")
REPO_URL = "https://gitverse.ru/miamura23/zapretik"
USER_DATA = PROJ / ".gitverse_session"


def delete_asset(tag, asset_name):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA),
            headless=False,
        )
        page = browser.pages[0] if browser.pages else browser.new_page()

        page.goto(f"{REPO_URL}/releases/tag/{tag}", timeout=60000)
        time.sleep(5)

        try:
            page.locator('button:has-text("Принимаю")').first.click(timeout=5000)
            time.sleep(1)
        except Exception:
            pass

        # Прокручиваем к блоку ассетов и разворачиваем его
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(1)
        print(f"Ищу ассеты {tag}...")
        try:
            assets_btn = page.locator('text="Ассеты"').first
            assets_btn.scroll_into_view_if_needed()
            time.sleep(0.5)
            assets_btn.click()
            time.sleep(2)
            print("Ассеты развернуты")
        except Exception as e:
            print(f"Ассеты: {e}")

        page.screenshot(path=str(PROJ / "_debug_assets2.png"))

        # Теперь ищем нужный файл
        print(f"Ищу: {asset_name}")
        try:
            file_elem = page.locator(f'text="{asset_name}"').first
            file_elem.scroll_into_view_if_needed()
            time.sleep(1)

            # На GitVerse ассеты выглядят так:
            # [иконка] filename  [размер]  [дата]  [иконка корзины]
            # Ищем кнопку (с SVG) в той же строке
            # Используем xpath для поиска строки
            row = file_elem.locator('xpath=ancestor::*[self::div or self::tr][1]').first

            # Ищем кнопку с SVG (корзина) в строке
            delete_btn = row.locator('button:has(svg)').last
            delete_btn.click()
            time.sleep(2)
            print("Нажата корзина")

            # Подтверждаем
            try:
                page.locator('button:has-text("Удалить"), button:has-text("Да")').first.click(timeout=5000)
                time.sleep(2)
                print(f"Удалено: {asset_name}")
            except Exception:
                print("OK")

        except Exception as e:
            print(f"Ошибка: {e}")

        page.screenshot(path=str(PROJ / "_debug_final.png"))
        browser.close()


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print("Использование: python gitverse_delete_asset.py v4.0.4 'zapretik-linux-v4.0.4.tar.gz'")
        sys.exit(1)
    delete_asset(args[0], args[1])


if __name__ == "__main__":
    main()
