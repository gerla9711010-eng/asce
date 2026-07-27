@echo off
REM Double-click this to check for missed listings. Keep ASCII-only.
chcp 65001 >nul
cd /d "%~dp0"
python check_missed.py
echo.
pause
