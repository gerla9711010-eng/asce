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
' --tunnel：順便開 Cloudflare 快速通道，並自動把網址寫回 n8n（網址每次重開都會變，所以要自動註冊）
sh.Run "pythonw """ & here & "\server.py"" --tunnel --port 8787", 0, False
