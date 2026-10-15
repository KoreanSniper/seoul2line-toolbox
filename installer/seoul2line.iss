#define AppName "seoul2line Toolbox"
#ifndef AppVersion
  #error AppVersion must be passed by installer/build.ps1
#endif
#define AppPublisher "seoul2line"
#define AppExeName "seoul2line Toolbox.exe"

[Setup]
AppId={{B6E6A1E4-8A54-4EA9-B89D-1B2B6D32A91F}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://github.com/KoreanSniper/seoul2line-toolbox
AppUpdatesURL=https://github.com/KoreanSniper/seoul2line-toolbox/releases/latest
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\release
OutputBaseFilename=seoul2line-toolbox-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExeName}
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
AppMutex=Local\seoul2lineToolboxApp
SetupMutex=Local\seoul2lineToolboxSetup
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes

[Files]
Source: "..\dist\seoul2line Toolbox\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "..\run.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\update_installer.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "download_latest.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
