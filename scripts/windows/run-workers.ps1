# Start one worker window per sending IP.
#   .\scripts\windows\run-workers.ps1                                  (reads config\ips.txt)
#   .\scripts\windows\run-workers.ps1 -Ips 192.168.1.50,192.168.1.51
param([string[]]$Ips = @())
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if ($Ips.Count -eq 0) {
    $Ips = Get-Content (Join-Path $Root "config\ips.txt") |
        ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $_.StartsWith("#") }
}
$Ips = @($Ips | Select-Object -Unique)
if ($Ips.Count -eq 0) { throw "No IPs. Put one per line in config\ips.txt, or pass -Ips a,b,c." }
foreach ($ip in $Ips) {
    Start-Process powershell -ArgumentList "-NoExit", "-File", (Join-Path $PSScriptRoot "run-worker.ps1"), "-Ip", $ip
    Write-Host "Started a worker window for $ip"
}
Write-Host "Each worker adds its IP to ip_state when it starts. Check: GET /admin/status"
