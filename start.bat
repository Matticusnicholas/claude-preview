@echo off
rem ============================================================================
rem  claude-preview launcher: sets everything up the first time, then just runs.
rem  - installs Python deps + Claude Code if needed
rem  - asks for your Claude auth token ONCE, saves it to local app data
rem  - reuses that token on every future run
rem  Pass a starting folder if you like:  start.bat C:\path\to\project
rem ============================================================================
setlocal
cd /d "%~dp0"
title claude-preview

rem --- Python ---------------------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo [claude-preview] Python 3.10+ is required.
    echo   Install it from https://www.python.org/downloads/  ^(check "Add to PATH"^) and re-run.
    pause
    exit /b 1
)

rem --- Python dependencies --------------------------------------------------
python -c "import textual, rich, claude_agent_sdk" >nul 2>&1
if errorlevel 1 (
    echo [claude-preview] Installing Python dependencies...
    python -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo [claude-preview] Dependency install failed - see the messages above.
        pause
        exit /b 1
    )
)

rem --- Claude Code CLI ------------------------------------------------------
where claude >nul 2>&1
if errorlevel 1 (
    where npm >nul 2>&1
    if errorlevel 1 (
        echo [claude-preview] Claude Code is required, and Node.js/npm was not found.
        echo   1^) Install Node.js from https://nodejs.org
        echo   2^) Re-run this script ^(it will install Claude Code for you^)
        pause
        exit /b 1
    )
    echo [claude-preview] Installing Claude Code...
    call npm install -g @anthropic-ai/claude-code
)

rem --- Auth token (saved locally, asked only once) --------------------------
set "TOKDIR=%LOCALAPPDATA%\claude-preview"
set "TOKFILE=%TOKDIR%\auth.token"
if not exist "%TOKDIR%" mkdir "%TOKDIR%"

set "CLAUDE_CODE_OAUTH_TOKEN="
if exist "%TOKFILE%" set /p CLAUDE_CODE_OAUTH_TOKEN=<"%TOKFILE%"
if not "%CLAUDE_CODE_OAUTH_TOKEN%"=="" goto run

echo.
echo ============================================================================
echo  First-time setup - one-time Claude login
echo  This uses YOUR Claude subscription. The token is saved to:
echo    %TOKFILE%
echo  so you'll never be asked again on this machine.
echo ============================================================================
echo.
set "HAVETOK="
set /p HAVETOK=Do you already have a Claude auth token? [y/N]:
if /I "%HAVETOK%"=="y" goto asktoken
echo.
echo Generating a token now - a browser window will open. Sign in, approve, then
echo copy the token it prints ^(starts with sk-ant-oat...^).
echo.
call claude setup-token

:asktoken
echo.
set "CLAUDE_CODE_OAUTH_TOKEN="
set /p CLAUDE_CODE_OAUTH_TOKEN=Paste your Claude auth token here:
if "%CLAUDE_CODE_OAUTH_TOKEN%"=="" (
    echo [claude-preview] No token entered - exiting.
    pause
    exit /b 1
)
> "%TOKFILE%" echo %CLAUDE_CODE_OAUTH_TOKEN%
echo [claude-preview] Token saved. You're set - this won't be asked again.
echo.

:run
python "%~dp0claude_preview.py" %*
endlocal
