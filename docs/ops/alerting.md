# 運営向けアラート（障害・異常時の通知）

最終更新: 2026-09-04

## 全体像

| 層 | 何を検知するか | どこで動くか | 通知 |
|---|---|---|---|
| 外形監視 | バックエンド `/health`・`/readyz`（DB到達・alembic head 一致）、フロント `/` の 200 応答、応答遅延 | GitHub Actions `uptime-alert.yml`（5分毎） | 障害検知・復旧・遅延 |
| アプリ内監視 | 未処理例外、5xx 応答のバースト | FastAPI ミドルウェア `app/core/alert_middleware.py` | 即時（クールダウン付き） |

通知は 3 チャネルに同時送信し、**未設定のチャネルは自動的にスキップ**します。

| チャネル | 顧客向けとの分離 | 設定 |
|---|---|---|
| メール（Brevo） | アカウント共用可。差出人名は「カタヅケ監視」、宛先は運営の監視用アドレス | `BREVO_API_KEY`, `ALERT_EMAILS`（カンマ区切り）, `ALERT_MAIL_FROM`（任意） |
| LINE（Messaging API） | **顧客向け公式アカウントとは別チャネル**を作る。顧客向け配信枠・友だち一覧に混ぜない | `ALERT_LINE_CHANNEL_ACCESS_TOKEN`, `ALERT_LINE_USER_IDS`（運営の LINE ユーザーID、カンマ区切り） |
| Webhook | Slack / Discord の Incoming Webhook | `ALERT_WEBHOOK_URL` |

LINE Notify は 2025年3月に終了しているため、Messaging API の別チャネルを使います。運営メンバーの LINE ユーザーIDは、運営用公式アカウントを友だち追加してもらい、Webhook の `follow` イベントか LINE Developers の「チャネル基本設定 > あなたのユーザーID」で取得します。

## 設定場所

- **GitHub Actions（外形監視）**: リポジトリの Settings > Secrets and variables > Actions に上記の変数を登録。
- **Render（アプリ内監視）**: Render の Environment に同じ変数を登録（`render.yaml` の envVars は既存サービスに同期されないため、ダッシュボードで直接追加する）。加えて任意で `ALERT_COOLDOWN_SECONDS`（既定 600）、`ALERT_5XX_THRESHOLD`（既定 5）、`ALERT_5XX_WINDOW_SECONDS`（既定 300）。

## 検知条件

### 外形監視（`scripts/uptime_check.py`）
- `/health`: HTTP 200 かつ `status == "ok"`
- `/readyz`: HTTP 200 かつ `status == "ready"`、`db == "ok"`、`schema.alembic_version == schema.expected_head`
- フロント `/`: HTTP 200 かつ `<title>` を含む
- 応答時間 > `SLOW_MS`（既定 8000ms）は Warning

状態遷移で通知します（毎回は送りません）。
- up → down: `[CRITICAL] 障害検知`
- down 継続: `ALERT_REPEAT_EVERY`（既定 12 回＝約1時間）ごとに再通知
- down → up: `[RECOVERED] 復旧しました`
- 状態は `actions/cache` で持ち回します（キャッシュが消えた場合は「初回検知」として再通知されるだけで、取りこぼしはありません）。

### アプリ内監視（`app/core/alert_middleware.py`）
- 未処理例外: 1件で即通知（`key = unhandled:<path>`、同じパスはクールダウン中は再送しない）。例外はそのまま再送出され、既定の 500 応答は変わりません。
- 5xx バースト: 直近 `ALERT_5XX_WINDOW_SECONDS` 秒間に `ALERT_5XX_THRESHOLD` 件以上の 5xx（例外由来を含む）で通知（`key = 5xx-burst`）。
- `/health` と `/readyz` 自身の失敗は集計しません（外形監視が拾うため）。
- クールダウンはプロセス内メモリです。複数インスタンス時はインスタンス数ぶん届く可能性がありますが、取りこぼしよりは許容します。

## 動作確認手順

1. Secrets を登録後、Actions の「Uptime alert」を **Run workflow** で `force_notify = true` にして実行 → テスト通知が届くことを確認。
2. 疑似障害: `BACKEND_URL` を存在しない URL に変えた `workflow_dispatch` は用意していないため、ローカルで `BACKEND_URL=http://127.0.0.1:9 python scripts/uptime_check.py` を実行し、通知本文と `.uptime_state.json` の遷移（down → 復旧）を確認。
3. アプリ内監視: `backend/tests/test_alerts.py` で送信・クールダウン・バースト検知を自動テスト。実機では Render の環境変数を設定後、意図的に 500 を返すエンドポイントは無いため、ログに `alerts:` 行が出ることと、Webhook（Slack/Discord）で受信できることを確認。

## 今後の拡張候補
- 業務異常（AI解析の連続失敗、通知メール送信失敗、審査待ち業者・減額申請の放置日数）の日次サマリ
- Sentry 等の導入（スタックトレース・発生頻度の可視化）
- Vercel / Render のデプロイ失敗を GitHub Deployments のステータスから検知
