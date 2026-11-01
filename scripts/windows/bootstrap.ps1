# Create the FIRST admin API key (works once). Needs BOOTSTRAP_TOKEN (16+ characters) in .env
# and the API restarted after you set it.   .\scripts\windows\bootstrap.ps1
param([string]$BaseUrl = "", [string]$Name = "First admin")
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "env.ps1")
if (-not $BaseUrl) { $p = if ($env:API_PORT) { $env:API_PORT } else { "8000" }; $BaseUrl = "http://127.0.0.1:$p" }
if (-not $env:BOOTSTRAP_TOKEN) { throw "Set BOOTSTRAP_TOKEN in .env (16+ characters), restart the API, then run this again." }
$r = Invoke-RestMethod -Method Post -Uri "$BaseUrl/bootstrap" `
    -Headers @{ "X-Setup-Token" = $env:BOOTSTRAP_TOKEN } `
    -ContentType "application/json" -Body (@{ name = $Name } | ConvertTo-Json)
Write-Host "Admin API key (shown once, store it safely):"
Write-Host $r.api_key
Write-Host "Now delete BOOTSTRAP_TOKEN from .env."
