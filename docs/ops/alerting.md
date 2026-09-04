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

## 最短の設定手順（1コマンド）

1. `.env.alerts.example` を `.env.alerts` にコピーし、値を埋める（このファイルは gitignore 済み）。
   - GitHub の Fine-grained PAT（対象: このリポジトリ、権限: Secrets と Actions を Read and write）
   - Render の API キー
   - 通知先（メール／LINE／Webhook のうち使うもの）
2. 実行:
   ```
   backend\.venv\Scripts\python.exe scripts\setup_alerts.py
   ```
   値の検証（LINE トークン・Brevo キーの疎通込み）→ GitHub Secrets 登録 → Render 環境変数登録（自動再デプロイ）→ Actions「Uptime alert」をテスト通知付きで起動し結果を表示、まで自動で行います。`--dry-run` で登録前の確認だけもできます。
3. メール／LINE／Webhook に「[カタヅケ監視][TEST] 疎通テスト」が届けば完了。
   - `setup_alerts.py` は実行ごとに `force_notify=true` で起動するため、**実行した回数ぶんテスト通知が届く**（設定を何度もやり直すとその都度メールが来る）。テスト通知は手動実行専用で、定期実行では送られない。

人手で必要なのは「運営用 LINE 公式アカウントの作成（顧客向けとは別）」「PAT と API キーの発行」「`.env.alerts` への記入」の3点だけです。

## 設定場所（手動で行う場合）

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
- 応答遅延（Warning）も遷移型: 遅くなった時に 1 回、通常速度に戻った時に `[INFO] 解消` を 1 回。遅い間の再送はしない
- **正常時は何も送らない**（5分毎のチェック結果はメールされず、Actions の Step Summary にだけ残る）
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

## Brevo（メール）で実際に詰まった点と対処（2026-09-04）
- **API キーの「Authorised IPs」制限**: 有効だと GitHub Actions / Render など固定IPでない送信元が全て 401 になる。Brevo の Security > Authorised IPs を無効にする。
- **差出人の認証**: 未認証の差出人からの送信は Brevo が受理後に「rejected（sender not validated）」で捨てる（API は 201 を返すので気づきにくい）。差出人は Senders に追加し、届く6桁コードで認証する。差出人の追加・認証 API は未登録IPを常に拒否するため、認証は Brevo の画面で行う。
- **本番の差出人**: `noreply@katadzuke.jp` はドメイン未認証のため送れない。当面 Render の `MAIL_FROM` と `ALERT_MAIL_FROM` を認証済みの `katazuke.support@gmail.com` にしている。katadzuke.jp を Brevo でドメイン認証（DNS に DKIM/SPF 追加）したら `noreply@katadzuke.jp` に戻せる。
- 配信結果は `GET /v3/smtp/statistics/events?email=<宛先>` で確認できる（`requests`→`delivered` なら到達、`error` なら理由が出る）。

## 今後の拡張候補
- 業務異常（AI解析の連続失敗、通知メール送信失敗、審査待ち業者・減額申請の放置日数）の日次サマリ
- Sentry 等の導入（スタックトレース・発生頻度の可視化）
- Vercel / Render のデプロイ失敗を GitHub Deployments のステータスから検知
