# Start the API for development (auto-reload). Open http://127.0.0.1:8000/docs
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Root
. (Join-Path $PSScriptRoot "env.ps1")
$Port = if ($env:API_PORT) { $env:API_PORT } else { "8000" }
& (Join-Path $Root "venv\Scripts\python.exe") -m uvicorn app.api:app --host 127.0.0.1 --port $Port --reload
