@echo off
chcp 65001 >nul
setlocal
title Colemailer - статус

set "ROOT=%~dp0.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"

set "PY=python"
if exist "%ROOT%\.venv\Scripts\python.exe" set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%ROOT%\.venv\Scripts\python.exe" if exist "%ROOT%\venv\Scripts\python.exe" set "PY=%ROOT%\venv\Scripts\python.exe"

echo ======================================================
echo  Colemailer - статус
echo  Папка: %ROOT%
echo ======================================================
echo.

echo [Конфиг]
"%PY%" "%ROOT%\bot.py" --check
echo.

echo [Процессы bot.py]
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -match 'bot\.py' -and $_.Name -match '^(python|pythonw|py)(\.exe)?$' }); if ($p.Count -eq 0) { Write-Host '  не запущен' } else { foreach ($x in $p) { Write-Host ('  PID ' + $x.ProcessId + '  ' + $x.Name) } }"
echo.

echo [Файлы сессии]
if exist "%ROOT%\*.session" (
    for %%F in ("%ROOT%\*.session") do echo   %%~nxF
) else (
    echo   нет - первый вход ещё не сделан
)
echo.

echo [Автозапуск Windows]
if exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ColemailerAutostart.vbs" (
    echo   установлен
) else (
    echo   не установлен ^(scripts\install_autostart_windows.bat^)
)
echo.
pause
