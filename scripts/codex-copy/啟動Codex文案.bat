@echo off
cd /d "%~dp0"
title Codex 文案服務
echo.
echo   啟動中，會做三件事：
echo     1. 開服務
echo     2. 開 Cloudflare 通道，拿一個對外網址
echo     3. 把網址自動寫回 n8n
echo.
echo   看到「已把 n8n 產文案指向 https://...」就成功了。
echo   這個視窗要一直開著。關掉它，n8n 會自動改回 Gemini。
echo.
echo ================================================
python server.py --tunnel --port 8787
echo ================================================
echo.
echo   服務已停止，n8n 應該已自動改回 Gemini。
echo   若上面顯示沒改回去，請執行：python server.py --revert
echo.
pause
