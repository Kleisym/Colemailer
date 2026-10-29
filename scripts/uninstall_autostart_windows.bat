@echo off
chcp 65001 >nul
setlocal
title Colemailer - удаление автозапуска

set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "TARGET_VBS=%STARTUP%\ColemailerAutostart.vbs"
set "LEGACY_VBS=%STARTUP%\TelegramSpambusterAutostart.vbs"

echo ======================================================
echo  Colemailer - удаление автозапуска Windows
echo ======================================================
echo.

set "FOUND=0"
if exist "%TARGET_VBS%" (
    del /f /q "%TARGET_VBS%"
    echo [OK] Удалён: %TARGET_VBS%
    set "FOUND=1"
)
if exist "%LEGACY_VBS%" (
    del /f /q "%LEGACY_VBS%"
    echo [OK] Удалён старый: %LEGACY_VBS%
    set "FOUND=1"
)
if "%FOUND%"=="0" (
    echo [i] Автозапуска в папке Автозагрузки нет - удалять нечего.
)

echo.
echo Сам бот, если он уже запущен, продолжает работать.
echo Остановить его: scripts\stop_windows.bat
echo.
pause
