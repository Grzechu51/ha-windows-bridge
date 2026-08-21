#define MyAppName "HA Windows Bridge"
#ifndef MyAppVersion
#define MyAppVersion "1.0.0"
#endif
#define MyAppPublisher "HA Windows Bridge"
#define MyAppExeName "HA Windows Bridge.exe"
#define MyShortcutIconName "shortcut-" + MyAppVersion + ".ico"
#ifndef MyAppMutex
#define MyAppMutex "Local\HAWindowsBridge"
#endif
#ifndef MyOutputBaseFilename
#define MyOutputBaseFilename "HA-Windows-Bridge-Setup-" + MyAppVersion
#endif

[Setup]
AppId={{E9D9E11F-76AB-4F75-A18E-29DB64D37E36}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
VersionInfoVersion={#MyAppVersion}.0
VersionInfoTextVersion={#MyAppVersion}
VersionInfoDescription={#MyAppName} Installer
VersionInfoCompany={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\HA Windows Bridge
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename={#MyOutputBaseFilename}
SetupIconFile=..\assets\icon.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
AppMutex={#MyAppMutex}
LicenseFile=..\LICENSE
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\_internal\assets\{#MyShortcutIconName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"

[Files]
Source: "..\dist\HA Windows Bridge\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\assets\icon.ico"; DestDir: "{app}\_internal\assets"; DestName: "{#MyShortcutIconName}"; Flags: ignoreversion

[InstallDelete]
Type: files; Name: "{app}\HAWindowsBridge-*.ico"
Type: files; Name: "{app}\_internal\assets\shortcut-*.ico"

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\_internal\assets\{#MyShortcutIconName}"; IconIndex: 0
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\_internal\assets\{#MyShortcutIconName}"; IconIndex: 0; Tasks: desktopicon
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\_internal\assets\{#MyShortcutIconName}"; IconIndex: 0; Check: ExistingDesktopShortcut

[Tasks]
Name: "desktopicon"; Description: "Utwórz skrót na pulpicie"; GroupDescription: "Dodatkowe skróty:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Uruchom {#MyAppName}"; Flags: nowait postinstall skipifsilent

[Code]
function ExistingDesktopShortcut(): Boolean;
begin
  Result := FileExists(ExpandConstant('{autodesktop}\{#MyAppName}.lnk'));
end;
