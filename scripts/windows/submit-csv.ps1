# Upload a CSV (column "email") as a job.  Uses curl.exe, which ships with Windows 10/11.
#   .\scripts\windows\submit-csv.ps1 -Key ev_xxx -File .\sample_1000_emails.csv
#   .\scripts\windows\submit-csv.ps1 -Key ev_xxx -File .\list.csv -Webhook http://192.168.1.20:9000/hook
param([Parameter(Mandatory = $true)][string]$Key, [Parameter(Mandatory = $true)][string]$File,
      [string]$BaseUrl = "http://127.0.0.1:8000", [string]$Webhook = "", [string]$CaCert = "")
$ErrorActionPreference = "Stop"
if (-not (Test-Path $File)) { throw "File not found: $File" }
$args = @("-sS", "-H", "X-API-Key: $Key", "-F", "file=@$File")
if ($Webhook) { $args += @("-F", "webhook_url=$Webhook") }
if ($CaCert) { $args += @("--cacert", $CaCert) }
$args += "$BaseUrl/v1/jobs/upload"
& curl.exe @args
Write-Host ""
