@echo off
REM KEIS public-purchase grabber - auto-start launcher.
REM Double-click to run. Put a shortcut in the Startup folder to run at boot.
REM Keep this file ASCII-only: Windows .bat mangles non-ASCII text.
chcp 65001 >nul
cd /d "%~dp0"

:loop
echo starting grab.py --watch --apply
python grab.py --watch --apply
echo [%DATE% %TIME%] grab.py exited code=%ERRORLEVEL%, restarting in 60s>> watch.log
timeout /t 60 /nobreak >nul
goto loop

REM ---- editing notes (unreachable on purpose) ----
REM 2026-09-14: when you edit this file, keep every byte up to and including the
REM "python grab.py" line exactly as it is, and only change lines BELOW it.
REM cmd.exe resumes a running .bat by byte offset: shifting the earlier lines while
REM grab.py is still running makes it resume mid-line and silently fall out of the
REM loop - i.e. exactly the 32-hour silent outage this launcher exists to prevent.
