@echo off
rem ============================================================================
rem  claude-preview - the TERMINAL (TUI) version. Most people want start.bat
rem  (the web IDE). Use this for a no-browser, split-screen terminal experience.
rem  Optional starting folder:  start-terminal.bat C:\path\to\project
rem ============================================================================
setlocal
cd /d "%~dp0"
title claude-preview (terminal)

where python >nul 2>&1
if errorlevel 1 (
    echo [claude-preview] Python 3.10+ is required: https://www.python.org/downloads/
    pause
    exit /b 1
)

python -c "import textual, rich, claude_agent_sdk" >nul 2>&1
if errorlevel 1 (
    echo [claude-preview] Installing dependencies...
    python -m pip install --disable-pip-version-check -r "%~dp0requirements.txt"
    if errorlevel 1 ( echo Dependency install failed. & pause & exit /b 1 )
)

where claude >nul 2>&1
if errorlevel 1 (
    where npm >nul 2>&1
    if errorlevel 1 (
        echo [claude-preview] Claude Code needs Node.js. Install https://nodejs.org then re-run.
        pause
        exit /b 1
    )
    echo [claude-preview] Installing Claude Code...
    call npm install -g @anthropic-ai/claude-code
)

set "TOKDIR=%LOCALAPPDATA%\claude-preview"
set "TOKFILE=%TOKDIR%\auth.token"
if not exist "%TOKDIR%" mkdir "%TOKDIR%"
set "CLAUDE_CODE_OAUTH_TOKEN="
if exist "%TOKFILE%" set /p CLAUDE_CODE_OAUTH_TOKEN=<"%TOKFILE%"
if not "%CLAUDE_CODE_OAUTH_TOKEN%"=="" goto run

echo.
echo  First-time setup - one-time Claude login ^(uses your subscription^).
echo  Saved to %TOKFILE% so you're never asked again.
echo.
set "HAVETOK="
set /p HAVETOK=Do you already have a Claude auth token? [y/N]:
if /I "%HAVETOK%"=="y" goto asktoken
echo Generating one - sign in in the browser, then copy the token it prints.
call claude setup-token

:asktoken
set "CLAUDE_CODE_OAUTH_TOKEN="
set /p CLAUDE_CODE_OAUTH_TOKEN=Paste your Claude auth token here:
if "%CLAUDE_CODE_OAUTH_TOKEN%"=="" ( echo No token entered. & pause & exit /b 1 )
> "%TOKFILE%" echo %CLAUDE_CODE_OAUTH_TOKEN%
echo Token saved.

:run
python "%~dp0claude_preview.py" %*
endlocal
