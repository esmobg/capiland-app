; Инсталатор на Kapilands Таймер — Inno Setup 6.
;
; Сглобява се с build_installer.bat (или: ISCC.exe installer\kapilands.iss).
; Изисква вече готов dist\Kapilands-Taymer.exe (build_exe.bat).
;
; Инсталира се само за текущия потребител — без прозорец за администратор
; (UAC), който е на защитен екран и екранният четец може да не го прочете.

#define AppName "Kapilands Таймер"
#define AppVersion "2.0"
#define AppExe "Kapilands-Taymer.exe"

[Setup]
AppId={{6E558729-A64F-4E92-8E54-CAF34CB4C37E}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=esmobg
AppPublisherURL=https://github.com/esmobg/capiland-app
AppSupportURL=https://github.com/esmobg/capiland-app/issues
AppUpdatesURL=https://github.com/esmobg/capiland-app/releases
VersionInfoVersion=2.0.0.0
VersionInfoProductVersion=2.0.0.0
VersionInfoDescription={#AppName} — инсталатор

PrivilegesRequired=lowest
DefaultDirName={autopf}\KapilandsTimer
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; Ако приложението работи, инсталаторът го затваря преди обновяване.
AppMutex=Global\KapilandsTimerSingleInstance,KapilandsTimerSingleInstance
CloseApplications=yes
RestartApplications=no

OutputDir=..\dist
OutputBaseFilename=Kapilands-Taymer-2.0-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName={#AppName} {#AppVersion}
UninstallDisplayIcon={app}\{#AppExe}

[Languages]
Name: "bg"; MessagesFile: "compiler:Languages\Bulgarian.isl"

[Tasks]
Name: "desktopicon"; Description: "Пряк път на работния плот"; GroupDescription: "Преки пътища:"; Flags: unchecked
Name: "autostart"; Description: "Стартирай заедно с Windows"; GroupDescription: "Стартиране:"; Flags: unchecked

[Files]
Source: "..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; DestName: "Упътване.md"; Flags: ignoreversion
Source: "..\docs\ACCESSIBILITY.md"; DestDir: "{app}"; DestName: "Достъпност.md"; Flags: ignoreversion
Source: "..\vendor\nvda\license.txt"; DestDir: "{app}\licenses"; DestName: "nvdaControllerClient-LGPL-2.1.txt"; Flags: ignoreversion
Source: "..\vendor\nvda\README.md"; DestDir: "{app}\licenses"; DestName: "nvdaControllerClient.md"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; Comment: "Таймери за Kapilands с говор през NVDA и JAWS"
Name: "{group}\Упътване"; Filename: "{app}\Упътване.md"
Name: "{group}\Деинсталиране на {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon
; Същото име като при „Стартирай заедно с Windows“ в Настройки на приложението.
Name: "{userstartup}\Kapilands Таймер"; Filename: "{app}\{#AppExe}"; Tasks: autostart

[Run]
Filename: "{app}\{#AppExe}"; Description: "Стартирай {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Пряк път, създаден от Настройки в самото приложение.
Type: files; Name: "{userstartup}\Kapilands Таймер.lnk"

; Данните (таймери, компании, история) остават в %APPDATA%\KapilandsTimer —
; деинсталирането не ги трие, за да не се загубят при преинсталиране.
