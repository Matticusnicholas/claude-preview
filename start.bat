@echo off
rem ============================================================================
rem  claude-preview - one-click launcher for the Cursor-style web IDE.
rem  First run: installs deps + Claude Code, asks for your Claude token once.
rem  Every run after: opens the editor in your browser.
rem  Optional starting folder:  start.bat C:\path\to\project
rem ============================================================================
setlocal
cd /d "%~dp0"
title claude-preview

rem --- Python --------------------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo [claude-preview] Python 3.10+ is required.
    echo   Install from https://www.python.org/downloads/  ^(check "Add to PATH"^) and re-run.
    pause
    exit /b 1
)

rem --- Dependencies --------------------------------------------------------
python -c "import fastapi, uvicorn, claude_agent_sdk" >nul 2>&1
if errorlevel 1 (
    echo [claude-preview] Installing dependencies ^(first run only^)...
    python -m pip install --disable-pip-version-check -r "%~dp0webapp\requirements.txt"
    if errorlevel 1 ( echo Dependency install failed - see above. & pause & exit /b 1 )
)

rem --- Claude Code CLI -----------------------------------------------------
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

rem --- Auth token (saved locally, asked only once) -------------------------
set "TOKDIR=%LOCALAPPDATA%\claude-preview"
set "TOKFILE=%TOKDIR%\auth.token"
if not exist "%TOKDIR%" mkdir "%TOKDIR%"
set "CLAUDE_CODE_OAUTH_TOKEN="
if exist "%TOKFILE%" set /p CLAUDE_CODE_OAUTH_TOKEN=<"%TOKFILE%"
if not "%CLAUDE_CODE_OAUTH_TOKEN%"=="" goto run

echo.
echo ============================================================================
echo  First-time setup - one-time Claude login ^(uses your subscription^).
echo  Saved to %TOKFILE% so you're never asked again on this machine.
echo ============================================================================
echo.
set "HAVETOK="
set /p HAVETOK=Do you already have a Claude auth token? [y/N]:
if /I "%HAVETOK%"=="y" goto asktoken
echo.
echo Generating a token now - a browser opens, sign in, then copy the token
echo it prints ^(starts with sk-ant-oat...^).
echo.
call claude setup-token

:asktoken
echo.
set "CLAUDE_CODE_OAUTH_TOKEN="
set /p CLAUDE_CODE_OAUTH_TOKEN=Paste your Claude auth token here:
if "%CLAUDE_CODE_OAUTH_TOKEN%"=="" ( echo No token entered - exiting. & pause & exit /b 1 )
> "%TOKFILE%" echo %CLAUDE_CODE_OAUTH_TOKEN%
echo Token saved. You're set - this won't be asked again.

:run
echo.
echo  claude-preview is starting at  http://127.0.0.1:8765
echo  ^(leave this window open; close it to stop the app^)
echo.
start "" http://127.0.0.1:8765
python "%~dp0webapp\server.py" %*
endlocal
