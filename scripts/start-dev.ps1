param(
  [string]$BackendHost = "127.0.0.1",
  [int]$BackendPort = 8000,
  [int]$FrontendPort = 3000
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$frontend = Join-Path $root "frontend"
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
  $venvPython = Join-Path $root "venv\Scripts\python.exe"
}

if (-not (Test-Path $frontend)) {
  Write-Error "frontend directory not found: $frontend"
}

if (-not (Test-Path $venvPython)) {
  Write-Error "Python venv not found. Create .venv and install requirements first."
}

if (Test-Path (Join-Path $root ".git")) {
  $branch = (& git -C $root branch --show-current).Trim()
  $changes = & git -C $root status --porcelain
  if ($branch -eq "main" -and -not $changes) {
    Write-Host "Checking GitHub for a safe main-branch update ..."
    & git -C $root fetch origin main
    if ($LASTEXITCODE -eq 0) {
      & git -C $root merge --ff-only origin/main
      if ($LASTEXITCODE -ne 0) {
        Write-Warning "Remote main could not be fast-forwarded. Starting the preserved local version."
      }
    } else {
      Write-Warning "GitHub is unavailable. Starting the preserved local version."
    }
  } else {
    Write-Host "Automatic update skipped (branch is not main or local changes are present)."
  }
}

Write-Host "Applying database migrations ..."
Push-Location $root
try {
  & $venvPython -m alembic upgrade head
  if ($LASTEXITCODE -ne 0) {
    Write-Error "Database migration failed; services were not started."
  }
} finally {
  Pop-Location
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
