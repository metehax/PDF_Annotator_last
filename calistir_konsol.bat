@echo off
rem Hata ayiklama: uygulamayi konsol penceresiyle acar, hata mesajlarini gosterir.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" call kur.bat
".venv\Scripts\python.exe" main_window.py
pause
