#!/bin/sh
# Render / Docker 起動エントリポイント。
#
# 設計判断:
# - Render の dockerCommand に sh -c "..." を直接渡すと argv 解釈が壊れる
#   （exit 127: コマンド全体を「ファイル名」として解釈される）ため、
#   スクリプトファイルに切り出してから ENTRYPOINT/CMD で呼ぶ。
# - $PORT は Render が自動注入する。未定義時は 8000 にフォールバック。
# - alembic 失敗時は uvicorn を起動しない（set -e でプロセス終了 → Render が再試行）。

set -e

echo "[start.sh] Running alembic migrations..."
alembic upgrade head

echo "[start.sh] Launching uvicorn on port ${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
