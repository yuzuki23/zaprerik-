@echo off
rem ============================================================
rem  Zapretik - запуск одной кнопкой
rem ============================================================
chcp 65001 > nul
cd /d "%~dp0"

rem --- Проверяем, что Python установлен -----------------------
where python > nul 2>&1
if errorlevel 1 (
    echo [ОШИБКА] Python не найден. Установите его с https://www.python.org/downloads/
    echo Не забудьте отметить галочку "Add python.exe to PATH" при установке.
    pause
    exit /b 1
)

rem --- Устанавливаем зависимости при первом запуске -----------
if not exist ".deps_ok" (
    echo Устанавливаю зависимости (один раз)...
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ОШИБКА] Не удалось установить зависимости.
        pause
        exit /b 1
    )
    echo ok> .deps_ok
)

rem --- Запускаем (права администратора скрипт запросит сам) ---
python main.py
pause
