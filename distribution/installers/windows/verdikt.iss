; Verdikt — Inno Setup 6
; Build:
;   1. cd distribution
;   2. pip install pyinstaller
;   3. pyinstaller --onefile --windowed --name VerdiktTray   tray/__main__.py
;   4. pyinstaller --onefile --windowed --name VerdiktWizard wizard/__main__.py
;   5. iscc installers\windows\verdikt.iss

#define MyAppName    "Verdikt"
#define MyAppVersion "1.0"
#define MyAppURL     "https://github.com/verdikt/verdikt"
#define MyAppExe     "VerdiktWizard.exe"

[Setup]
AppId={{B3C7F2E1-D4A5-4B6C-9F8E-012345678901}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputBaseFilename=VerdiktSetup
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\assets\icon.ico
PrivilegesRequired=lowest
MinVersion=10.0.17763
ArchitecturesInstallIn64BitMode=x64

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\..\dist\VerdiktTray.exe";   DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\dist\VerdiktWizard.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\compose.*.yml";          DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\assets\*";               DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\Verdikt Setup Wizard";                      Filename: "{app}\VerdiktWizard.exe"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}";        Filename: "{uninstallexe}"
Name: "{commondesktop}\Verdikt";                           Filename: "{app}\VerdiktWizard.exe"; Tasks: desktopicon
Name: "{userstartup}\Verdikt Tray";                        Filename: "{app}\VerdiktTray.exe";   Tasks: autostart

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "autostart";   Description: "Start Verdikt tray icon at login"; GroupDescription: "Startup"

[Run]
Filename: "{app}\VerdiktWizard.exe"; Description: "Run Verdikt Setup Wizard"; Flags: postinstall nowait skipifsilent

[Code]
function DockerRunning(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\cmd.exe'), '/c docker version >nul 2>&1',
                 '', SW_HIDE, ewWaitUntilTerminated, ResultCode)
            and (ResultCode = 0);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if not DockerRunning() then
      MsgBox(
        'Docker Desktop is not running.' + #13#10#13#10 +
        'Please install Docker Desktop from https://www.docker.com/products/docker-desktop' + #13#10 +
        'and make sure it is started before running the Verdikt Setup Wizard.',
        mbInformation, MB_OK
      );
  end;
end;
