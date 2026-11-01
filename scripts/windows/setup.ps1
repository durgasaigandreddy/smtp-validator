# One-time development setup: virtual environment, packages, .env
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root

& python -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.10 or newer is required (python --version)." }

if (-not (Test-Path "venv")) { & python -m venv venv }
$Py = Join-Path $Root "venv\Scripts\python.exe"
& $Py -m pip install --upgrade pip
& $Py -m pip install -r requirements.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env - open it and set the passwords, HELO_HOST and MAIL_FROM."
}
Write-Host ""
Write-Host "Next:"
Write-Host "  1. docker compose -f docker-compose.dev.yml up -d     (Postgres on localhost:5432)"
Write-Host "  2. .\scripts\windows\run-api.ps1"
Write-Host "  3. set BOOTSTRAP_TOKEN in .env, restart the API, run .\scripts\windows\bootstrap.ps1"
