@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" scripts\selfcheck.py %*
) else if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" scripts\selfcheck.py %*
) else (
    python scripts\selfcheck.py %*
)
exit /b %ERRORLEVEL%
