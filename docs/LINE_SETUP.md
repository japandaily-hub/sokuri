# カタヅケ LINE連携セットアップ手順（2026-09-04）

「LINEで通知を受け取る」と「LINEで続ける（ログイン）」を動かすための設定。
値を貼る場所は **Vercel（画面側）** と **Render（サーバー側）**、値の出どころは **LINE Developers の2チャネル**。

現状（2026-09-04 時点）: Vercel の `LINE_CLIENT_ID` / `LINE_CLIENT_SECRET` は設定済み。Render は `LINE_CLIENT_ID` 未設定（exchange が 503）・`LINE_CHANNEL_ACCESS_TOKEN` 未設定。

## 1. LINE Developers でプロバイダーと2チャネル
- https://developers.line.biz/console/
- プロバイダーを1つ（例: カタヅケ）。**LINEログイン**チャネルと **Messaging API** チャネルを同じプロバイダー配下に置く（別だと userId が変わり通知が届かない）。

## 2. LINEログインチャネル（LINEログイン設定タブ）
- コールバックURL に2行:
  - `https://sokuri.vercel.app/api/auth/callback/line`（ログイン）
  - `https://sokuri.vercel.app/api/line/link/callback`（通知連携）
- チャネルを「開発中」→「公開済み」へ（開発中だと管理者以外は「この機能は現在開発中です」）。
- チャネル基本設定の **チャネルID** を控える（Render に貼る。Vercel の LINE_CLIENT_ID と同じ）。
- メール取得権限は不要（scope は profile / openid）。

## 3. Messaging API チャネル（Messaging API設定タブ）
- **チャネルアクセストークン（長期）** を発行して控える（Render に貼る）。
- 応答メッセージは無効推奨。Webhook は不要。
- QRコード／ベーシックID（@…）を控える。**友だち追加していない人には push できない**。

## 4. Render（sokuri-backend → Environment → Edit）
| KEY | VALUE |
| :-- | :-- |
| `LINE_CLIENT_ID` | LINEログインチャネルのチャネルID |
| `LINE_CHANNEL_ACCESS_TOKEN` | Messaging API の長期アクセストークン |
- 「Save, rebuild, and deploy」。render.yaml に書いても既存サービスには反映されない（ダッシュボード必須）。

## 5. Vercel（sokuri → Settings → Environment Variables）
- `LINE_CLIENT_ID` / `LINE_CLIENT_SECRET`（設定済み）。
- 推奨: `APP_BASE_URL=https://sokuri.vercel.app` を追加して Redeploy。

## 6. 動作確認
```bash
curl -s -o NUL -w "%{http_code}" -X POST -H "Content-Type: application/json" -d "{\"line_access_token\":\"dummy\"}" https://sokuri-backend.onrender.com/api/v1/auth/line/exchange
```
503 → 401 に変われば Render 側 OK。その後: 友だち追加 → ログイン → /notifications「LINEで通知を受け取る」→ 許可 → 「LINE通知を受け取っています」。

## トラブルシュート
| 症状 | 原因 | 直し方 |
| :-- | :-- | :-- |
| LINE連携は現在ご利用いただけません | Render の LINE_CLIENT_ID 未設定（503） | 手順4 |
| この機能は現在開発中です | ログインチャネルが開発中 | 手順2（公開済み） |
| 400 redirect_uri | コールバックURL不一致 | 手順2の2行 |
| 連携成功なのに通知なし | 友だち未追加／TOKEN未設定／別プロバイダー | 手順3・4・1 |
| 既に別のアカウントと連携 | 同じLINEを別会員に紐づけ済み | 先に解除 |

根拠: `web/src/auth.ts`、`web/src/lib/line-link.ts`、`web/src/app/api/line/link/*`、`backend/app/config.py`、`backend/app/services/line_notify.py`。
