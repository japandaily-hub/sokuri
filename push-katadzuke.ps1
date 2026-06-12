# push-katadzuke.ps1 v3 — stash復元 + commit + push（単独実行前提）
$ErrorActionPreference = "Stop"
Set-Location C:\sokuri

Write-Host "=== 0/6 lock 掃除 & 状態確認 ===" -ForegroundColor Cyan
$lock = "C:\sokuri\.git\index.lock"
if (Test-Path $lock) { Remove-Item $lock -Force }
# stash pop 失敗で残った unmerged index を解消（working tree は保持）
git reset | Out-Null
git stash list

Write-Host "=== 1/6 origin/main 取り込み ===" -ForegroundColor Cyan
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw "pull failed" }

Write-Host "=== 2/6 stash から共有ファイル編集分を復元 ===" -ForegroundColor Cyan
$stashed = git stash list
if ($stashed -match "katadzuke-beta-wip") {
  $tracked = @(
    "render.yaml",
    "backend/pyproject.toml",
    "backend/.env.example",
    "backend/app/config.py",
    "backend/app/api/v1/router.py",
    "backend/app/db/models/__init__.py",
    "backend/tests/conftest.py",
    "web/package.json",
    "web/src/app/layout.tsx"
  )
  git checkout "stash@{0}" -- $tracked
  if ($LASTEXITCODE -ne 0) { throw "stash restore failed" }
  git stash drop "stash@{0}"
  Write-Host "restored from stash" -ForegroundColor Green
} else {
  Write-Host "stash なし（復元済みとみなす）" -ForegroundColor Yellow
}

Write-Host "=== 2.5/6 復元内容の検証 ===" -ForegroundColor Cyan
$checks = @(
  @{f="web/package.json";          p="next-auth"},
  @{f="backend/app/api/v1/router.py"; p="auth_router"},
  @{f="backend/app/config.py";     p="jwt_secret"},
  @{f="web/src/app/layout.tsx";    p="Providers"},
  @{f="backend/app/db/models/__init__.py"; p="Invite"},
  @{f="render.yaml";               p="JWT_SECRET"}
)
foreach ($c in $checks) {
  if (-not (Select-String -Path $c.f -Pattern $c.p -Quiet)) { throw ("verify failed: " + $c.f) }
}
Write-Host "verify OK" -ForegroundColor Green

Write-Host "=== 3/6 package-lock.json 更新 ===" -ForegroundColor Cyan
Push-Location web
npm install --package-lock-only --no-audit --no-fund
Pop-Location

Write-Host "=== 4/6 stage & commit ===" -ForegroundColor Cyan
$files = @(
  "render.yaml","push-katadzuke.ps1",
  "backend/pyproject.toml","backend/.env.example",
  "backend/alembic/versions/0004_katadzuke_schema.py",
  "backend/alembic/versions/0005_auth_tables.py",
  "backend/app/config.py","backend/app/schemas_katadzuke.py",
  "backend/app/core","backend/app/api/deps.py","backend/app/api/v1/router.py",
  "backend/app/api/v1/endpoints/auth.py","backend/app/api/v1/endpoints/case_photos.py",
  "backend/app/api/v1/endpoints/cases.py","backend/app/api/v1/endpoints/bids.py",
  "backend/app/api/v1/endpoints/transactions.py","backend/app/api/v1/endpoints/reductions.py",
  "backend/app/api/v1/endpoints/reviews.py","backend/app/api/v1/endpoints/admin.py",
  "backend/app/db/models/__init__.py","backend/app/db/models/case.py",
  "backend/app/db/models/operator.py","backend/app/db/models/bid.py",
  "backend/app/db/models/transaction.py","backend/app/db/models/user.py",
  "backend/app/db/models/invite.py",
  "backend/app/services/storage.py","backend/app/services/summary.py",
  "backend/app/services/notify.py",
  "backend/tests/conftest.py","backend/tests/test_katadzuke_api.py",
  "web/package.json","web/package-lock.json","web/.env.example",
  "web/src/auth.ts","web/src/middleware.ts","web/src/types/next-auth.d.ts",
  "web/src/lib/katadzuke-api.ts","web/src/components/AuthCard.tsx",
  "web/src/components/kdz","web/src/app/providers.tsx","web/src/app/layout.tsx",
  "web/src/app/api/auth","web/src/app/login","web/src/app/signup",
  "web/src/app/create","web/src/app/cases","web/src/app/admin","web/src/app/operator"
)
git add -- $files
git commit -m "feat(katadzuke): closed beta - auth/cases/bids/transactions/reductions/reviews/admin + NextAuth v5 (migrations 0004-0005, additive)"
if ($LASTEXITCODE -ne 0) { throw "commit failed" }

Write-Host "=== 5/6 push ===" -ForegroundColor Cyan
git push origin main
if ($LASTEXITCODE -ne 0) { throw "push failed" }
Write-Host "push OK" -ForegroundColor Green

Write-Host "=== 6/6 Render ヘルスチェック ===" -ForegroundColor Cyan
Start-Sleep -Seconds 120
$ok = $false
for ($i = 1; $i -le 10; $i++) {
    try {
        $res = Invoke-WebRequest -Uri "https://sokuri-backend.onrender.com/health" -UseBasicParsing -TimeoutSec 20
        if ($res.StatusCode -eq 200) { $ok = $true; break }
    } catch { Write-Host "waiting... ($i/10)" -ForegroundColor Yellow }
    Start-Sleep -Seconds 25
}
if ($ok) { Write-Host "Render API: OK" -ForegroundColor Green } else { Write-Host "Render API: NG" -ForegroundColor Red }
Write-Host "ALL DONE" -ForegroundColor Green
