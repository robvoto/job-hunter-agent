; Job Hunter Agent — Windows Installer
;
; Fully self-contained: no Python or uv needs to be pre-installed on the
; client machine. The installer bundles its own private Python runtime.
;
; To build this installer:
;   1. Install Inno Setup 6: https://jrsoftware.org/isdl.php
;   2. Prepare the bundled runtime once (and whenever the pinned version in
;      prepare_python.ps1 changes):
;        powershell -ExecutionPolicy Bypass -File installer\prepare_python.ps1
;      This downloads Python's official embeddable distribution into
;      installer\pyembed\ and bootstraps pip + uv into it. Not committed to
;      git — regenerate it locally before building.
;   3. Open this file in the Inno Setup Compiler and press Build (F9).
;      Or from the command line:
;        "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer\setup.iss
;   Output: installer\dist\JobHunterAgent-Setup.exe
;
; Install layout after running this installer:
;
;   %LOCALAPPDATA%\Programs\JobHunterAgent\         (app install root; per-user install)
;     job_hunter_agent\*.pyc                        Bytecode-only Python package
;     desktop\launcher.py                           Bootstrap tray launcher
;     templates\                                    HTML/CSS/JS assets
;     data\knowledge\*.json                         Seeds for upgrade_knowledge_from_dir()
;     data\config\global_settings.json              Seed (read by REPO_ROOT path in bootstrap)
;     data\defaults\user_settings.json              Seed
;     data\signals\*.json                           Seeds
;     python\                                       Bundled embeddable Python + uv (from prepare_python.ps1);
;                                                    the [Run] steps below install app deps + Playwright into it
;     installer\launcher.vbs                        Hidden desktop launcher shim
;     pyproject.toml                                Project metadata used by uv launch
;     uv.lock                                       Locked dependency set used by uv launch
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
UsePreviousAppDir=no
DisableDirPage=yes
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
Source: "pyembed\*";            DestDir: "{app}\python";           Flags: ignoreversion recursesubdirs createallsubdirs
Source: "launcher.vbs";         DestDir: "{app}\installer";        Flags: ignoreversion

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
Name: "{userappdata}\JobHunterAgent\data\config"
Name: "{userappdata}\JobHunterAgent\data\users"
Name: "{userappdata}\JobHunterAgent\data\runtime"
Name: "{userappdata}\JobHunterAgent\output"

; ── Shortcuts ──
[Icons]
Name: "{group}\Job Hunter Agent";           Filename: "{sys}\wscript.exe"; Parameters: """{app}\installer\launcher.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\job_hunter_agent.ico"
Name: "{group}\Uninstall Job Hunter Agent"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Job Hunter Agent";     Filename: "{sys}\wscript.exe"; Parameters: """{app}\installer\launcher.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\job_hunter_agent.ico"; Tasks: desktopicon
Name: "{userstartup}\Job Hunter Agent";     Filename: "{sys}\wscript.exe"; Parameters: """{app}\installer\launcher.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\job_hunter_agent.ico"; Tasks: startupitem

; ── Post-install: install app deps + Playwright into the bundled runtime ──
; Each step below runs hidden but shows its own StatusMsg on Inno's own wizard
; page, so progress is visible without popping a separate console window.
[Run]
Filename: "{app}\python\python.exe"; Parameters: "-m uv pip install -r pyproject.toml --python ""{app}\python\python.exe"""; WorkingDir: "{app}"; StatusMsg: "Installing Python dependencies..."; Flags: runhidden waituntilterminated
Filename: "{app}\python\python.exe"; Parameters: "-m playwright install chromium"; WorkingDir: "{app}"; StatusMsg: "Installing Playwright Chromium browser..."; Flags: runhidden waituntilterminated
Filename: "{app}\python\python.exe"; Parameters: "-c ""from pathlib import Path; import py_compile; root = Path('job_hunter_agent'); files = list(root.rglob('*.py')); [py_compile.compile(str(p), cfile=str(p.with_suffix('.pyc')), dfile=str(p), doraise=True) for p in files]; [p.unlink() for p in files]"""; WorkingDir: "{app}"; StatusMsg: "Finalizing app files..."; Flags: runhidden waituntilterminated
Filename: "{sys}\wscript.exe"; Parameters: """{app}\installer\launcher.vbs"""; WorkingDir: "{app}"; Description: "Launch Job Hunter Agent now"; Flags: nowait postinstall skipifsilent

; ── Uninstall cleanup ──
[UninstallDelete]
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{userappdata}\JobHunterAgent\data\runtime"
Type: filesandordirs; Name: "{userappdata}\JobHunterAgent\output"

[Code]
var
  WorkspaceExportPage: TInputDirWizardPage;
  WorkspaceExportDir: string;

procedure InitializeWizard();
begin
  WorkspaceExportDir := ExpandConstant('{userdocs}\Job Hunter Workspace');
  WorkspaceExportPage := CreateInputDirPage(
    wpSelectDir,
    'Workspace export folder',
    'Choose where Telegram exports should be written.',
    'Job Hunter writes the merged and fresh job lists to this folder while the desktop app is open.',
    False,
    ''
  );
  WorkspaceExportPage.Add('Workspace export folder:');
  WorkspaceExportPage.Values[0] := WorkspaceExportDir;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = WorkspaceExportPage.ID then
  begin
    WorkspaceExportDir := Trim(WorkspaceExportPage.Values[0]);
    if WorkspaceExportDir = '' then
    begin
      MsgBox('Please choose an export folder.', mbError, MB_OK);
      Result := False;
      exit;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ConfigDir: string;
  ConfigPath: string;
  JsonText: string;
  EscapedDir: string;
begin
  if CurStep = ssPostInstall then
  begin
    ConfigDir := ExpandConstant('{userappdata}\JobHunterAgent\data\config');
    ForceDirectories(ConfigDir);
    ConfigPath := ConfigDir + '\desktop.json';
    EscapedDir := WorkspaceExportDir;
    StringChangeEx(EscapedDir, '\', '\\', True);
    JsonText :=
      '{' + #13#10 +
      '  "workspace_export_dir": "' + EscapedDir + '"' + #13#10 +
      '}' + #13#10;
    if not SaveStringToFile(ConfigPath, JsonText, False) then
      MsgBox('Could not save desktop settings to ' + ConfigPath, mbError, MB_OK);
  end;
end;
