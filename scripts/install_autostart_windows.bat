@echo off
chcp 65001 >nul
setlocal
title Colemailer - автозапуск

set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "TARGET_VBS=%STARTUP%\ColemailerAutostart.vbs"
set "LEGACY_VBS=%STARTUP%\TelegramSpambusterAutostart.vbs"

echo ======================================================
echo  Colemailer - тихий автозапуск при входе в Windows
echo ======================================================
echo  Папка проекта: %ROOT%
echo.

if not exist "%ROOT%\bot.py" (
    echo [ОШИБКА] Не нашёл bot.py в "%ROOT%".
    echo Положи этот скрипт в папку scripts рядом с bot.py.
    pause
    exit /b 1
)

set "PY=python"
if exist "%ROOT%\.venv\Scripts\python.exe" set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%ROOT%\.venv\Scripts\python.exe" if exist "%ROOT%\venv\Scripts\python.exe" set "PY=%ROOT%\venv\Scripts\python.exe"

set "PYW=pythonw"
set "PYW_IS_PATH=1"
if exist "%ROOT%\.venv\Scripts\pythonw.exe" set "PYW=%ROOT%\.venv\Scripts\pythonw.exe"
if not exist "%ROOT%\.venv\Scripts\pythonw.exe" if exist "%ROOT%\venv\Scripts\pythonw.exe" set "PYW=%ROOT%\venv\Scripts\pythonw.exe"
if /i "%PYW%"=="pythonw" set "PYW_IS_PATH=0"

if "%PYW_IS_PATH%"=="0" (
    where pythonw >nul 2>&1
    if errorlevel 1 (
        echo [!] Не нашёл pythonw.exe. Поставь Python 3.10+ и создай venv:
        echo     python -m venv .venv
        echo     .venv\Scripts\python -m pip install -r requirements.txt
        pause
        exit /b 1
    )
)

if not exist "%ROOT%\config.txt" (
    if exist "%ROOT%\config.example.txt" (
        echo [i] config.txt не найден - создаю из config.example.txt
        copy /y "%ROOT%\config.example.txt" "%ROOT%\config.txt" >nul
        echo [i] Заполни api_id/api_hash в config.txt, иначе бот не подключится.
    )
)

echo Проверяю конфиг (python bot.py --check):
"%PY%" "%ROOT%\bot.py" --check
echo.

if not exist "%ROOT%\*.session" (
    echo [!] Файла сессии ещё нет. Первый вход надо сделать вручную:
    echo     scripts\run_windows_visible.bat
    echo     Иначе тихий запуск не сможет запросить код из Telegram.
    echo.
)

if exist "%LEGACY_VBS%" (
    del /f /q "%LEGACY_VBS%" >nul 2>&1
    echo [i] Убрал старый автозапуск SpamBuster из Автозагрузки.
)

if not exist "%STARTUP%" mkdir "%STARTUP%" >nul 2>&1

echo Создаю %TARGET_VBS% ...
(
echo Set sh = CreateObject("WScript.Shell"^)
echo sh.CurrentDirectory = "%ROOT%"
echo sh.Run Chr(34^) ^& "%PYW%" ^& Chr(34^) ^& " bot.py", 0, False
) > "%TARGET_VBS%"

if not exist "%TARGET_VBS%" (
    echo [ОШИБКА] Не удалось создать файл автозапуска.
    pause
    exit /b 1
)

echo.
echo [OK] Автозапуск установлен:
echo      %TARGET_VBS%
echo      При следующем входе в Windows бот поднимется сам, без окна.
echo      Запускаю его прямо сейчас...

wscript.exe "%TARGET_VBS%"
echo [OK] Готово. Статус: scripts\status_windows.bat, остановка: scripts\stop_windows.bat
echo.
pause
