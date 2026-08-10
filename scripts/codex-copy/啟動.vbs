' 背景啟動 Codex 文案服務（不跳黑窗）。
' 放捷徑到「開機自動啟動」資料夾，開機就會跑起來：
'   Win+R → 貼 shell:startup → Enter → 把這支的捷徑丟進去
'
' 想看它有沒有在跑：瀏覽器開 http://127.0.0.1:8787/health
' 想看紀錄：同資料夾 logs\codex-copy.log
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.CurrentDirectory = here
' 0 = 不顯示視窗，False = 不等它結束
sh.Run "pythonw """ & here & "\server.py"" --port 8787", 0, False
