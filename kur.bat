@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ==============================================
echo  PDF Annotator - Kurulum
echo ==============================================

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY goto :nopython

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 goto :oldpython

if exist ".venv\Scripts\python.exe" goto :venvok
echo [1/4] Sanal ortam olusturuluyor...
%PY% -m venv .venv
if errorlevel 1 goto :hata
:venvok

echo [2/4] Gereksinimler kuruluyor (PySide6, PyMuPDF, Pillow)...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :hata

echo [3/4] OCR dil dosyalari (Turkce + Ingilizce) kontrol ediliyor...
if not exist "tessdata" mkdir "tessdata"
call :indir tur
call :indir eng

echo [4/4] Masaustu kisayolu olusturuluyor...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'PDF Annotator.lnk')); $s.TargetPath=(Resolve-Path '.venv\Scripts\pythonw.exe').Path; $s.Arguments='main_window.py'; $s.WorkingDirectory=(Get-Location).Path; $s.Save() } catch { exit 1 }"
if errorlevel 1 echo Kisayol olusturulamadi, calistir.bat dosyasini kullanabilirsiniz.

echo.
echo Kurulum tamamlandi. Uygulamayi calistir.bat ile ya da masaustundeki
echo "PDF Annotator" kisayoluyla acabilirsiniz.
pause
exit /b 0

:indir
if exist "tessdata\%1.traineddata" goto :eof
echo    %1.traineddata indiriliyor...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -UseBasicParsing -Uri 'https://github.com/tesseract-ocr/tessdata_fast/raw/main/%1.traineddata' -OutFile 'tessdata\%1.traineddata' } catch { exit 1 }"
if errorlevel 1 (
  echo    UYARI: %1.traineddata indirilemedi. OCR icin bu dosyayi tessdata klasorune elle koyun.
  if exist "tessdata\%1.traineddata" del "tessdata\%1.traineddata"
)
goto :eof

:nopython
echo HATA: Python bulunamadi. python.org adresinden Python 3.10 veya ustunu kurun
echo       ve kurulumda "Add python.exe to PATH" secenegini isaretleyin.
start "" https://www.python.org/downloads/
pause
exit /b 1

:oldpython
echo HATA: Python 3.10 veya uzeri gerekli.
pause
exit /b 1

:hata
echo.
echo HATA: Kurulum tamamlanamadi. Yukaridaki mesaji kontrol edin.
pause
exit /b 1
