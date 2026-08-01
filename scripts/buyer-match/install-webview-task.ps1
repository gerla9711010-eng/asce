# Register a Windows Scheduled Task that keeps the buyer-match web dashboard
# running in the background, starting automatically at logon.
# Keep this file ASCII-only: Windows PowerShell 5.1 mangles non-ASCII source.
# Usage:  powershell -ExecutionPolicy Bypass -File .\install-webview-task.ps1
# Remove: Unregister-ScheduledTask -TaskName 'buyer-match-webview' -Confirm:$false
#
# Serves on 0.0.0.0:5001 so a phone on the same WiFi can reach it too.
# LAN-only, no login/password. Windows Firewall may prompt "allow python.exe
# through the firewall" the first time a device connects from another host --
# click Allow (Private network is enough; this store PC should not be on a
# Public-classified network anyway).

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

$py = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-Command python.exe -ErrorAction Stop).Source }
$script = Join-Path $here 'webview_server.py'
if (-not (Test-Path $script)) { throw "webview_server.py not found next to this script: $script" }

$action  = New-ScheduledTaskAction -Execute $py -Argument "`"$script`"" -WorkingDirectory $here
$trigger = New-ScheduledTaskTrigger -AtLogOn
# No execution time limit (it's meant to run forever) + restart on crash.
$settings = New-ScheduledTaskSettingsSet `
  -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
  -StartWhenAvailable

Register-ScheduledTask -TaskName 'buyer-match-webview' `
  -Action $action -Trigger $trigger -Settings $settings `
  -Description 'Buyer-match results dashboard, always-on local web server (port 5001)' -Force

# Start it right now too, don't make them log off/on to see it.
Start-ScheduledTask -TaskName 'buyer-match-webview'

$ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object {
  $_.InterfaceAlias -notmatch 'Loopback' -and $_.IPAddress -notlike '169.254.*'
} | Select-Object -First 1).IPAddress

Write-Host "Registered + started scheduled task 'buyer-match-webview' (runs at every logon)." -ForegroundColor Green
Write-Host "On this PC:  http://localhost:5001" -ForegroundColor Cyan
if ($ip) { Write-Host "From phone (same WiFi): http://$ip`:5001" -ForegroundColor Cyan }
Write-Host "If your phone can't connect, Windows Firewall may be blocking it -- check for an 'Allow python.exe' prompt on this PC, or ask to add a firewall rule." -ForegroundColor Yellow
