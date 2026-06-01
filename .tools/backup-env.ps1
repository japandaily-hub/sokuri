# 旧 PC で実行: 現在の .env を OneDrive 同期フォルダにコピーする。
#
# 用途:
#   - 新 PC 移行前に最新の .env をバックアップ
#   - 鍵をローテーションした後の再保存
#
# 使い方:
#   powershell -ExecutionPolicy Bypass -File C:\sokuri\.tools\backup-env.ps1

$ErrorActionPreference = "Stop"

$repoRoot = "C:\sokuri"
$oneDriveDir = "C:\Users\$env:USERNAME\OneDrive\ドキュメント\Claude\Projects\ソクウリ\sokuri-migration"

if (-not (Test-Path $oneDriveDir)) {
    New-Item -ItemType Directory -Path $oneDriveDir -Force | Out-Null
    Write-Host "INFO: $oneDriveDir を新規作成" -ForegroundColor Cyan
}

$srcBackend = Join-Path $repoRoot "backend\.env"
$srcWeb     = Join-Path $repoRoot "web\.env.local"
$dstBackend = Join-Path $oneDriveDir "backend.env"
$dstWeb     = Join-Path $oneDriveDir "web.env.local"

function Copy-IfPresent($src, $dst, $label) {
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination $dst -Force
        Write-Host "OK: ${label} を $dst にバックアップ" -ForegroundColor Green
    } else {
        Write-Host "SKIP: ${label} が存在しないためスキップ ($src)" -ForegroundColor Yellow
    }
}

Copy-IfPresent $srcBackend $dstBackend "backend/.env"
Copy-IfPresent $srcWeb     $dstWeb     "web/.env.local"

Write-Host ""
Write-Host "=== backup-env DONE ===" -ForegroundColor Cyan
Write-Host "OneDrive アプリで sync 完了表示が出れば、新 PC からも自動取得されます。" -ForegroundColor Gray
