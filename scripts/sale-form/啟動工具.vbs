' 啟動工具.vbs － 雙擊即可無視窗啟動「不動產售屋表自動填寫工具」
' pythonw（不開 console）+ Run 視窗樣式 0（隱藏）＝ 真無視窗。
' 出錯沒畫面可看時，開 output\crash.log（gui_main.py 會把未捕捉例外寫進去）。

Set objShell = CreateObject("WScript.Shell")
Set objFSO   = CreateObject("Scripting.FileSystemObject")

strScriptDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
strPyScript  = strScriptDir & "\gui_main.py"

' 把工作目錄切到本資料夾，讓 chrome_profile / output/ 路徑正確
objShell.CurrentDirectory = strScriptDir

' 0 = 隱藏視窗，False = 不等待程式結束（VBS 立即退出）
objShell.Run "pythonw """ & strPyScript & """", 0, False
