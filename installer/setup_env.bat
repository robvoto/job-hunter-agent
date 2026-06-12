@echo off
setlocal

set APP_DIR=%~dp0..

echo Creating Python virtual environment...
python -m venv "%APP_DIR%\.venv"
if errorlevel 1 (
    echo ERROR: Failed to create virtual environment.
    echo Ensure Python 3.12 or later is installed and available in PATH.
    exit /b 1
)

echo Installing dependencies...
"%APP_DIR%\.venv\Scripts\pip.exe" install --quiet -r "%APP_DIR%\requirements.txt"
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    exit /b 1
)

echo Installing Playwright Chromium browser...
"%APP_DIR%\.venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 (
    echo ERROR: Failed to install Playwright Chromium.
    exit /b 1
)

echo.
echo Setup complete. Job Hunter Agent is ready.
