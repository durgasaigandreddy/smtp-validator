# Dot-source this file to load .env into the current PowerShell session:  . .\scripts\windows\env.ps1
param([string]$File = (Join-Path $PSScriptRoot "..\..\.env"))
if (-not (Test-Path $File)) {
    throw ".env not found at $File. Copy .env.example to .env and edit it."
}
Get-Content $File | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "" -or $line.StartsWith("#")) { return }
    $i = $line.IndexOf("=")
    if ($i -lt 1) { return }
    $name = $line.Substring(0, $i).Trim()
    $value = $line.Substring($i + 1).Trim().Trim('"')
    [Environment]::SetEnvironmentVariable($name, $value, "Process")
}
