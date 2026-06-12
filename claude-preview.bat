@echo off
rem Launcher for claude-preview. Run from anywhere; add this folder to PATH if you like.
rem First launch opens the Claude browser login (needs the `ant` CLI); after that
rem the saved session is reused automatically.

python "%~dp0claude_preview.py" %*
