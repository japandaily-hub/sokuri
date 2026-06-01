# OneDrive 配下の Claude-appdata-backup から不要キャッシュを削除する。
#
# 直前の robocopy で 15 GB のキャッシュが残っているため、ここで除去する。

$dst = "C:\Users\$env:USERNAME\OneDrive\ドキュメント\Claude\Projects\ソクウリ\sokuri-migration\Claude-appdata-backup"
$log = "C:\sokuri\cleanup_log.txt"

"=== cleanup START: $(Get-Date -Format o) ===" | Out-File $log -Encoding UTF8

if (-not (Test-Path $dst)) {
    "ERROR: $dst not found" | Out-File $log -Append -Encoding UTF8
    exit 1
}

$excludeDirs = @(
    "Cache", "Code Cache", "GPUCache", "DawnGraphiteCache", "DawnWebGPUCache",
    "Crashpad", "IndexedDB", "Network", "Session Storage", "Local Storage",
    "Shared Dictionary", "SharedStorage", "WebStorage", "blob_storage",
    "Partitions", "ChromeNativeHost", "DIPS", "DIPS-wal", "SharedStorage-wal",
    "logs", "fcache", "pending-uploads", "vm_bundles", "claude-code-vm",
    "sentry"
)

foreach ($d in $excludeDirs) {
    $path = Join-Path $dst $d
    if (Test-Path $path) {
        try {
            $size = [math]::Round(((Get-ChildItem $path -Recurse -ErrorAction SilentlyContinue |
                Measure-Object -Property Length -Sum).Sum / 1MB), 1)
            Remove-Item -Path $path -Recurse -Force -ErrorAction Stop
            "DELETED: $d ($size MB)" | Out-File $log -Append -Encoding UTF8
        } catch {
            "FAILED: $d - $($_.Exception.Message)" | Out-File $log -Append -Encoding UTF8
        }
    } else {
        "SKIP (not present): $d" | Out-File $log -Append -Encoding UTF8
    }
}

# 結果サイズ
try {
    $sizeMB = [math]::Round(((Get-ChildItem $dst -Recurse -ErrorAction SilentlyContinue |
        Measure-Object -Property Length -Sum).Sum / 1MB), 1)
    "FINAL_DST_SIZE: $sizeMB MB" | Out-File $log -Append -Encoding UTF8
} catch {}

"=== cleanup END: $(Get-Date -Format o) ===" | Out-File $log -Append -Encoding UTF8
