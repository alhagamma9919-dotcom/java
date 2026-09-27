# Comfy Remote installer. Run in PowerShell as Administrator:
#   powershell -ExecutionPolicy Bypass -File install.ps1 [-ComfyDir C:\ComfyUI]
param([string]$ComfyDir = "C:\ComfyUI")
$ErrorActionPreference = "Stop"
$here = $PSScriptRoot

$py = Join-Path $ComfyDir "venv\Scripts\pythonw.exe"
if (!(Test-Path $py)) { $py = Join-Path (Split-Path $ComfyDir) "python_embeded\pythonw.exe" }
if (!(Test-Path $py)) { throw "pythonw.exe not found for $ComfyDir. Install ComfyUI (with venv) first." }

$cfg = Join-Path $here "config.json"
if (!(Test-Path $cfg)) { @{ comfy_dir = $ComfyDir } | ConvertTo-Json | Set-Content $cfg -Encoding UTF8 }

# Start the launcher (hidden) every time you log in
$act = New-ScheduledTaskAction -Execute $py -Argument "`"$here\launcher.py`"" -WorkingDirectory $here
$trg = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "Comfy Remote" -Action $act -Trigger $trg -Settings $set -Force | Out-Null

# Firewall: port 8190 only from the home network and Tailscale
Remove-NetFirewallRule -DisplayName "Comfy Remote" -ErrorAction SilentlyContinue
New-NetFirewallRule -DisplayName "Comfy Remote" -Direction Inbound -Protocol TCP -LocalPort 8190 `
    -RemoteAddress LocalSubnet, 100.64.0.0/10 -Action Allow | Out-Null

Stop-ScheduledTask -TaskName "Comfy Remote" -ErrorAction SilentlyContinue
Start-ScheduledTask -TaskName "Comfy Remote"
Start-Sleep 4

$c = Get-Content $cfg -Raw | ConvertFrom-Json
$ts = (& tailscale ip -4 2>$null | Select-Object -First 1)
$lan = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.PrefixOrigin -eq 'Dhcp' } | Select-Object -First 1).IPAddress
""
"Comfy Remote is running."
"  PIN           : $($c.pin)"
if ($lan) { "  Home Wi-Fi    : http://${lan}:8190" }
if ($ts)  { "  Tailscale     : http://${ts}:8190   (or http://$($env:COMPUTERNAME.ToLower()):8190)" }
""
"Put your API-format workflows in: $here\workflows"
