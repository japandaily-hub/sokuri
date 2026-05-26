<#
.SYNOPSIS
  ソクウリ — GitHub 初回アップロード補助スクリプト (PowerShell 版)

.DESCRIPTION
  setup-github.bat と等価。Windows Defender の .bat 誤検知を回避するため
  PowerShell に書き直したもの。事前に GitHub 上で「空のリポジトリ」を
  作成しておくこと (README / .gitignore / license は追加しない)。

.PARAMETER RepoUrl
  作成した GitHub リポジトリの URL (例: https://github.com/yourname/sokuri.git)

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File C:\sokuri\setup-github.ps1 `
    -RepoUrl https://github.com/yourname/sokuri.git
#>

[CmdletBinding()]
param(
  [Parameter(Mandatory = $false, Position = 0)]
  [string]$RepoUrl
)

$ErrorActionPreference = "Stop"

# -------------------------------------------------------------
# Bootstrap: Windows Terminal 自動切替
# -------------------------------------------------------------
# 旧 conhost (Windows PowerShell の既定コンソール) は既定フォントが CJK 非対応
# のため日本語が □ 化する。Windows Terminal は CJK フォールバックが効くので
# 利用可能なら自動で WT へ切り替える。WT セッション内 ($env:WT_SESSION 有) や
# WT 不在環境ではそのまま継続。
if (-not $env:WT_SESSION) {
  $wt = Get-Command wt.exe -ErrorAction SilentlyContinue
  if ($wt) {
    Write-Host "[bootstrap] Relaunching in Windows Terminal for proper CJK rendering..." -ForegroundColor Cyan
    # 引数転送 (RepoUrl が渡されていれば維持)
    $forward = @(
      "powershell.exe",
      "-NoExit",
      "-ExecutionPolicy", "Bypass",
      "-File", "`"$PSCommandPath`""
    )
    if ($PSBoundParameters.ContainsKey('RepoUrl') -and $RepoUrl) {
      $forward += @("-RepoUrl", "`"$RepoUrl`"")
    }
    # WT_SESSION を継承させないため明示的に新規プロセス起動
    Start-Process -FilePath $wt.Source -ArgumentList $forward | Out-Null
    exit 0
  } else {
    Write-Host "[bootstrap] Windows Terminal (wt) が見つかりません。" -ForegroundColor Yellow
    Write-Host "[bootstrap] 日本語が □ 表示される場合は次を実行してください:"   -ForegroundColor Yellow
    Write-Host "[bootstrap]   winget install --id Microsoft.WindowsTerminal"     -ForegroundColor Yellow
    Write-Host "[bootstrap] 続行します..." -ForegroundColor Yellow
  }
}

# --- コンソールエンコーディングを UTF-8 に統一 ---
# 原本 setup-github.bat と同じ方針 (chcp 65001) でコンソール CP を UTF-8 に固定。
# powershell -File で起動した子プロセスは親コンソールの CP を継承するが、
# [Console]::OutputEncoding は CP と必ずしも一致しないため両方を明示する。
# このスクリプトは BOM 付き UTF-8 で保存されているので、内部文字列 → UTF-8
# バイト → UTF-8 コンソール の流れで一貫し、□ 化を防ぐ。
$null = & chcp 65001
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$OutputEncoding           = [Console]::OutputEncoding

function Write-Header($text) {
  Write-Host ""
  Write-Host "============================================================" -ForegroundColor Cyan
  Write-Host " $text" -ForegroundColor Cyan
  Write-Host "============================================================" -ForegroundColor Cyan
}

function Write-Step($text) {
  Write-Host ""
  Write-Host "--- $text ---" -ForegroundColor Yellow
}

function Stop-OnError($message) {
  Write-Host ""
  Write-Host "============================================================" -ForegroundColor Red
  Write-Host " エラー: $message"                                            -ForegroundColor Red
  Write-Host " この画面の内容をコピーして Claude に伝えてください。"        -ForegroundColor Red
  Write-Host "============================================================" -ForegroundColor Red
  Read-Host "続行するには Enter キーを押してください"
  exit 1
}

# -------------------------------------------------------------
# 0. 前提チェック
# -------------------------------------------------------------
Write-Header "ソクウリ — GitHub アップロード補助スクリプト"

# git 存在チェック
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
  Stop-OnError "git コマンドが見つかりません。Git for Windows をインストールしてください。"
}

# 作業ディレクトリ確定
$WorkDir = "C:\sokuri"
if (-not (Test-Path $WorkDir)) {
  Stop-OnError "$WorkDir が存在しません。"
}
Set-Location $WorkDir

# RepoUrl 未指定なら対話入力
if ([string]::IsNullOrWhiteSpace($RepoUrl)) {
  Write-Host ""
  Write-Host " 事前に GitHub で「空のリポジトリ」を作成しておいてください。"
  Write-Host " (README / .gitignore / license は追加しないこと)"
  Write-Host ""
  Write-Host " 作成したリポジトリの URL を貼り付けて Enter を押してください。"
  Write-Host " 例: https://github.com/yourname/sokuri.git"
  Write-Host ""
  $RepoUrl = Read-Host "リポジトリURL"
}

if ([string]::IsNullOrWhiteSpace($RepoUrl)) {
  Stop-OnError "URL が入力されませんでした。もう一度実行してください。"
}

# 形式チェック (簡易)
if ($RepoUrl -notmatch '^https://github\.com/.+\.git$' -and
    $RepoUrl -notmatch '^git@github\.com:.+\.git$') {
  Write-Host ""
  Write-Host "[警告] URL が一般的な GitHub リポジトリ形式ではありません: $RepoUrl" -ForegroundColor Yellow
  $confirm = Read-Host "このまま続行しますか? (y/N)"
  if ($confirm -ne 'y' -and $confirm -ne 'Y') {
    Stop-OnError "ユーザーが中止しました。"
  }
}

# -------------------------------------------------------------
# 1. 既存 .git の初期化
# -------------------------------------------------------------
Write-Step "1/6 古い .git を初期化します"
if (Test-Path ".git") {
  try {
    Remove-Item -Recurse -Force ".git"
  } catch {
    Stop-OnError ".git の削除に失敗しました: $($_.Exception.Message)"
  }
}

# -------------------------------------------------------------
# 2. git init
# -------------------------------------------------------------
Write-Step "2/6 Git リポジトリを作成します"
git init
if ($LASTEXITCODE -ne 0) { Stop-OnError "git init に失敗しました。" }

# -------------------------------------------------------------
# 3. git add
# -------------------------------------------------------------
Write-Step "3/6 ファイルを登録します (node_modules 等は .gitignore で自動除外)"
git add .
if ($LASTEXITCODE -ne 0) { Stop-OnError "git add に失敗しました。" }

# -------------------------------------------------------------
# 4. commit
# -------------------------------------------------------------
Write-Step "4/6 コミットを作成します"
git -c user.email=ko.13.hei@gmail.com -c user.name=kohei commit -m "initial commit: sokuri"
if ($LASTEXITCODE -ne 0) { Stop-OnError "git commit に失敗しました。" }

# -------------------------------------------------------------
# 5. branch -M main
# -------------------------------------------------------------
Write-Step "5/6 ブランチ名を main にします"
git branch -M main
if ($LASTEXITCODE -ne 0) { Stop-OnError "git branch -M main に失敗しました。" }

# -------------------------------------------------------------
# 6. remote add + push
# -------------------------------------------------------------
Write-Step "6/6 GitHub へ送信します (ログイン画面が出たら認証してください)"

# 既存 origin があれば付け替え
$existingOrigin = git remote 2>$null | Where-Object { $_ -eq 'origin' }
if ($existingOrigin) {
  git remote set-url origin $RepoUrl
} else {
  git remote add origin $RepoUrl
}
if ($LASTEXITCODE -ne 0) { Stop-OnError "git remote 設定に失敗しました。" }

git push -u origin main
if ($LASTEXITCODE -ne 0) { Stop-OnError "git push に失敗しました。認証や URL を確認してください。" }

# -------------------------------------------------------------
# 完了
# -------------------------------------------------------------
Write-Header "完了しました"
Write-Host " GitHub のリポジトリページを再読み込みして"
Write-Host " ファイルが表示されていれば成功です。"
Write-Host " 次は Vercel での公開です (DEPLOY.md の手順2を参照)。"
Write-Host ""
Read-Host "続行するには Enter キーを押してください"
exit 0
