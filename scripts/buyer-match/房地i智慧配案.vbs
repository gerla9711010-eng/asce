' 房地i智慧配案.vbs — 雙擊這支即可，會用 pythonw.exe（不會開黑窗）跑 gui_customer_match.py
' 房地客需 → i智慧即時案源，跟「啟動工具.vbs」（單獨查 i智慧）是兩個不同工具
' ⚠️ 視窗標題是「房地/i智慧配案」，檔名不能有斜線（Windows 檔名不允許 /）所以拿掉

Set objShell = CreateObject("WScript.Shell")
Set objFSO   = CreateObject("Scripting.FileSystemObject")

strScriptDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
strPyScript  = strScriptDir & "\gui_customer_match.py"

' 把工作目錄釘在本資料夾，chrome_profile / output / logs 路徑才會正確
objShell.CurrentDirectory = strScriptDir

' 0 = 隱藏視窗，False = 不等待（VBS 立刻退出）
objShell.Run "pythonw.exe """ & strPyScript & """", 0, False
