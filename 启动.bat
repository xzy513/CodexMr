@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python with tkinter and try again.
  pause
  exit /b 1
)
start "" pythonw "%~dp0widget.py"
