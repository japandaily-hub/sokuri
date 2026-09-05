# r10 backend 修正（2026-09-05）

対象台帳: `r10-verify-user.md`（ADD-M10）/ `r10-verify-vendor.md`（M4）/ `r10-verify-operator.md`（H-1・ADD-H1・H-2・H-3・M-1〜M-6）。
`.claude/worktrees/` は未編集。alembic 単一ヘッド = `0032_contact_messages`（33 リビジョン・SQLite で upgrade/downgrade 実機確認済み、ORM 列と完全一致）。

## 結論

- 契約 8 項目すべて実装。pytest **849 passed / 0 failed**（既存 819 + 新規 30、既存 4 件は契約変更に追随して更新）。
- 破壊的変更は `GET /admin/identity-documents` の応答形状のみ（list → `{items,total,counts}`）。web 側の同時切替が必須。
- `/readyz` の `config` に `alerts_line` / `alerts_webhook` を追加した結果、**本番で LINE/Webhook 未設定なら `degraded_config` が恒常的に非空**になる。`uptime_check` は遷移型なので通知は 1 回だけだが、運用意図の確認が要る（下記「要確認」）。

## 実装内容と最終契約

### 1. ADD-M10 案件の対応エリア（`POST /cases`）
`CaseCreateRequest.prefecture` を `ServiceAreaPrefecture = Literal["東京都","千葉県","埼玉県","神奈川県"]` に変更。対応エリア外・表記ゆれ（「東京」）・空文字は **422**。
`SERVICE_AREA_PREFECTURES` は `get_args()` で Literal から導出（二重定義のズレを構造的に排除）。
住所（`UserAddressUpdateRequest.prefecture`）は 47 都道府県のまま（居住地は圏外でもよい）。既存 seed / テストの案件値は「東京都」「神奈川県」のみで影響なし。

### 2. V-M4 減額申請の残回数（`GET /transactions/{id}`）
`TransactionDetailOut` に `reduction_request_count: int`（= `len(reduction_requests)`）と `reduction_request_limit: int = 2` を追加。
上限は `app/core/limits.py::MAX_REDUCTION_REQUESTS_PER_TRANSACTION` を単一の出所にし、409 を出す `reductions._MAX_REDUCTION_REQUESTS` と同一定数であることをテストで固定。

### 3. O-M1〜M4 本人確認一覧・提出通知・業者 counts
**`GET /admin/identity-documents`（応答形状の変更）**
```jsonc
{ "items": [UserIdentityDocumentAdminOut, ...],
  "total": 12,                                   // status + q の絞込に一致する全件数
  "counts": { "pending": 3, "approved": 8, "rejected": 1 } }  // status も q も反映しない全件内訳（バッジ用）
```
- クエリ: `status`（既定 pending / all 可）・`q`（依頼者メール・氏名の部分一致。`_escape_ilike_value` で `%` `_` を無害化）・`limit`（既定 100・最大 500）・`offset`。
- 並び: `submitted_at DESC, id DESC`（tie-breaker。ページ跨ぎの重複・欠落をテストで固定）。
- 退会済みユーザーの書類は items / total / counts の全経路で除外（従来の一覧と同条件）。
- `counts` が q を無視するのは `list_operators` の counts と同じ契約（検索中だけバッジが変わると絞込の解除忘れで審査漏れが起きるため）。

**提出時の admin 通知**: `notify.send_identity_submitted_admin_alert(to_email)` を新設し、`POST /users/me/identity-documents` の成功後に `BackgroundTasks` で ADMIN_EMAILS へ 1 宛先 1 通（`notify_dispatch` は経由しない）。**本文・件名に提出者の PII を一切含めない**（管理画面リンクのみ）。ADMIN_EMAILS 未設定時は `logger.warning`。

**`GET /admin/operators` の counts**: `pending_with_license`（pending かつ `license_image_uploaded_at IS NOT NULL`）を追加。判定式は `verify_operator` の 409 ゲートと同一。既存の GROUP BY 1 本に `SUM(CASE ...)` を足すだけで N+1 なし。

