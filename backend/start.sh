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

# ── 本番デフォルト値の注入（render.yaml の envVars は既存サービスに反映されない）──
# 2026-07-18 に実測して判明: render.yaml の envVars に「新しいキーを追記して push」
# しても、既に作成済みの Render サービスには同期されない（Blueprint を再適用しない限り
# 反映されない）。実際 TRUSTED_PROXY_HOPS=3 を render.yaml に書いてデプロイしても、
# アプリ側は未設定＝コード既定値(1) のままだった（/api/v1/_diag/client-ip で実測）。
# そのため「本番でこの値である必要がある」設定は、git で確実に届くこのスクリプトで
# 既定値を与える。dashboard で明示設定された値があればそちらが優先される（:- 展開）。
#
# TRUSTED_PROXY_HOPS: X-Forwarded-For の右から何番目を実クライアントIPとみなすか。
#   本番実測（2026-07-18）の連鎖は3段:
#     client(133.106.x) → Cloudflare(162.159.x/172.6x.x) → Render内部(10.x)
#   1 のままだと末尾の Render 内部IPを掴み、全ユーザーが同一バケットを共有する
#   「認証全断」モードに入る（現在は is_private_or_loopback でIP軸スキップへ退避する
#   ため全断はしないが、IP軸の保護が失われる）。
#   ⚠️ 変更時は必ず /api/v1/_diag/client-ip で resolved_ip が実クライアントIPに
#   なることを実測してから確定すること。過大にすると偽装可能になる。
export TRUSTED_PROXY_HOPS="${TRUSTED_PROXY_HOPS:-3}"

# RATE_LIMIT_ENABLED: 認証系レート制限の緊急無効化スイッチ。
#   コード既定値も true（セキュア・バイ・デフォルト）だが、ここに明示しておくことで
#   「障害時にどこを触れば止まるか」を起動経路上に可視化する。
#   ⚠️ 緊急停止は Render dashboard で RATE_LIMIT_ENABLED=false を設定する
#   （render.yaml を false にしても上記のとおり既存サービスには反映されない）。
export RATE_LIMIT_ENABLED="${RATE_LIMIT_ENABLED:-true}"

echo "[start.sh] rate limit: enabled=${RATE_LIMIT_ENABLED} trusted_proxy_hops=${TRUSTED_PROXY_HOPS}"

# マイグレーション失敗でも uvicorn は必ず起動する（2026-07 全断障害の教訓）。
# 旧設計は「alembic 失敗 → set -e で即終了 → uvicorn 未起動 → クラッシュループ」で、
# DB 側の一時/恒久障害（無料PG期限切れ等）がサービス全断（/health 含む）に増幅されていた。
# 起動を止めず degraded で立ち上げれば、/health は返り、Render のログも読める。
# DB 到達性は /readyz（app/main.py）で判別する。
# リトライ付き（最大3回・5秒間隔）: DB差し替え/プロビジョニング直後は数秒間
# 接続を受け付けないことがあり、1発勝負だと「その後DBが復帰しても次の再起動まで
# スキーマが空のまま degraded で走り続ける」罠になる（2026-07-16 に実際に発生）。
# 出力は /tmp/alembic-last.log にも保存する。Render無料プランはログ保持が短く
# CLI/API未接続だと読めないため、/readyz が(スキーマ未達時のみ・URLリダクト付きで)
# このファイル末尾を返し、マイグレーション失敗の実トレースバックを外形観測可能にする。
# 注: POSIX sh に pipefail が無いため tee は使わず、リダイレクト後に cat でログへ転写する。
echo "[start.sh] Running alembic migrations..."
attempt=1
until alembic upgrade head > /tmp/alembic-last.log 2>&1; do
  cat /tmp/alembic-last.log >&2
  if [ "$attempt" -ge 3 ]; then
    echo "[start.sh] WARN: alembic migration failed after ${attempt} attempts. Starting uvicorn anyway (degraded)." >&2
    echo "[start.sh] WARN: DB-dependent APIs will fail; check /readyz and DATABASE_URL / DB status." >&2
    break
  fi
  echo "[start.sh] WARN: alembic attempt ${attempt} failed; retrying in 5s..." >&2
  attempt=$((attempt+1))
  sleep 5
done
cat /tmp/alembic-last.log

echo "[start.sh] Launching uvicorn on port ${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
