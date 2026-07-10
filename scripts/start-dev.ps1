param(
  [string]$BackendHost = "127.0.0.1",
  [int]$BackendPort = 8000,
  [int]$FrontendPort = 3000
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $root "frontend"
$venvPython = Join-Path $root "venv\Scripts\python.exe"

if (-not (Test-Path $frontend)) {
  Write-Error "frontend directory not found: $frontend"
}

if (-not (Test-Path $venvPython)) {
  Write-Error "Python venv not found: $venvPython"
}

$frontendEnvLocal = Join-Path $frontend ".env.local"
$frontendEnvExample = Join-Path $frontend ".env.example"
if ((-not (Test-Path $frontendEnvLocal)) -and (Test-Path $frontendEnvExample)) {
  Copy-Item $frontendEnvExample $frontendEnvLocal
  Write-Host "Created frontend/.env.local from .env.example"
}

Write-Host "Starting backend on http://$BackendHost`:$BackendPort ..."
Start-Process powershell -ArgumentList @(
  "-NoExit",
  "-Command",
  "Set-Location '$root'; & '$venvPython' -m uvicorn app.main:app --reload --host $BackendHost --port $BackendPort"
)

Write-Host "Starting frontend on http://localhost:$FrontendPort ..."
Start-Process powershell -ArgumentList @(
  "-NoExit",
  "-Command",
  "Set-Location '$frontend'; npm run dev -- --port $FrontendPort"
)

Write-Host "Dev services launched in new terminal windows."
