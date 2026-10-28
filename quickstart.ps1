# CRM Entity Resolution System - Quick Start Script (Windows)
# Usage: .\quickstart.ps1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "CRM Entity Resolution System - QuickStart" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check if Docker is running
try {
    $dockerInfo = docker info 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Docker not running. Please start Docker Desktop." -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "ERROR: Docker not found. Please install Docker Desktop." -ForegroundColor Red
    exit 1
}

Write-Host "[1/6] Checking Docker containers..." -ForegroundColor Yellow

# Check if crm-pg exists
$pgContainer = docker ps -a -f "name=crm-pg" --format "{{.Names}}"
if ($pgContainer -ne "crm-pg") {
    Write-Host "Creating crm-pg container..." -ForegroundColor Yellow
    docker run -d `
        --name crm-pg `
        -e POSTGRES_DB=crm `
        -e POSTGRES_USER=crm_user `
        -e POSTGRES_PASSWORD=crm_password_2026 `
        -p 5432:5432 `
        postgres:17-alpine
} elseif ($pgContainer -eq "crm-pg" -and (docker ps -f "name=crm-pg" --format "{{.Names}}") -ne "crm-pg") {
    Write-Host "Starting existing crm-pg container..." -ForegroundColor Yellow
    docker start crm-pg
}

# Wait for PostgreSQL to be ready
Write-Host "Waiting for PostgreSQL to be ready..." -ForegroundColor Yellow
$pgReady = $false
for ($i = 30; $i -gt 0; $i--) {
    if (docker exec crm-pg pg_isready -U crm_user -d crm 2>&1 | Select-String -Quiet "accepting connections") {
        $pgReady = $true
        break
    }
    Start-Sleep -Seconds 1
}

if (-not $pgReady) {
    Write-Host "ERROR: PostgreSQL not ready after 30 seconds." -ForegroundColor Red
    exit 1
}
Write-Host "PostgreSQL is ready!" -ForegroundColor Green

Write-Host ""
Write-Host "[2/6] Setting up Python environment..." -ForegroundColor Yellow

# Check Python version
$pythonVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Python not found." -ForegroundColor Red
    exit 1
}
Write-Host "Found: $pythonVersion" -ForegroundColor Gray

# Create virtual environment
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Yellow
    python -m venv .venv
}

# Install dependencies
Write-Host "Installing dependencies..." -ForegroundColor Yellow
.venv\Scripts\pip install --upgrade pip
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pip install python-dotenv requests

Write-Host ""
Write-Host "[3/6] Training Splink model..." -ForegroundColor Yellow

.venv\Scripts\python src/splink_model.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "WARNING: Model training may have issues. Check logs." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "[4/6] Running batch prediction..." -ForegroundColor Yellow

.venv\Scripts\python scripts/batch_predict.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "WARNING: Batch prediction may have issues. Check logs." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "[5/6] Starting API server..." -ForegroundColor Yellow

Start-Process -FilePath ".venv\Scripts\python.exe" -ArgumentList "api\app.py" -WindowStyle Normal
Start-Sleep -Seconds 3

# Verify API is running
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 5
    if ($response.StatusCode -eq 200) {
        Write-Host "API is running on http://localhost:8000" -ForegroundColor Green
    }
} catch {
    Write-Host "WARNING: API may not be running. Check /tmp/api.log" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "[6/6] Starting UI dashboard..." -ForegroundColor Yellow

.venv\Scripts\streamlit run ui/app.py --server.port 8501 --server.headless true

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "QuickStart complete!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "API: http://localhost:8000" -ForegroundColor White
Write-Host "UI:  http://localhost:8501" -ForegroundColor White
