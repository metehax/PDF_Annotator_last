; Inno Setup 6 — build.bat ISCC'yi /DAppVersion=... /DAppId=... ile çağırır (appinfo.py tek kaynak)
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef AppGuid
  #define AppGuid "8E5C7A41-3B9D-4F26-A1C0-6D2B94E7F315"
#endif
#define AppName "PDF Annotator"
#define AppExe "PDF Annotator.exe"

[Setup]
AppId={{{#AppGuid}}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
SetupIconFile=app.ico
OutputDir=dist
OutputBaseFilename=PDF-Annotator-Setup-{#AppVersion}
VersionInfoVersion={#AppVersion}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=yes
WizardStyle=modern
InfoBeforeFile=KURULUM_NOTU.txt

[Languages]
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked
Name: "assoc"; Description: "PDF ve resim dosyaları için ""Birlikte aç"" listesine {#AppName} ekle"; Flags: unchecked

[Files]
Source: "dist\{#AppName}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: "selftest.txt"
; VC++ çalışma zamanı: PyInstaller DLL'leri getirir; yine de gerekirse vc_redist.x64.exe'yi build klasörüne koyun
Source: "vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall skipifsourcedoesntexist

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\PDFAnnotator.Belge"; ValueType: string; ValueData: "PDF İşaretleme Aracı belgesi"; Flags: uninsdeletekey; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\PDFAnnotator.Belge\DefaultIcon"; ValueType: string; ValueData: "{app}\{#AppExe},0"; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\PDFAnnotator.Belge\shell\open\command"; ValueType: string; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.pdf\OpenWithProgids"; ValueType: none; ValueName: "PDFAnnotator.Belge"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.png\OpenWithProgids"; ValueType: none; ValueName: "PDFAnnotator.Belge"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.jpg\OpenWithProgids"; ValueType: none; ValueName: "PDFAnnotator.Belge"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.jpeg\OpenWithProgids"; ValueType: none; ValueName: "PDFAnnotator.Belge"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc

[Run]
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "Visual C++ çalışma zamanı kuruluyor..."; Flags: skipifdoesntexist; Check: NeedVcRedist
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
function NeedVcRedist: Boolean;
begin
  Result := FileExists(ExpandConstant('{tmp}\vc_redist.x64.exe')) and
            not FileExists(ExpandConstant('{sys}\vcruntime140.dll'));
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Ws: String;
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
  begin
    if MsgBox('Ayarlar ve çalışma klasörü (Belgeler\PDF Annotator) de silinsin mi?' + #13#10 +
              'Belgeleriniz silinir; "Hayır" önerilir.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    begin
      Ws := ExpandConstant('{userdocs}\PDF Annotator');
      if DirExists(Ws) then DelTree(Ws, True, True, True);
      RegDeleteKeyIncludingSubkeys(HKCU, 'Software\PDFAnnotator');
    end;
  end;
end;
