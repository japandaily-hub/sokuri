# 新 PC 移行用: OneDrive 同期された .env を C:\sokuri 配下に配置する。
#
# 想定:
#   旧 PC で C:\sokuri\.tools\backup-env.ps1 を実行（または手動で
#   backend/.env と web/.env.local を下記 $oneDriveDir にコピー）してある状態。
#   OneDrive デスクトップアプリにより新 PC でも $oneDriveDir が自動 sync される。
#
# 使い方（新 PC）:
#   1. git clone https://github.com/japandaily-hub/sokuri.git C:\sokuri
#   2. OneDrive のサインインを完了し、ファイル同期を待つ
#   3. powershell -ExecutionPolicy Bypass -File C:\sokuri\.tools\restore-env.ps1
#
# 失敗時は手動で OneDrive 配下の 2 ファイルを backend/.env と web/.env.local に
# 名前変更してコピーすれば同じ結果。

$ErrorActionPreference = "Stop"

$repoRoot = "C:\sokuri"
$oneDriveDir = "C:\Users\$env:USERNAME\OneDrive\ドキュメント\Claude\Projects\ソクウリ\sokuri-migration"

if (-not (Test-Path $oneDriveDir)) {
    Write-Host "ERROR: OneDrive 同期ディレクトリが見つかりません: $oneDriveDir" -ForegroundColor Red
    Write-Host "       OneDrive アプリでサインイン → 同期完了を待ってから再実行してください。" -ForegroundColor Yellow
    exit 1
}

$srcBackend = Join-Path $oneDriveDir "backend.env"
$srcWeb     = Join-Path $oneDriveDir "web.env.local"
$dstBackend = Join-Path $repoRoot "backend\.env"
$dstWeb     = Join-Path $repoRoot "web\.env.local"

function Copy-IfPresent($src, $dst, $label) {
    if (Test-Path $src) {
        $dir = Split-Path $dst -Parent
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        Copy-Item -Path $src -Destination $dst -Force
        Write-Host "OK: ${label} を ${dst} に配置" -ForegroundColor Green
    } else {
        Write-Host "SKIP: ${label} がバックアップに無いためスキップ ($src)" -ForegroundColor Yellow
    }
}

Copy-IfPresent $srcBackend $dstBackend "backend/.env"
Copy-IfPresent $srcWeb     $dstWeb     "web/.env.local"

Write-Host ""
Write-Host "=== restore-env DONE ===" -ForegroundColor Cyan
Write-Host "git status で .env が untracked になっていなければ OK（.gitignore 済）。" -ForegroundColor Gray
