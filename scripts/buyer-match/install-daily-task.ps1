# Register a Windows Scheduled Task that runs the buyer-match daily job.
# Keep this file ASCII-only: Windows PowerShell 5.1 mangles non-ASCII source.
# Usage:  powershell -ExecutionPolicy Bypass -File .\install-daily-task.ps1
# Remove: Unregister-ScheduledTask -TaskName 'buyer-match-daily' -Confirm:$false
#
# Two triggers (2026-08-05): 15 min after logon (the PC shuts down at 00:30 every
# night, so logon == the user arriving at the store: start early, finish early),
# plus 08:10 daily as a backstop for a late/no logon.
# Running A/B/C takes ~2h, so starting at logon matters.
#
# The store PC is offline 00:00 - ~07:22. daily_run.py waits for the network
# instead of mistaking the outage for an expired login, and records the date it
# finished so the two triggers (or a midday reboot) cannot run it twice a day.
# It starts the CDP Chrome itself if needed, and pushes a LINE message on
# success, on zero hits, and on every failure.

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

$action = New-ScheduledTaskAction -Execute $py -Argument "`"$script`"" -WorkingDirectory $here

$daily = New-ScheduledTaskTrigger -Daily -At 8:10am
# 15 min after logon: let OneDrive / Chrome / LINE finish starting up first
# (the PC has 16 GB and everything autostarts at once).
$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$logon.Delay = 'PT15M'

# A/B/C together run ~2h; 6h leaves headroom without hanging forever.
# StartWhenAvailable: if the PC was off at 08:10, run as soon as it is on again.
# IgnoreNew: if the logon run is still going at 08:10, do not start a second one.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
  -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries `
  -ExecutionTimeLimit (New-TimeSpan -Hours 6) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName 'buyer-match-daily' `
  -Action $action -Trigger @($daily, $logon) -Settings $settings `
  -Description 'buyer-match run (foundi needs -> ismart live cases), 15 min after logon + 08:10 backstop, LINE report' -Force

Write-Host "Registered scheduled task 'buyer-match-daily' (logon +15 min, and 08:10 backstop)." -ForegroundColor Green
Write-Host "Check LINE plumbing now: python daily_run.py --notify-test" -ForegroundColor Cyan
Write-Host "Full dry run now:        python daily_run.py --dry-run" -ForegroundColor Cyan
Write-Host "Log file:                $(Join-Path $here 'daily_run.log')" -ForegroundColor Cyan