### 4. O-M5 依頼者一覧（`GET /admin/users`）
`suspended: bool | None`（true=停止中のみ / false=停止中以外 / 省略=絞り込まない）を追加。`include_deleted` は既存実装のまま（web 型の `Pick` 拡張が残作業）。監査ログに両パラメータを追記。

### 5. O-M6 お問い合わせの受信台帳
新テーブル `contact_messages`（alembic `0032_contact_messages`）: `id, name, email, category, message, handled_at NULL, handled_by_admin_id NULL(FK users ON DELETE SET NULL), created_at, updated_at`。索引は `email` と複合 `(handled_at, created_at)`（「未対応を新着順」を 1 本で賄う）。
- `POST /contact`: メール送信の**前**に保存。保存失敗でもメール送信と 202 は維持し、`logger.error` + `alerts.send_alert(key="contact-persist-failed")` で可視化（PII はログ・アラート本文に出さない）。既存のレート制限（IP 軸・アカウント軸・プロセス内キャップ 300/h・アラート閾値 30/h）は無変更。
- `GET /admin/contacts?handled=&limit=&offset=` → `{items,total}`。並びは `created_at DESC, id DESC`。
- `PATCH /admin/contacts/{id}/handle` → `{id, handled_at}`。**冪等**（既に対応済みなら上書きせず 200 で現状を返す＝最初の対応者・時刻を保持）。404 は存在しない ID。認可は `get_current_admin`（非 admin は 403 / 無認証は 401）。

### 6. O-H3(M) `/readyz`
`_config_readiness` に `alerts_line`（`ALERT_LINE_CHANNEL_ACCESS_TOKEN` **かつ** `ALERT_LINE_USER_IDS`。`alerts._send_line` が両方必須のため）と `alerts_webhook`（`ALERT_WEBHOOK_URL`）を追加。`degraded_config` は「False のキー」の集合なので自動的に含まれる。値は返さず bool のみ（無認証で読める payload のため）。

### 7. O-ADD-H1 / O-H2(M) `scripts/uptime_check.py`
- **通知全滅で `return 1`**: `notify()` を 1 回以上呼んだのに `sent` が空なら Step Summary に `**通知全滅**` を書いて exit 1（Actions を赤くし、workflow 失敗メールを最後の砦にする）。通知不要の正常時は `notify()` を呼ばないため掛からない。docstring の「終了コード: 常に 0」を改訂。
- **`degraded_config` の warning**: `CheckResult` に `degraded_config: list[str]` を追加。`/readyz` が ok の実行でのみ前回値と比較し、**変化時のみ** Warning（空に戻ったら解消通知 1 回）。`/readyz` が NG の実行は判定をスキップし前回値を据え置く（「解消した」の誤検知防止）。状態は `STATE_FILE` に `degraded_config` として持ち回す。
- `docs/ops/alerting.md` の「検知条件 > 外形監視」「状態遷移」「デッドマンスイッチ」節に追記。

### 8. O-H-1 backend 側
通知リンク先は `/chat/{id}`（依頼者）/ `/operator/transactions/{id}`（業者）のまま**変更なし**。`send_transaction_cancelled`（当事者間）と `send_transaction_cancelled_by_admin`（運営の強制終了）の本文に「キャンセルの理由は、下のリンク先の画面でご確認いただけます。」を 1 行追加し、リンク文言を両方「詳細と理由を確認する」に統一（理由の描画は web 側）。

## テスト

`backend/tests/test_r10_backend_fixes.py`（新規 30 件）
- 対応エリア: 4 都県で 201 / 圏外・表記ゆれ・空文字で 422 / 住所は 47 都道府県のまま 200。
- 本人確認一覧: items+total+counts、q（メール／氏名／`%` のエスケープ）、審査後の counts 遷移、同時刻 3 件のページ跨ぎ tie-breaker、提出時の ADMIN_EMAILS 宛通知（1 宛先 1 通・順序）、通知本文に PII が無いこと。
- 業者 counts: `pending_with_license` が「pending かつ許可証あり」のみを数える（active の提出済みは含めない）。
- 依頼者一覧: `suspended` true/false/省略 と `include_deleted`。
- 問い合わせ: ADMIN_EMAILS 未設定でも DB に残る／既存のメール送信が維持される／一覧の handled 絞込・handle の冪等・404・403/401。
- `/readyz`: `alerts_line` は token と user_ids の両方が必要、`alerts_webhook`。
- `uptime_check`: 通知全滅 → 1、1 チャネル成功 → 0、通知不要 → 0（notify 未呼出）、degraded_config の遷移型通知、`/readyz` 到達不能時に解消通知を出さないこと。

