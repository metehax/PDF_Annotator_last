@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" call kur.bat
if not exist ".venv\Scripts\pythonw.exe" exit /b 1
start "" ".venv\Scripts\pythonw.exe" src\main_window.py
