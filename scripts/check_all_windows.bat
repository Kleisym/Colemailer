@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

echo == selfcheck ==
"%PY%" scripts\selfcheck.py
if errorlevel 1 exit /b 1

echo == pytest ==
"%PY%" -m pytest tests -q
exit /b %ERRORLEVEL%
