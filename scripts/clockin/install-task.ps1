# Register a Windows Scheduled Task that auto-clocks-in between 09:00-10:00
# on Thursdays, Saturdays and Sundays only.
# Keep this file ASCII-only: Windows PowerShell 5.1 mangles non-ASCII source.
# Usage:  powershell -ExecutionPolicy Bypass -File .\install-task.ps1
# Remove: Unregister-ScheduledTask -TaskName 'houseol-auto-clockin' -Confirm:$false

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# Prefer pythonw.exe (no console window); fall back to python.exe
$py = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-Command python.exe -ErrorAction Stop).Source }
$script = Join-Path $here 'clockin.py'

if (-not (Test-Path (Join-Path $here '.env'))) {
  Write-Warning "No .env found. Fill HOUSEOL_PASS in scripts/clockin/.env before the task can log in."
}

# Task fires at 09:00; the script's --jitter 3600 sleeps a random 0-60 min
# => actual clock-in lands at an irregular time within 09:00-10:00.
$action  = New-ScheduledTaskAction -Execute $py -Argument "`"$script`" --jitter 3600" -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Thursday,Saturday,Sunday -At 9:00am
# ExecutionTimeLimit must exceed max jitter (60 min) + run time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask -TaskName 'houseol-auto-clockin' `
  -Action $action -Trigger $trigger -Settings $settings `
  -Description 'Auto clock-in to houseol between 09:00-10:00 on Thu/Sat/Sun' -Force

Write-Host "Registered scheduled task 'houseol-auto-clockin' (Thu/Sat/Sun, random 09:00-10:00)." -ForegroundColor Green
Write-Host "Test now: python clockin.py --dry-run" -ForegroundColor Cyan
