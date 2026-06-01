# CI と同じ syntax-guard をローカルで実行する（push 前の予防チェック）。
#
# 検出するもの:
#   - SyntaxError （estimate.py / seed.py で踏んだ orphan fragment 系）
#   - null bytes （ファイル書き換え時にトレーラーが残るバグ）
#
# 使い方:
#   powershell -ExecutionPolicy Bypass -File C:\sokuri\.tools\syntax-guard.ps1

$ErrorActionPreference = "Stop"
Set-Location C:\sokuri\backend

$py = @"
import ast, sys, pathlib
fail = 0
roots = ['app', 'alembic']
for root in roots:
    for path in pathlib.Path(root).rglob('*.py'):
        data = path.read_bytes()
        if b'\x00' in data:
            print(f'NULL_BYTES: {path} ({data.count(chr(0).encode())} bytes)')
            fail = 1
            continue
        try:
            ast.parse(data)
        except SyntaxError as e:
            print(f'SYNTAX_ERROR: {path}:{e.lineno}: {e.msg}')
            fail = 1
sys.exit(fail)
"@

$tmp = New-TemporaryFile
$py | Out-File -FilePath $tmp.FullName -Encoding UTF8
try {
    python $tmp.FullName
    if ($LASTEXITCODE -eq 0) {
        Write-Host "syntax-guard: OK (no issues)" -ForegroundColor Green
    } else {
        Write-Host "syntax-guard: FAIL — 上記ファイルを修正してから push してください" -ForegroundColor Red
        exit 1
    }
} finally {
    Remove-Item $tmp.FullName -Force
}
