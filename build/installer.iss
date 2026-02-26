; Inno Setup script for Agent Commander GUI
; Compile with: iscc /DAppVersion=X.Y.Z /DProjectRoot=<path> /DDistDir=<path> /DOutputDir=<path> installer.iss

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

#ifndef ProjectRoot
  #define ProjectRoot ".."
#endif

#ifndef DistDir
  #define DistDir "..\dist\AgentCommander"
#endif

#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

[Setup]
AppId={{B3D8A7F2-9C4E-4A1B-8F6D-2E5C3A7B9D01}
AppName=Agent Commander
AppVersion={#AppVersion}
AppVerName=Agent Commander {#AppVersion}
AppPublisher=Agent Commander contributors
DefaultDirName={localappdata}\AgentCommander
DefaultGroupName=Agent Commander
DisableProgramGroupPage=yes
OutputBaseFilename=AgentCommander_Setup_{#AppVersion}
OutputDir={#OutputDir}
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=Agent Commander
; SetupIconFile={#ProjectRoot}\build\agent_commander.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startmenu"; Description: "Create Start Menu shortcut"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Agent Commander"; Filename: "{app}\AgentCommander.exe"; WorkingDir: "{app}"
Name: "{group}\Uninstall Agent Commander"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Agent Commander"; Filename: "{app}\AgentCommander.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\AgentCommander.exe"; Description: "Launch Agent Commander"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandirs; Name: "{app}\cliproxyapi"
Type: filesandirs; Name: "{app}\_internal"
