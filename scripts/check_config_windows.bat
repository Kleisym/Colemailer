@echo off
chcp 65001 >nul
setlocal
title Colemailer - проверка конфига

set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"

set "PY=python"
if exist "%ROOT%\.venv\Scripts\python.exe" set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%ROOT%\.venv\Scripts\python.exe" if exist "%ROOT%\venv\Scripts\python.exe" set "PY=%ROOT%\venv\Scripts\python.exe"

echo ======================================================
echo  Colemailer - проверка config.txt
echo  Папка: %ROOT%
echo ======================================================
echo.

if not exist "%ROOT%\config.txt" (
    echo [i] config.txt нет - создаю из config.example.txt
    if exist "%ROOT%\config.example.txt" copy /y "%ROOT%\config.example.txt" "%ROOT%\config.txt" >nul
)

"%PY%" "%ROOT%\bot.py" --check
echo.
echo Подсказки:
echo  - "нет api_id/api_hash" - ключи не заполнены: my.telegram.org или
echo    python bot.py --auto-api +79991234567
echo  - "номер не задан" - впиши phone в config.txt (нужен только для первого входа)
echo  - несколько аккаунтов - каждый в своей секции [accountN], ключи вне секций
echo    при наличии секций не читаются.
echo.
pause
