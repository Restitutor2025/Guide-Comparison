#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef LibreOfficeMsi
  #error LibreOfficeMsi must point to the downloaded x64 LibreOffice MSI.
#endif

#define AppName "Guide Comparison"
#define AppExeName "GuideComparison.exe"

[Setup]
AppId={{E49C78D7-26E2-43D8-B660-A7225DF39BB7}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Restitutor
DefaultDirName={autopf}\Guide Comparison
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=GuideComparisonSetup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExeName}
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: checkedonce

[Files]
Source: "..\dist\GuideComparison\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#LibreOfficeMsi}"; DestDir: "{tmp}"; DestName: "LibreOffice.msi"; Flags: deleteafterinstall; Check: LibreOfficeMissing

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{sys}\msiexec.exe"; Parameters: "/i ""{tmp}\LibreOffice.msi"" /qn /norestart"; StatusMsg: "Installing the DOCX rendering engine..."; Flags: waituntilterminated; Check: LibreOfficeMissing
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
function LibreOfficeMissing: Boolean;
begin
  Result :=
    (not FileExists(ExpandConstant('{autopf}\LibreOffice\program\soffice.exe'))) and
    (not FileExists(ExpandConstant('{autopf32}\LibreOffice\program\soffice.exe')));
end;
