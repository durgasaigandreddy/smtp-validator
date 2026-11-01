# Create another API key using an admin key.
#   .\scripts\windows\new-key.ps1 -AdminKey ev_xxx -Name "Client app"          (client key)
#   .\scripts\windows\new-key.ps1 -AdminKey ev_xxx -Name "Second admin" -Admin
param([Parameter(Mandatory = $true)][string]$AdminKey, [Parameter(Mandatory = $true)][string]$Name,
      [switch]$Admin, [string]$BaseUrl = "http://127.0.0.1:8000")
$ErrorActionPreference = "Stop"
$body = @{ name = $Name; admin = [bool]$Admin } | ConvertTo-Json
$r = Invoke-RestMethod -Method Post -Uri "$BaseUrl/admin/keys" -Headers @{ "X-API-Key" = $AdminKey } `
    -ContentType "application/json" -Body $body
Write-Host "API key for '$Name' (shown once):"
Write-Host $r.api_key
