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
if errorlevel 1 goto already
echo ================================================
echo.
echo   服務已停止，n8n 應該已自動改回 Gemini。
echo   若上面顯示沒改回去，請執行：python server.py --revert
echo.
pause
exit /b

:already
echo ================================================
echo.
echo   這不是壞掉。開機的時候已經自動啟動一份了，一次只能跑一份。
echo   這個視窗直接關掉就好，服務正常在跑。
echo.
echo   真的要重開：工作管理員砍掉 python 和 pythonw，再點一次這個檔案。
echo.
pause
