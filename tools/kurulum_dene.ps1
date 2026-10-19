# Kurucuyu sessizce kullanıcı başına geçici klasöre kurar, --selftest çalıştırır, kaldırır ve izleri denetler.
# Kullanım: powershell -ExecutionPolicy Bypass -File tools\kurulum_dene.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot
$setup = Get-ChildItem "$root\dist\PDF-Annotator-Setup-*.exe" | Select-Object -First 1
$d = Join-Path $env:TEMP "pdfa_inst"
$k = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{8E5C7A41-3B9D-4F26-A1C0-6D2B94E7F315}_is1"
$docs = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "PDF Annotator"
$hadWs = Test-Path $docs
$bad = 0
function Say($ok, $t) { if (-not $ok) { $script:bad++ }; "{0} {1}" -f ($(if ($ok) { "OK  " } else { "FAIL" }), $t) }

$p = Start-Process $setup.FullName -ArgumentList "/VERYSILENT", "/CURRENTUSER", "/NORESTART", "/TASKS=assoc", "/DIR=$d" -Wait -PassThru
Say ($p.ExitCode -eq 0) "kurulum çıkış kodu $($p.ExitCode)"
Say (Test-Path $k) "Program Ekle/Kaldır girdisi (HKCU Uninstall)"
if (Test-Path $k) { $v = Get-ItemProperty $k; Say ($v.DisplayVersion -match '^\d+\.\d+\.\d+') "sürüm: $($v.DisplayName) $($v.DisplayVersion)" }
Say (Test-Path "$d\PDF Annotator.exe") "exe kuruldu"
Say (Test-Path "HKCU:\Software\Classes\PDFAnnotator.Belge") "Birlikte aç kaydı"

$env:PATH = "C:\Windows\System32;C:\Windows"       # Python PATH'te yok
$p = Start-Process "$d\PDF Annotator.exe" -ArgumentList "--selftest" -Wait -PassThru
Say ($p.ExitCode -eq 0) "--selftest çıkış kodu $($p.ExitCode)"

$u = (Get-ItemProperty $k).UninstallString.Trim('"')
$p = Start-Process $u -ArgumentList "/VERYSILENT", "/NORESTART" -Wait -PassThru
Say ($p.ExitCode -eq 0) "kaldırma çıkış kodu $($p.ExitCode)"
Start-Sleep 3
Say (-not (Test-Path "$d\PDF Annotator.exe")) "uygulama dosyaları silindi"
Say (-not (Test-Path $k)) "Uninstall girdisi silindi"
Say (-not (Test-Path "HKCU:\Software\Classes\PDFAnnotator.Belge")) "Birlikte aç kaydı silindi"
Say ((Test-Path $docs) -eq $hadWs) "kullanıcı çalışma klasörüne dokunulmadı"
"OZET: $bad hata"
exit $bad
