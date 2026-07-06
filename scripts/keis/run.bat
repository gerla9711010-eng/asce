@echo off
REM KEIS 公買搶單 — 開機自動監控啟動檔
REM 雙擊即可跑；放進「啟動」資料夾就會開機自動執行。
REM cd 到這個 .bat 所在的資料夾（grab.py 和 .env 要在同一層）
cd /d "%~dp0"

:loop
echo [%date% %time%] 啟動 grab.py --watch --apply
python grab.py --watch --apply
echo [%date% %time%] grab.py 結束（可能斷網/當機），60 秒後自動重啟... >> watch.log
timeout /t 60 /nobreak >nul
goto loop
