; Job Hunter Agent — Windows Installer
;
; Prerequisites:
;   Python 3.12 or later must be installed and available in PATH.
;   Download from https://www.python.org/downloads/ — check "Add Python to PATH".
;
; To build this installer:
;   1. Install Inno Setup 6: https://jrsoftware.org/isdl.php
;   2. Open this file in the Inno Setup Compiler and press Build (F9).
;      Or from the command line:
;        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\setup.iss
;   Output: installer\dist\JobHunterAgent-Setup.exe
;
; Install layout after running this installer:
;
;   %LOCALAPPDATA%\Programs\JobHunterAgent\         (app install root)
;     job_hunter_agent\                             Python package
;     desktop\launcher.py                           Tray launcher
;     templates\                                    HTML/CSS/JS assets
;     data\knowledge\*.json                         Seeds for upgrade_knowledge_from_dir()
;     data\config\global_settings.json              Seed (read by REPO_ROOT path in bootstrap)
;     data\defaults\user_settings.json              Seed
;     data\signals\*.json                           Seeds
;     .venv\                                        Python virtual environment (created by setup_env.bat)
;     installer\setup_env.bat                       Dep-install utility
;     pyproject.toml
;     uv.lock
;
;   %APPDATA%\JobHunterAgent\data\                  User data root (JOB_HUNTER_DATA_DIR)
;     config\global_settings.json                   Direct-read by global_settings_defaults.py
;     defaults\user_settings.json                   Direct-read by user_settings.py
;     knowledge\*.json                              Direct-read by salary.py, locations.py, etc.
;     signals\*.json                                Signal registry seeds
;     users\                                        Per-user workspace data
;     runtime\                                      Scrape artefacts, LLM cache
;   %APPDATA%\JobHunterAgent\output\                Logs and artefacts (JOB_HUNTER_OUTPUT_DIR)
;   %APPDATA%\JobHunterAgent\app.db                 SQLite database (JOB_HUNTER_DB_PATH)
;
;   Start Menu: Job Hunter Agent
;   Desktop shortcut (optional)
;   Startup entry (optional)

[Setup]
AppName=Job Hunter Agent
AppVersion=1.0
AppPublisher=Job Hunter Agent
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\JobHunterAgent
DefaultGroupName=Job Hunter Agent
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=JobHunterAgent-Setup
SetupIconFile=job_hunter_agent.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=Job Hunter Agent

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"
Name: "startupitem"; Description: "Launch &automatically at Windows startup"; GroupDescription: "Startup:"; Flags: unchecked

; ── App binaries and static assets → %LOCALAPPDATA%\Programs\JobHunterAgent ──
[Files]
Source: "job_hunter_agent.ico";  DestDir: "{app}";                  Flags: ignoreversion
Source: "..\job_hunter_agent\*"; DestDir: "{app}\job_hunter_agent"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "__pycache__,*.pyc,*.pyo"
Source: "..\desktop\*";         DestDir: "{app}\desktop";          Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\templates\*";       DestDir: "{app}\templates";        Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\pyproject.toml";    DestDir: "{app}";                  Flags: ignoreversion
Source: "..\uv.lock";           DestDir: "{app}";                  Flags: ignoreversion skipifsourcedoesntexist
Source: "setup_env.bat";        DestDir: "{app}\installer";        Flags: ignoreversion

; Knowledge / config seeds in the app dir (used by upgrade_knowledge_from_dir and bootstrap)
Source: "..\data\config\*";    DestDir: "{app}\data\config";    Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\data\defaults\*";  DestDir: "{app}\data\defaults";  Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\data\knowledge\*"; DestDir: "{app}\data\knowledge"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\data\signals\*";   DestDir: "{app}\data\signals";   Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.lock"

; ── User data seeds → %APPDATA%\JobHunterAgent\data ──
; Always overwrite — user customisations live in the DB, not in these files.
Source: "..\data\config\*";    DestDir: "{userappdata}\JobHunterAgent\data\config";    Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\data\defaults\*";  DestDir: "{userappdata}\JobHunterAgent\data\defaults";  Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\data\knowledge\*"; DestDir: "{userappdata}\JobHunterAgent\data\knowledge"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\data\signals\*";   DestDir: "{userappdata}\JobHunterAgent\data\signals";   Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.lock"

; ── Runtime dirs (empty, created so the app can write on first run) ──
[Dirs]
Name: "{userappdata}\JobHunterAgent\data\users"
Name: "{userappdata}\JobHunterAgent\data\runtime"
Name: "{userappdata}\JobHunterAgent\output"

; ── Shortcuts ──
[Icons]
Name: "{group}\Job Hunter Agent";           Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\desktop\launcher.py"""; WorkingDir: "{app}"; IconFilename: "{app}\job_hunter_agent.ico"
Name: "{group}\Uninstall Job Hunter Agent"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Job Hunter Agent";     Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\desktop\launcher.py"""; WorkingDir: "{app}"; IconFilename: "{app}\job_hunter_agent.ico"; Tasks: desktopicon
Name: "{userstartup}\Job Hunter Agent";     Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\desktop\launcher.py"""; WorkingDir: "{app}"; IconFilename: "{app}\job_hunter_agent.ico"; Tasks: startupitem

; ── Post-install: set up venv, install deps, install Playwright Chromium ──
[Run]
Filename: "{app}\installer\setup_env.bat"; WorkingDir: "{app}"; StatusMsg: "Installing Python dependencies and Playwright Chromium (this takes a few minutes)..."; Flags: runhidden waituntilterminated
Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: """{app}\desktop\launcher.py"""; WorkingDir: "{app}"; Description: "Launch Job Hunter Agent now"; Flags: nowait postinstall skipifsilent

; ── Uninstall cleanup ──
[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{userappdata}\JobHunterAgent\data\runtime"
Type: filesandordirs; Name: "{userappdata}\JobHunterAgent\output"

[Code]
function IsPythonAvailable(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\cmd.exe'), '/C python --version',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode)
    and (ResultCode = 0);
end;

function InitializeSetup(): Boolean;
begin
  if not IsPythonAvailable() then
  begin
    MsgBox(
      'Python 3.12 or later is required but was not found in PATH.' + #13#10 + #13#10 +
      'Download it from https://www.python.org/downloads/ and ensure' + #13#10 +
      '"Add Python to PATH" is checked during installation, then run this installer again.',
      mbError, MB_OK
    );
    Result := False;
  end
  else
    Result := True;
end;
