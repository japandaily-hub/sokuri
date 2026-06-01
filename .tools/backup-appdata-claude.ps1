# Claude AppData の **必要部分のみ** を OneDrive sokuri-migration 配下にバックアップ。
#
# 設計判断:
# - Electron の Cache / GPUCache / IndexedDB / Crashpad 等は再生成可能な「ゴミ」で
#   サイズが 15 GB 級になり OneDrive sync が事実上不可能。/XD で除外する。
# - 移行に本当に必要なのは:
#     local-agent-mode-sessions/   ← memory・plugins・skills
#     *.json (config 系)           ← Claude desktop の設定
# - 既存の robocopy が走っている場合は kill してから再実行
#
# 使い方:
#   powershell -ExecutionPolicy Bypass -File C:\sokuri\.tools\backup-appdata-claude.ps1

# 既存 robocopy を kill（前回のフル backup が走っている場合）
Get-Process robocopy -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

# UWP container 配下を自動解決
$pkgRoot = Get-ChildItem "$env:LOCALAPPDATA\Packages" -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "Claude_*" } |
    Select-Object -First 1
if ($pkgRoot) {
    $src = Join-Path $pkgRoot.FullName "LocalCache\Roaming\Claude"
} else {
    $src = "$env:APPDATA\Claude"
}
$dst = "C:\Users\$env:USERNAME\OneDrive\ドキュメント\Claude\Projects\ソクウリ\sokuri-migration\Claude-appdata-backup"
$log = "C:\sokuri\appdata_backup_log.txt"

"=== AppData backup START: $(Get-Date -Format o) ===" | Out-File -FilePath $log -Encoding UTF8
"SRC: $src" | Out-File -FilePath $log -Append -Encoding UTF8
"DST: $dst" | Out-File -FilePath $log -Append -Encoding UTF8

if (-not (Test-Path $src)) {
    "ERROR: source not found" | Out-File -FilePath $log -Append -Encoding UTF8
    exit 1
}

# 除外する Electron / Chromium のキャッシュ系（再生成可能）
$excludeDirs = @(
    "Cache", "Code Cache", "GPUCache", "DawnGraphiteCache", "DawnWebGPUCache",
    "Crashpad", "IndexedDB", "Network", "Session Storage", "Local Storage",
    "Shared Dictionary", "SharedStorage", "WebStorage", "blob_storage",
    "Partitions", "ChromeNativeHost", "DIPS", "DIPS-wal", "SharedStorage-wal",
    "logs", "fcache", "pending-uploads", "vm_bundles", "claude-code-vm",
    "sentry"
)
"EXCLUDED dirs: $($excludeDirs -join ', ')" | Out-File -FilePath $log -Append -Encoding UTF8

# 出力先を一度クリーンにしてから再 mirror（前回 15GB の残骸を削除）
if (Test-Path $dst) {
    "Removing previous full backup at $dst (may take a moment)..." | Out-File -FilePath $log -Append -Encoding UTF8
    Remove-Item -Path $dst -Recurse -Force -ErrorAction SilentlyContinue
}
New-Item -ItemType Directory -Path $dst -Force | Out-Null

# robocopy with /XD 除外
$rcArgs = @($src, $dst, "/MIR", "/R:0", "/W:0", "/MT:8", "/XJ",
            "/NFL", "/NDL", "/NJH", "/NJS", "/NP")
foreach ($d in $excludeDirs) {
    $rcArgs += "/XD"
    $rcArgs += (Join-Path $src $d)
}
"COMMAND: robocopy with $($excludeDirs.Count) exclusions" | Out-File -FilePath $log -Append -Encoding UTF8

$proc = Start-Process -FilePath robocopy -ArgumentList $rcArgs -NoNewWindow -Wait -PassThru
$exit = $proc.ExitCode
"ROBOCOPY EXIT: $exit" | Out-File -FilePath $log -Append -Encoding UTF8

if ($exit -le 3) {
    "RESULT: OK" | Out-File -FilePath $log -Append -Encoding UTF8
} elseif ($exit -le 7) {
    "RESULT: WARN (mismatched/extra)" | Out-File -FilePath $log -Append -Encoding UTF8
} else {
    "RESULT: ERROR (som