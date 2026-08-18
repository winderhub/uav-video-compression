#define MyAppName "Aerial Video Compressor"
#ifndef MyAppVersion
#define MyAppVersion "0.1.0"
#endif
#define MyAppPublisher "Aerial Data Tools"
#define MyAppExeName "AerialVideoCompressor.exe"
#ifdef Win7Build
#define BuildTarget "win7"
#define MyPlatformName "Windows-7-x64"
#define MyMinVersion "6.1sp1"
#else
#define BuildTarget "modern"
#define MyPlatformName "Windows-x64"
#define MyMinVersion "10.0"
#endif

[Setup]
AppId={{D4435AD0-8A35-45F0-A9E5-2FF8842698C5}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\AerialVideoCompressor
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist\installer
OutputBaseFilename=AerialVideoCompressor-{#MyAppVersion}-{#MyPlatformName}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
MinVersion={#MyMinVersion}

[Files]
Source: "..\..\dist\windows-{#BuildTarget}\AerialVideoCompressor\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标："; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent
