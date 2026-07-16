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

# マイグレーション失敗でも uvicorn は必ず起動する（2026-07 全断障害の教訓）。
# 旧設計は「alembic 失敗 → set -e で即終了 → uvicorn 未起動 → クラッシュループ」で、
# DB 側の一時/恒久障害（無料PG期限切れ等）がサービス全断（/health 含む）に増幅されていた。
# 起動を止めず degraded で立ち上げれば、/health は返り、Render のログも読める。
# DB 到達性は /readyz（app/main.py）で判別する。
# リトライ付き（最大3回・5秒間隔）: DB差し替え/プロビジョニング直後は数秒間
# 接続を受け付けないことがあり、1発勝負だと「その後DBが復帰しても次の再起動まで
# スキーマが空のまま degraded で走り続ける」罠になる（2026-07-16 に実際に発生）。
echo "[start.sh] Running alembic migrations..."
attempt=1
until alembic upgrade head; do
  if [ "$attempt" -ge 3 ]; then
    echo "[start.sh] WARN: alembic migration failed after ${attempt} attempts. Starting uvicorn anyway (degraded)." >&2
    echo "[start.sh] WARN: DB-dependent APIs will fail; check /readyz and DATABASE_URL / DB status." >&2
    break
  fi
  echo "[start.sh] WARN: alembic attempt ${attempt} failed; retrying in 5s..." >&2
  attempt=$((attempt+1))
  sleep 5
done

echo "[start.sh] Launching uvicorn on port ${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
