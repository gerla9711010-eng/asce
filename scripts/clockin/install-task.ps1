# 註冊「每天 09:00–10:00 之間隨機自動簽到」的 Windows 工作排程。
# 用法（在本資料夾按右鍵 → 用 PowerShell 執行，或）：
#   powershell -ExecutionPolicy Bypass -File .\install-task.ps1
# 移除：Unregister-ScheduledTask -TaskName 'houseol-auto-clockin' -Confirm:$false

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# 用 pythonw.exe（沒有黑視窗）；找不到就退回 python.exe
$py = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-Command python.exe -ErrorAction Stop).Source }
$script = Join-Path $here 'clockin.py'

if (-not (Test-Path (Join-Path $here 'profile'))) {
  Write-Warning "還沒登入設定檔！排程裝好前請先跑一次： python clockin.py --login"
}

$action  = New-ScheduledTaskAction -Execute $py -Argument "`"$script`"" -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -Daily -At 9:00am
# 09:00 觸發後隨機延遲 0~60 分鐘 → 每天落在 9:00–10:00 之間不規則時間
$trigger.RandomDelay = (New-TimeSpan -Hours 1)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask -TaskName 'houseol-auto-clockin' `
  -Action $action -Trigger $trigger -Settings $settings `
  -Description '每天 9:00-10:00 之間隨機自動到 houseol 差勤系統簽到' -Force

Write-Host "已註冊工作排程 'houseol-auto-clockin'（每天 9:00-10:00 隨機執行）。" -ForegroundColor Green
Write-Host "手動測一次： python clockin.py --dry-run" -ForegroundColor Cyan
