# Start one worker bound to one local IP address.   .\scripts\windows\run-worker.ps1 -Ip 192.168.1.50
# Note: most home and office networks block outbound port 25, so checks may end as "unknown".
param([Parameter(Mandatory = $true)][string]$Ip)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
. (Join-Path $PSScriptRoot "env.ps1")
$env:SOURCE_IP = $Ip
& (Join-Path $Root "venv\Scripts\python.exe") -m app.worker
