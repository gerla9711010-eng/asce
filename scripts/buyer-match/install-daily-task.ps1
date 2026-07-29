# Register a Windows Scheduled Task that runs the buyer-match daily job at 08:10.
# Keep this file ASCII-only: Windows PowerShell 5.1 mangles non-ASCII source.
# Usage:  powershell -ExecutionPolicy Bypass -File .\install-daily-task.ps1
# Remove: Unregister-ScheduledTask -TaskName 'buyer-match-daily' -Confirm:$false
#
# Store PC is offline 00:00 - ~07:22 every night, so 08:10 is safely after
# the network is back. daily_run.py starts the CDP Chrome itself if needed,
# and pushes a LINE message on success, on zero hits, and on every failure.

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# Prefer pythonw.exe (no console window); fall back to python.exe
$py = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-Command python.exe -ErrorAction Stop).Source }
$script = Join-Path $here 'daily_run.py'

if (-not (Test-Path $script)) { throw "daily_run.py not found next to this script: $script" }

$envFile = Join-Path $here '.env'
$keisEnv = Join-Path (Split-Path -Parent $here) 'keis\.env'
if (-not (Test-Path $envFile) -and -not (Test-Path $keisEnv)) {
  Write-Warning "No .env found here and no scripts\keis\.env either. Without BUYER_MATCH_NOTIFY_WEBHOOK (or KEIS_NOTIFY_WEBHOOK) the job runs but sends no LINE message."
}

$action  = New-ScheduledTaskAction -Execute $py -Argument "`"$script`"" -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -Daily -At 8:10am
# A full group run took ~16 min in testing; allow plenty of headroom.
# StartWhenAvailable: if the PC was off at 08:10, run as soon as it is on again.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 3)

Register-ScheduledTask -TaskName 'buyer-match-daily' `
  -Action $action -Trigger $trigger -Settings $settings `
  -Description 'Daily 08:10 buyer-match run (foundi needs -> ismart live cases) with LINE report' -Force

Write-Host "Registered scheduled task 'buyer-match-daily' (every day 08:10)." -ForegroundColor Green
Write-Host "Check LINE plumbing now: python daily_run.py --notify-test" -ForegroundColor Cyan
Write-Host "Full dry run now:        python daily_run.py --dry-run" -ForegroundColor Cyan
Write-Host "Log file:                $(Join-Path $here 'daily_run.log')" -ForegroundColor Cyan
