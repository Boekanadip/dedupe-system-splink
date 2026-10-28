# CRM Entity Resolution System - Stop Script (Windows)
# Usage: .\stop.ps1

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Stopping CRM Entity Resolution System" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Stopping API server..." -ForegroundColor Yellow
Get-Process -Name "python" -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*api\app.py*" } | Stop-Process -Force

Write-Host ""
Write-Host "Stopping Docker containers..." -ForegroundColor Yellow
docker stop crm-pg 2>$null
docker stop crm-api 2>$null
docker stop crm-ui 2>$null

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "All services stopped." -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
