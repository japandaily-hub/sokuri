# r8 backend 修正（異常系）— 実装記録

対象: r8-abnormal.md の H3 / H2 / M3 / M4 / M1 / M5 / M6 / H4（backend 側）。
pytest: `799 passed` → **`811 passed`**（新規 12 件・`.venv\Scripts\python.exe -m pytest -q`、182〜185秒）。

## 変更ファイル

| ファイル | 内容 |
|---|---|
| `app/api/v1/endpoints/transactions.py` | H3 ガード（`_assert_txn_open` / `TRANSACTION_CLOSED_DETAIL`）、H2 `cancellation`、M4 `user_suspended`（詳細＋一覧はバッチ1クエリ `_suspended_user_ids`）、`_owner_email`→`_owner`、退会業者メールのトムストン非開示、`_lock_txn_rows` を services へ委譲 |
| `app/api/v1/endpoints/admin.py` | M5 `PATCH /admin/transactions/{id}/cancel`、H2 一覧 `cancelled_by`（`IN` の1クエリ） |
| `app/api/v1/endpoints/reductions.py` | M3 上限2回（`_MAX_REDUCTION_REQUESTS`） |
| `app/api/v1/endpoints/operator_profile.py` | M6 `DELETE /operator/me`、`/vendors`・`/vendors/{id}` から退会業者を除外 |
| `app/api/v1/endpoints/auth.py` / `app/api/deps.py` | M6 退会業者のログイン拒否・旧トークン即時失効（`deleted_at` ゲート） |
| `app/db/models/operator.py` / `alembic/versions/0030_operator_deleted_at.py` | M6 `operators.deleted_at`（索引付き・24字リビジョンID） |
| `app/services/case_lock.py` | `lock_transaction_rows`（Case→Transaction のロック規約を admin と共有。複製回避） |
| `app/services/{notify,line_notify,notify_dispatch}.py` | 運営キャンセル通知（「相手方により」→「運営の判断により」） |
| `app/api/v1/endpoints/case_photos.py` / `app/services/storage.py` | H4 detail の日本語化（HEIC の具体的な回避手順まで明示・入力値は反射しない） |
| `app/schemas_katadzuke.py` | 下記の契約追加 |
| `tests/test_r8_abnormal_guards.py`（新規） | H3/H2/M3/M4/M1/M5/M6 の回帰 12 件 |

## 最終契約

- `TransactionDetailOut`: `+cancellation: {cancelled_by: "user"|"operator"|"admin", reason: str|null, cancelled_at: datetime} | null`（`status=="cancelled"` のときのみ非 null）、`+user_suspended: bool`
- `TransactionListItem`: `+user_suspended: bool`
- `AdminTransactionListItem`: `+cancelled_by: str|null`
- `OperatorOut`（admin 一覧・業者自身の応答のみ。公開系は別スキーマ）: `+cancel_count: int`
- `POST /transactions/{id}/messages`・`POST /transactions/{id}/schedule/propose`: 409 `detail={"code":"transaction_closed","message":"この取引は終了しています。"}`（`messages/read` は 200 のまま）
- `POST /transactions/{id}/reduction`: 3回目は 409 `"減額申請は1つの取引につき2回までです。"`（未回答が残る間は従来どおり `"未回答の減額申請があります。回答をお待ちください。"` が優先）
- `PATCH /admin/transactions/{id}/cancel` body `{"reason": str(1..500)}` → 200 `{"id","status":"cancelled"}` / 409 `"キャンセルできる状態ではありません。"` / 404 `"成約情報が見つかりません。"` / 422（空文字）。`cancel_count` は加算しない。当事者双方へ通知
- `DELETE /operator/me` → 204 / 409 `"進行中の取引があるため退会できません。取引の完了またはキャンセル後に再度お試しください。"`。レート制限 `account_delete` 適用
- アップロード detail: 422 `"ファイルサイズが上限（10MB）を超えています。写真を縮小するか、別の写真をお試しください。"` / 415 `"この形式の画像には対応していません。JPEG・PNG・WebP のいずれかで…（HEIC は「設定 > カメラ > フォーマット > 互換性優先」で…）"` / 422 `"ファイルが空です。写真を選び直してお試しください。"` / presign 422 `"この形式の画像には対応していません。JPEG・PNG・WebP のいずれかを選択してください。"`

## 隣接・複製伝播チェック

- 取引への書き込み系を全走査: `complete` / `cancel` / `confirm_schedule` / `reduction` 系は既に status ガード済み、`reviews` は completed 限定。穴は `create_message` と `propose_schedule` の2つのみで、両方に同一定数のガードを入れた。
- ロック手順は複製せず `services/case_lock.lock_transaction_rows` に集約（`lock_case_row` を bids→services に移設したときと同じ判断）。
- 退会トムストンの非開示処理は依頼者側に既存（「退会済みユーザー」）。業者側にも同型（「退会済み業者」）を追加。

## 未対応・申し送り

1. **[要ユーザー判断] `DELETE /operator/me` に再認証が無い**（web 契約がボディ無し DELETE のため）。依頼者退会はパスワード再確認必須。トークン漏洩時の被害差が非対称なので、`/operator/reauth-token` を前段に置く形での追加を推奨。
2. `Operator.cancel_count` は admin 一覧に出したのみ。**自動停止・スコア反映は未実装**（運用ポリシー未定のため）。web 側文言「アカウント評価に影響します」は依然として実装より強い。
3. M2（キャンセル後の再出品導線）・M7（`Retry-After`）・H1（ログイン 429 の誤表示）は web 側担当のため未着手。
4. `0030_operator_deleted_at` は**本番未適用**。デプロイ時に alembic 実行ログで確認すること（テストは `create_all` のため migration 経路を通らない）。
5. 作業中に `tests/test_katadzuke_api.py` / `tests/test_txn_state_integrity.py` が**別セッションにより変更**されていた（未コミット・219行追加）。commit は pathspec 指定で本作業分のみに限定すること。
