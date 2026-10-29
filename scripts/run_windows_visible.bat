@echo off
chcp 65001 >nul
setlocal
title Colemailer

cd /d "%~dp0.."
set "ROOT=%CD%"

set "PY=python"
if exist "%ROOT%\.venv\Scripts\python.exe" set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%ROOT%\.venv\Scripts\python.exe" if exist "%ROOT%\venv\Scripts\python.exe" set "PY=%ROOT%\venv\Scripts\python.exe"

echo ======================================================
echo  Colemailer - запуск в видимом окне
echo  Папка: %ROOT%
echo ======================================================
echo  Это окно нужно для первого входа: бот спросит номер,
echo  код из Telegram и пароль 2FA (если он включён).
echo  Для работы 24/7 потом поставь автозапуск:
echo    scripts\install_autostart_windows.bat
echo ======================================================
echo.

if not exist "%ROOT%\bot.py" (
    echo [ОШИБКА] В "%ROOT%" нет bot.py. Скрипт должен лежать в папке scripts рядом с ботом.
    pause
    exit /b 1
)

if not exist "%ROOT%\config.txt" (
    if exist "%ROOT%\config.example.txt" (
        echo [i] config.txt не найден - создаю из config.example.txt
        copy /y "%ROOT%\config.example.txt" "%ROOT%\config.txt" >nul
    )
)

"%PY%" "%ROOT%\bot.py"
set "CODE=%ERRORLEVEL%"

echo.
if not "%CODE%"=="0" (
    echo [i] Бот завершился с кодом %CODE%.
    echo     Если это первый запуск - заполни api_id/api_hash в config.txt
    echo     или запусти: python bot.py --auto-api +79991234567
)
echo Окно можно закрыть.
pause