既存テストの更新（契約変更への追随のみ・仕様は不変）: `test_admin_notifications_r6.py`（config キー集合）、`test_admin_operator_controls.py`（counts に 1 キー）、`test_user_identity.py` × 2（一覧が `{items,...}` に）。

## 変更ファイル

新規
- `backend/app/db/models/contact_message.py`
- `backend/alembic/versions/0032_contact_messages.py`
- `backend/tests/test_r10_backend_fixes.py`

変更
- `backend/app/schemas_katadzuke.py` / `backend/app/core/limits.py`
- `backend/app/api/v1/endpoints/admin.py` / `contact.py` / `user_identity.py` / `transactions.py` / `reductions.py`
- `backend/app/services/notify.py` / `backend/app/main.py` / `backend/app/db/models/__init__.py`
- `backend/tests/conftest.py` / `test_admin_notifications_r6.py` / `test_admin_operator_controls.py` / `test_user_identity.py`
- `scripts/uptime_check.py` / `docs/ops/alerting.md`

## web 担当への引き渡し（同時切替が必要）

1. `GET /admin/identity-documents` は **配列を返さない**。`res.items` / `res.total` / `res.counts.{pending,approved,rejected}` へ。Pager の上限は `total` で閉じること。`?q=` を検索ボックスに配線。
2. `GET /admin/operators` の `counts.pending_with_license` を「いま承認できる件数」としてバッジに追加（`pending` との差分＝許可証提出待ち）。
3. `GET /admin/users` の `AdminListParams` の `Pick` を `include_deleted` / `suspended` まで拡張（backend は実装済み）。
4. `/admin/contacts` 画面（一覧＋「対応済みにする」）の新設。
5. `TransactionDetail` に `reduction_request_count` / `reduction_request_limit` を追加し、業者側に残回数を表示。
6. チャット画面（`/chat/[id]`）への `cancellation` 描画（O-H-1 の本体。メール本文は「リンク先で理由を読める」と約束済み）。

## 未対応 / 要確認

- **[要確認] `alerts_webhook` を degraded 扱いにする是非**: アラート経路はメール・LINE・Webhook の代替関係にあり、Webhook を使わない運用なら `degraded_config` が常時非空になる。契約通り実装したが、運用意図が「3 経路すべて必須」でないなら `alerts_webhook` は `config` に出しつつ `degraded_config` からは外す（＝常に True 扱い）方が通知の S/N は良い。
- **ADD-H2（Brevo が 201 を返して受理後に破棄する経路）は未対応**。契約外のため着手せず。`GET /v3/smtp/statistics/events` の日次チェックが台帳の提案。
- **O-M7 / M-8 / M-9（ドキュメント系・Low）は未対応**（契約外）。
- `counts` が q を無視する点は `list_operators` に合わせた判断。検索結果の内訳が欲しいという要件が web 側に出たら再協議。
- `/contact` の DB 保存は既存セッション（`get_session`）で commit する。**保存とメール送信は非トランザクショナル**（保存失敗でもメールは飛ぶ）。取りこぼし最小化を優先した意図的な設計。
- 本番 DB へのマイグレーション適用（`0032`）は未実施。デプロイ後に `/readyz` の `schema.alembic_version == expected_head` で確認すること。

## サマリ

- ✅ 契約 8 項目すべて実装・pytest 849 passed（新規 30）・alembic 単一ヘッド 0032（SQLite で upgrade/downgrade 実機確認）
- ⚠️ `GET /admin/identity-documents` は破壊的変更（web 同時切替必須）。`alerts_webhook` の degraded 扱いは運用意図の確認待ち
- ❌ ADD-H2（Brevo の 201 後破棄）と M-7〜M-9（文書系）は契約外のため未対応
