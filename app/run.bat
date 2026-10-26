@echo off
rem FloraPlan (basic edition): double-click to start. See run.py.
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11+ is required: https://www.python.org/downloads/
  start "" https://www.python.org/downloads/
  pause
  exit /b 1
)
python run.py
if errorlevel 1 pause
