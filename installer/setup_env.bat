@echo off
setlocal

set APP_DIR=%~dp0..

echo Checking uv...
where uv >nul 2>nul
if errorlevel 1 (
    echo ERROR: uv is required but was not found in PATH.
    echo Install uv first, then run this setup again.
    exit /b 1
)

if not exist "%APP_DIR%\pyproject.toml" (
    echo ERROR: Missing pyproject.toml in %APP_DIR%.
    exit /b 1
)

echo Syncing Python environment with uv...
uv sync --no-dev
if errorlevel 1 (
    echo ERROR: Failed to sync dependencies with uv.
    exit /b 1
)

echo Installing Playwright Chromium browser...
uv run playwright install chromium
if errorlevel 1 (
    echo ERROR: Failed to install Playwright Chromium.
    exit /b 1
)

echo.
echo Setup complete. Job Hunter Agent is ready.
