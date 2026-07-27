@echo off
title open_real_chrome (buyer-match, port 9223)

echo.
echo ==========================================
echo  open_real_chrome.bat（買方配案用）
echo  獨立 profile + CDP port 9223
echo ==========================================
echo.
echo [WARN] 執行前請先關掉所有 Chrome 視窗（含工作列看不到、但工作管理員裡還有的
echo        背景 chrome.exe），不然 Windows ProcessSingleton 會把這次啟動併進
echo        既有 chrome.exe，9223 這個 port 就不會生效。
echo.

set "CHROME_A=C:\Program Files\Google\Chrome\Application\chrome.exe"
set "CHROME_B=C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
set "CHROME_C=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
set "DEBUG_ARGS=--remote-debugging-port=9223 --remote-allow-origins=* --user-data-dir=%~dp0chrome_profile"
set "URLS=https://is.ycut.com.tw/is/case/search/all-case"

set "CHROME="
if exist "%CHROME_A%" set "CHROME=%CHROME_A%"
if not defined CHROME if exist "%CHROME_B%" set "CHROME=%CHROME_B%"
if not defined CHROME if exist "%CHROME_C%" set "CHROME=%CHROME_C%"

if not defined CHROME (
    echo [ERROR] 找不到 chrome.exe：
    echo   %CHROME_A%
    echo   %CHROME_B%
    echo   %CHROME_C%
    pause
    exit /b 1
)

echo 找到 chrome.exe：
echo   %CHROME%
echo.
echo 用獨立 profile 開 Chrome、帶 i智慧搜尋頁...
start "" "%CHROME%" %DEBUG_ARGS% %URLS%
echo.
echo [OK] Chrome 已啟動。
echo.
echo 接下來：
echo   1. 在這個新開的 Chrome 視窗用你自己的帳號登入 i智慧（is.ycut.com.tw）。
echo   2. 登入一次後這個 chrome_profile 資料夾會記住登入態，之後不用再登。
echo   3. 回來跑 buyer_match.py 就可以了。
echo.
echo 如果腳本說連不到 9223：
echo   - 背景還有沒關乾淨的 chrome.exe，工作管理員裡全部砍掉再重跑這支 bat。
echo.
pause
