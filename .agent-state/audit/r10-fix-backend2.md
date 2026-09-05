# r10 backend 追加修正（2026-09-05）

引き渡し3件（`r10-fix-frontend-ops.md` 未対応1・2 / `r10-fix-backend.md` 要確認）を実装。

## 実装内容

1. **`AdminUserListItem.deleted_at: datetime | None`**（`GET /admin/users`）
   - `admin.py::admin_list_users` で `u.deleted_at` を詰める。web の「退会済みを含む」トグルで
     どの行が退会済みかを判別できるようにする（従来は任意フィールドで受けても常に欠落していた）。
2. **`TransactionListItem.visit_time_slot: str | None`**（`GET /transactions`・依頼者/業者共通）
   - `Transaction.visit_time_slot`（既存カラム）をそのまま公開。`TransactionDetailOut` と同じ
     契約に揃え、一覧でも時間帯を表示できるようにした。
3. **`/readyz` の `degraded_config` から `alerts_webhook` を除外**
   - `app/main.py` に `_DEGRADED_CONFIG_EXEMPT_KEYS` を新設し、`degraded_config` 算出時に除外。
     `config.alerts_webhook` の bool 表示は維持（LINE/メールが代替経路のため単体未設定は劣化ではない）。
   - `docs/ops/alerting.md`「検知条件 > 外形監視」を追記修正。

## テスト

`backend/tests/test_r10_backend_fixes.py` に追加（既存クラスへの追記2件＋新規2件）
- `TestAdminUserListFilters`: include_deleted 時に `deleted_at` が正しく出ること。
- `TestTransactionListVisitTimeSlot`（新規）: 日程確定前は None・確定後は値を持つことを
  依頼者・業者双方の一覧応答で確認。
- `TestConfigReadinessAlerts.test_readyz_degraded_config_excludes_alerts_webhook`（新規）:
  `/readyz` 実エンドポイントで `alerts_webhook` 未設定でも `degraded_config` に出ないこと・
  `alerts_line` は従来通り degraded 対象であること。

## 変更ファイル

- `backend/app/main.py`
- `backend/app/schemas_katadzuke.py`
- `backend/app/api/v1/endpoints/admin.py`
- `backend/app/api/v1/endpoints/transactions.py`
- `backend/tests/test_r10_backend_fixes.py`
- `docs/ops/alerting.md`

## 結果

pytest **851 passed / 0 failed**（既存849 + 新規2 + 既存2件への追記）。
