@echo off
rem ============================================================================
rem  claude-preview WEB launcher: Cursor-style IDE in your browser.
rem  First run installs deps + Claude Code and asks for your token once.
rem  Pass a starting folder:  start-web.bat C:\path\to\project
rem ============================================================================
setlocal
cd /d "%~dp0"
title claude-preview (web)

where python >nul 2>&1
if errorlevel 1 (
    echo [claude-preview] Python 3.10+ is required: https://www.python.org/downloads/  ^(check "Add to PATH"^)
    pause
    exit /b 1
)

python -c "import fastapi, uvicorn, claude_agent_sdk" >nul 2>&1
if errorlevel 1 (
    echo [claude-preview] Installing dependencies...
    python -m pip install --disable-pip-version-check -r "%~dp0webapp\requirements.txt"
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
echo.
echo  Opening http://127.0.0.1:8765 ...
start "" http://127.0.0.1:8765
python "%~dp0webapp\server.py" %*
endlocal
