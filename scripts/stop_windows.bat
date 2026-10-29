@echo off
chcp 65001 >nul
setlocal
echo ======================================================
echo  Colemailer - остановка всех процессов bot.py
echo ======================================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "$p = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine -match 'bot\.py' -and $_.Name -match '^(python|pythonw|py)(\.exe)?$' }); if ($p.Count -eq 0) { Write-Host 'Активных процессов Colemailer не найдено.' } else { foreach ($x in $p) { try { Stop-Process -Id $x.ProcessId -Force -ErrorAction Stop; Write-Host ('[OK] Остановлен PID ' + $x.ProcessId) } catch { Write-Host ('[!] PID ' + $x.ProcessId + ' не остановлен: ' + $_.Exception.Message) } } }"

echo.
echo Если бот был запущен службой systemd или автозапуском Windows,
echo он поднимется снова: сначала сними автозапуск
echo   scripts\uninstall_autostart_windows.bat
echo.
pause
