@echo off
REM KEIS public-purchase grabber - auto-start launcher.
REM Double-click to run. Put a shortcut in the Startup folder to run at boot.
REM Keep this file ASCII-only: Windows .bat mangles non-ASCII text.
chcp 65001 >nul
cd /d "%~dp0"

:loop
echo starting grab.py --watch --apply
python grab.py --watch --apply
echo grab.py exited, restarting in 60s... >> watch.log
timeout /t 60 /nobreak >nul
goto loop
