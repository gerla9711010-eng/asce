@echo off
REM Ad-publishing watchdog - runs once and exits. Register in Task Scheduler (hourly).
REM Keep this file ASCII-only: Windows .bat mangles non-ASCII text.
chcp 65001 >nul
cd /d "%~dp0"
python ad_watchdog.py
