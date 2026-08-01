' 配案看板.vbs — 雙擊手動啟動網頁看板（不會開黑窗）
' 平常不用點這個：install-webview-task.ps1 裝好排程後開機會自動啟動。
' 這支是備用：排程掛掉或想手動重開時用。

Set objShell = CreateObject("WScript.Shell")
Set objFSO   = CreateObject("Scripting.FileSystemObject")

strScriptDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
strPyScript  = strScriptDir & "\webview_server.py"

objShell.CurrentDirectory = strScriptDir

' 0 = 隱藏視窗，False = 不等待（VBS 立刻退出）
objShell.Run "pythonw.exe """ & strPyScript & """", 0, False
