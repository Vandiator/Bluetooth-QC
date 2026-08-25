[Setup]
; App Information
AppName=Studds QC Inspection
AppVersion=1.0.0
AppPublisher=Studds Accessories Ltd.
; Changed to Local AppData so it doesn't require Admin rights
DefaultDirName={localappdata}\StuddsQC
DefaultGroupName=Studds QC

; Output Settings
OutputDir=installer_output
OutputBaseFilename=StuddsQC_Setup_v1.0_NoAdmin
SetupIconFile=compiler:SetupClassicIcon.ico
Compression=lzma2
SolidCompression=yes

; THIS IS THE MAGIC LINE: Tells Windows NOT to ask for Admin Passwords
PrivilegesRequired=lowest

ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; The main Python backend / webview executable
Source: "dist\StuddsQC.exe"; DestDir: "{app}"; Flags: ignoreversion

; The critical HTML frontend
Source: "studds_qc_inspection.html"; DestDir: "{app}"; Flags: ignoreversion


; The database configuration
Source: "db_config.json"; DestDir: "{app}"; Flags: ignoreversion

; ICON FILE:
Source: "icon - file.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Start Menu Shortcut
Name: "{group}\Studds QC Inspection"; Filename: "{app}\StuddsQC.exe"; IconFilename: "{app}\icon - file.ico"
; Desktop Shortcut
Name: "{autodesktop}\Studds QC Inspection"; Filename: "{app}\StuddsQC.exe"; Tasks: desktopicon; IconFilename: "{app}\icon - file.ico"

[Run]
; Launch automatically after installation
Filename: "{app}\StuddsQC.exe"; Description: "Launch Studds QC Inspection"; Flags: nowait postinstall skipifsilent