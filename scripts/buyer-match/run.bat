@echo off
cd /d "%~dp0"
rem Auto-update this folder to GitHub main before running (2026-10-19: the office PC ran old code
rem and corrupted the shared OneDrive state). Works on any branch. Skips if there are local
rem uncommitted edits or no network. run.bat itself is excluded (editing a running .bat breaks cmd).
git fetch -q origin main 2>nul
if errorlevel 1 goto run
git diff --quiet -- . 2>nul
if errorlevel 1 goto run
git checkout origin/main -- . ":!run.bat" 2>nul
:run
start "" pythonw gui.py
