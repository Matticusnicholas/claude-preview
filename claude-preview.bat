@echo off
rem Launcher for claude-preview.
rem Needs Claude Code installed and logged in (npm i -g @anthropic-ai/claude-code; claude; /login).
rem Optional: pass a starting folder ->  claude-preview.bat C:\path\to\project

python "%~dp0claude_preview.py" %*
