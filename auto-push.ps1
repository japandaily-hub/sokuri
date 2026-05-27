$ErrorActionPreference = "Stop"
Set-Location C:\sokuri

Write-Host "=== git commit --allow-empty (Railway webhook trigger) ===" -ForegroundColor Cyan
git commit --allow-empty -m "ci: trigger Railway redeploy for Phase 2 albums endpoint"

Write-Host ""
Write-Host "=== git push ===" -ForegroundColor Cyan
git push

Write-Host ""
Write-Host "=== DONE ===" -ForegroundColor Green
Start-Sleep -Seconds 3
