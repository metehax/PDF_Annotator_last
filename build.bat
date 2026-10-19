@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ==============================================
echo  PDF Annotator - Derleme (PyInstaller, onedir)
echo ==============================================

set "PY="
where py >nul 2>nul && (py -3.12 -c "pass" >nul 2>nul && set "PY=py -3.12" || set "PY=py -3")
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (echo HATA: Python bulunamadi. & exit /b 1)

if not exist "resources\tessdata\tur.traineddata" goto :notess
if not exist "resources\tessdata\eng.traineddata" goto :notess

rem Temiz derleme ortami: .venv'e dokunmaz
if exist ".buildvenv" rmdir /s /q ".buildvenv"
echo [1/6] Derleme ortami kuruluyor...
%PY% -m venv .buildvenv || goto :hata
set "VP=.buildvenv\Scripts\python.exe"
"%VP%" -m pip install --upgrade pip >nul || goto :hata
echo [2/6] Gereksinimler kuruluyor...
"%VP%" -m pip install -r requirements.txt pyinstaller || goto :hata
echo [3/6] Simge uretiliyor...
"%VP%" packaging\make_icon.py || goto :hata
echo [4/6] Derleniyor...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
"%VP%" -m PyInstaller --noconfirm --clean packaging\pdfannotator.spec || goto :hata
echo [5/6] Kendi kendini sinama (--selftest)...
"dist\PDF Annotator\PDF Annotator.exe" --selftest "dist\PDF Annotator\selftest.txt"
if errorlevel 1 (type "dist\PDF Annotator\selftest.txt" & goto :hata)
type "dist\PDF Annotator\selftest.txt"
echo [6/6] Kurucu (Inno Setup)...
set "ISCC="
for %%P in ("%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe") do if exist %%P set "ISCC=%%~P"
if not defined ISCC (echo UYARI: Inno Setup 6 yok; kurucu atlandi ^(winget install JRSoftware.InnoSetup^). & goto :bitti)
"%VP%" -c "import sys;sys.path.insert(0,'src');import appinfo;print(appinfo.VERSION)" > build\ver.txt
set /p APPVER=<build\ver.txt
"%VP%" -c "import sys;sys.path.insert(0,'src');import appinfo;print(appinfo.APP_ID.strip(chr(123)+chr(125)))" > build\id.txt
set /p APPGUID=<build\id.txt
"%ISCC%" /Qp "/DAppVersion=%APPVER%" "/DAppGuid=%APPGUID%" packaging\kurulum.iss || goto :hata
powershell -NoProfile -Command "Get-FileHash 'dist\PDF-Annotator-Setup-%APPVER%.exe' -Algorithm SHA256 | ForEach-Object { 'SHA-256: ' + $_.Hash }"
:bitti
echo.
echo Tamam: dist\PDF Annotator\PDF Annotator.exe
exit /b 0

:notess
echo HATA: resources\tessdata\tur.traineddata ve eng.traineddata gerekli (once kur.bat).
exit /b 1
:hata
echo.
echo HATA: Derleme basarisiz.
exit /b 1
