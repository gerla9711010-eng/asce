' 背景啟動 Codex 文案服務（不跳黑窗）。
'
' 放法：把這支的「捷徑」丟進開機自動啟動資料夾
'   Win+R -> 貼 shell:startup -> Enter -> 在這裡按右鍵「貼上捷徑」
'
' 注意 2026-08-10 踩過兩個坑：
'   1) 使用者把「檔案本體」搬進開機資料夾，而舊版是用「自己所在的資料夾」去找 server.py，
'      搬走之後那裡沒有 server.py，開機時安靜什麼都不做，也沒有錯誤訊息。
'      現在改成先認寫死的專案路徑，找不到才退回自己所在的資料夾，所以搬到哪裡都能用。
'   2) 這支檔案存成 UTF-8 沒有 BOM 時，Windows Script Host 會用系統 ANSI 碼頁(Big5)去讀，
'      中文字被讀成亂位元組，跳出「必須提供陳述式」這種語法錯誤。已改存成 Big5(cp950)。
Const REPO = "C:\Users\user\asce\scripts\codex-copy"

Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

If fso.FileExists(REPO & "\server.py") Then
  base = REPO
Else
  base = fso.GetParentFolderName(WScript.ScriptFullName)
End If

If Not fso.FileExists(base & "\server.py") Then
  ' 這種情況下靜靜失敗最糟，寧可跳一次窗告訴使用者
  MsgBox "找不到 server.py。" & vbCrLf & vbCrLf & _
         "找過：" & vbCrLf & REPO & vbCrLf & base, vbExclamation, "Codex 文案服務"
  WScript.Quit 1
End If

sh.CurrentDirectory = base
' --tunnel：順便開 Cloudflare 快速通道，並自動把網址寫回 n8n
' （快速通道的網址每次重開都會變，所以要自動註冊）
' 0 = 不顯示視窗，False = 不等它結束
sh.Run "pythonw """ & base & "\server.py"" --tunnel --port 8787", 0, False
