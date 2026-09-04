# R3 バックエンド実装2 — 依頼者アカウント停止機能（ADD-2対応）

実施日: 2026-09-04 / 対応根拠: `.agent-state/audit/r3-verify-operator.md` ADD-2

## 実装内容

- `users` テーブルに `is_suspended`(bool, NOT NULL, default false, indexed) / `suspended_at`(datetime, null) /
  `suspended_reason`(string(200), null) を追加。`Operator.is_suspended` と同形。
- `GET /admin/users?q=&limit=&offset=`（`get_current_admin` 必須。既定50・上限200。
  `q` はメール/表示名(`User.name`)の部分一致。新しい順。`case_count` は N+1 回避のため
  `Case.user_id` の GROUP BY でバッチ集計）→ `{items, total}`。
- `PATCH /admin/users/{user_id}/suspend`（body: `suspended: bool`, `reason: str|null≤200`）→
  `{id, is_suspended, suspended_at}`。admin 自身・role="admin" のユーザーは 409。
- `deps.py` に `assert_user_not_suspended(user)` を新設し、`get_current_user` /
  `get_current_actor`(user分岐) の2箇所（＝依頼者トークンを検証する全経路）に追加。
  403 detail は契約どおり「このアカウントは利用停止中です。お問い合わせ窓口までご連絡ください。」。
- 隣接・複製伝播チェック: `auth.py` の `line_exchange`（Bearer付き連携経路の user 分岐）にも
  同ゲートを追加（`assert_user_not_revoked` と同じ箇所に既に呼ばれていたパターンを踏襲）。
  加えて `user_login` と `line_exchange` ケース2（LINE単独ログイン）にも停止時 403 を追加し、
  停止中に新規トークンが発行されないようにした（`operator_login` の既存挙動に合わせた防御的多重化）。
  公開API（`/vendors` 等）はこれらの経路を通らないため無影響（テストで確認）。
- alembic `0025_user_suspend`（up/down 実装済み、down_revision=0024）。

## notify.py の文言チェック（Block2 追加指示）

`backend/app/services/notify.py` を全文 grep したが「LINEにも」等の食い違う通知チャネル文言は
**現状存在しない**（`notify_dispatch.py` は既に LINE優先→メールフォールバックの正しい説明コメントに
統一済み。おそらく直前の別実装セッションの変更で既に是正されている）。追加修正は不要と判断し、
対応不要として記録する。

## pytest 結果

`.venv\Scripts\python.exe -m pytest -q` — **680 passed, 0 failed**（既存677 + 新規3件）。
新規テスト: `tests/test_admin_user_controls.py`
（`test_suspend_and_unsuspend_user` / `test_suspend_requires_admin_and_existing_user_and_rejects_admin_targets` /
`test_list_users_search_and_case_count`）。

## alembic ヘッド

CLI `alembic heads` は本環境既存の cp932 ロケール問題（`alembic.ini` 読込がPythonの
既定ロケールエンコーディングで固定されており、日本語パス環境で `UnicodeDecodeError`）で
実行不能（本タスクの変更とは無関係の環境要因）。`ScriptDirectory.get_heads()` で直接確認し、
単一ヘッド `0025_user_suspend`（`0024_operator_review_stats` を正しく継承）を確認済み。

## 変更ファイル一覧

- 新規: `backend/alembic/versions/0025_user_suspend.py`
- 新規: `backend/tests/test_admin_user_controls.py`
- `backend/app/db/models/user.py`（`is_suspended`/`suspended_at`/`suspended_reason` 追加）
- `backend/app/api/deps.py`（`assert_user_not_suspended` 新設・`get_current_user`/`get_current_actor` に追加）
- `backend/app/api/v1/endpoints/auth.py`（`line_exchange` user分岐・`user_login`・LINE単独ログインに停止ゲート追加）
- `backend/app/schemas_katadzuke.py`（`AdminUserListItem`/`AdminUserListResponse`/`UserSuspendRequest`/`UserSuspendResponse`）
- `backend/app/api/v1/endpoints/admin.py`（`GET /admin/users`・`PATCH /admin/users/{id}/suspend` 新設）

## 未対応と理由

- 停止解除時の `suspended_reason` はクリアする実装にした（契約に明記無いが、解除後に古い停止理由が
  残り続けるのは運用上の事故のもと。web側の表示に影響する場合は要調整）。
- admin 昇格経路（`_promote_to_admin_if_listed`）は停止判定より前に評価される設計は踏襲していない
  （停止判定を先に行い403で早期リターン。admin_emails 昇格対象者が同時に停止対象になるケースは
  想定外のため未検証）。

---

✅ 達成: is_suspended/suspended_at/suspended_reason 追加・admin一覧/停止API・deps.py全経路ゲート・
pytest 680 passed・alembic単一ヘッド(0025)確認済み。禁止ファイル（config.py/main.py/alert_middleware.py等・web/）は無変更。
⚠️ 課題: `alembic heads` CLIが環境要因（cp932）で直接実行不能（本タスク起因ではない・別途本環境整備が必要）。
❌ ブロッカー: なし。
