# Show a job's progress, or download its results CSV.
#   .\scripts\windows\job-status.ps1 -Key ev_xxx -JobId 1
#   .\scripts\windows\job-status.ps1 -Key ev_xxx -JobId 1 -OutFile results.csv
param([Parameter(Mandatory = $true)][string]$Key, [Parameter(Mandatory = $true)][int]$JobId,
      [string]$BaseUrl = "http://127.0.0.1:8000", [string]$OutFile = "")
$ErrorActionPreference = "Stop"
$h = @{ "X-API-Key" = $Key }
if ($OutFile) {
    Invoke-WebRequest -Uri "$BaseUrl/v1/jobs/$JobId/results.csv" -Headers $h -OutFile $OutFile
    Write-Host "Saved $OutFile"
} else {
    Invoke-RestMethod -Uri "$BaseUrl/v1/jobs/$JobId" -Headers $h | ConvertTo-Json -Depth 6
}
