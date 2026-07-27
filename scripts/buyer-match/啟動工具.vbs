' 啟動工具.vbs — 雙擊這支即可，會用 pythonw.exe（不會開黑窗）跑 gui_main.py

Set objShell = CreateObject("WScript.Shell")
Set objFSO   = CreateObject("Scripting.FileSystemObject")

strScriptDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
strPyScript  = strScriptDir & "\gui_main.py"

' 把工作目錄釘在本資料夾，chrome_profile / output / logs 路徑才會正確
objShell.CurrentDirectory = strScriptDir

' 0 = 隱藏視窗，False = 不等待（VBS 立刻退出）
objShell.Run "pythonw.exe """ & strPyScript & """", 0, False
