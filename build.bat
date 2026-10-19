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

if not exist "tessdata\tur.traineddata" goto :notess
if not exist "tessdata\eng.traineddata" goto :notess

rem Temiz derleme ortami: .venv'e dokunmaz
if exist ".buildvenv" rmdir /s /q ".buildvenv"
echo [1/5] Derleme ortami kuruluyor...
%PY% -m venv .buildvenv || goto :hata
set "VP=.buildvenv\Scripts\python.exe"
"%VP%" -m pip install --upgrade pip >nul || goto :hata
echo [2/5] Gereksinimler kuruluyor...
"%VP%" -m pip install -r requirements.txt pyinstaller || goto :hata
echo [3/5] Simge uretiliyor...
"%VP%" make_icon.py || goto :hata
echo [4/5] Derleniyor...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
"%VP%" -m PyInstaller --noconfirm --clean pdfannotator.spec || goto :hata
echo [5/5] Kendi kendini sinama (--selftest)...
"dist\PDF Annotator\PDF Annotator.exe" --selftest "dist\PDF Annotator\selftest.txt"
if errorlevel 1 (type "dist\PDF Annotator\selftest.txt" & goto :hata)
type "dist\PDF Annotator\selftest.txt"
echo.
echo Tamam: dist\PDF Annotator\PDF Annotator.exe
exit /b 0

:notess
echo HATA: tessdata\tur.traineddata ve eng.traineddata gerekli (once kur.bat).
exit /b 1
:hata
echo.
echo HATA: Derleme basarisiz.
exit /b 1
