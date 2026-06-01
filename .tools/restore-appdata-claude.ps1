# 新 PC で Claude desktop の memory / plugins / settings を復元する。
#
# 前提:
# - 新 PC で Claude desktop をインストール済み（少なくとも 1 回起動して package container を作成済み）
# - OneDrive sync が完了し sokuri-migration\Claude-appdata-backup が手元にある
# - Claude desktop は終了している（ファイルロック回避）
#
# 使い方:
#   1. Claude desktop を完全終了（タスクトレイ → Exit）
#   2. powershell -ExecutionPolicy Bypass -File C:\sokuri\.tools\restore-appdata-claude.ps1

$log = "C:\sokuri\restore_appdata_log.txt"
"=== restore START: $(Get-Date -Format o) ===" | Out-File $log -Encoding UTF8

# Source: OneDrive sync された backup
$src = "C:\Users\$env:USERNAME\OneDrive\ドキュメント\Claude\Projects\ソクウリ\sokuri-migration\Claude-appdata-backup"
if (-not (Test-Path $src)) {
    "ERROR: backup not found at $src" | Out-File $log -Append -Encoding UTF8
    "Hint: OneDrive sync が完了しているか確認してください" | Out-File $log -Append -Encoding UTF8
    exit 1
}
"SRC: $src" | Out-File $log -Append -Encoding UTF8

# Destination: 新 PC の Claude UWP container を探す
$pkgRoot = Get-ChildItem "$env:LOCALAPPDATA\Packages" -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "Claude_*" } |
    Select-Object -First 1
if (-not $pkgRoot) {
    "ERROR: Claude UWP package not found" | Out-File $log -Append -Encoding UTF8
    "Hint: Claude desktop を 1 度起動してから終了してください" | Out-File $log -Append -Encoding UTF8
    exit 1
}
$dst = Join-Path $pkgRoot.FullName "LocalCache\Roaming\Claude"
"DST: $dst (package: $($pkgRoot.Name))" | Out-File $log -Append -Encoding UTF8

# Claude desktop プロセス確認（起動中なら警告）
$running = Get-Process -Name "Claude*" -ErrorAction SilentlyContinue
if ($running) {
    "WARN: Claude プロセスが起動中です。終了してから再実行してください。" | Out-File $log -Append -Encoding UTF8
    "Running processes:" | Out-File $log -Append -Encoding UTF8
    $running | ForEach-Object { "  $($_.ProcessName) (PID $($_.Id))" } | Out-File $log -Append -Encoding UTF8
    exit 2
}

# robocopy で復元（ロックされていなければ全部上書き、/MIR ではなく /E で既存を残しつつ上書き）
# 既存の cache 等を消したくないため /MIR は使わない
$rcArgs = @($src, $dst, "/E", "/R:0", "/W:0", "/MT:8", "/XJ",
            "/NFL", "/NDL", "/NJH", "/NJS", "/NP")
$proc = Start-Process -FilePath robocopy -ArgumentList $rcArgs -NoNewWindow -Wait -PassThru
$exit = $proc.ExitCode
"ROBOCOPY EXIT: $exit" | Out-File $log -Append -Encoding UTF8
if ($exit -le 3) {
    "RESULT: OK — restore 完了" | Out-File $log -Append -Encoding UTF8
} elseif ($exit -le 7) {
    "RESULT: WARN (一部の差分のみ)" | Out-File $log -Append -Encoding UTF8
} else {
    "RESULT: ERROR (一部失敗 — Claude desktop が起動中かファイルロックの可能性)" | Out-File $log -Append -Encoding UTF8
}

"=== restore END: $(Get-Date -Format o) ===" | Out-File $log -Append -Encoding UTF8
"次の手順: Claude desktop を起動すれば memory / plugins が復元された状態で開きます。" | Out-File $log -Append -Encoding UTF8
