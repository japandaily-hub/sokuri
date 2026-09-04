# r6-verify-fix 残課題の修正（backend4）— 2026-09-05

結論: N1/M4/M5/M2/M1 の5件をすべて実装済み。pytest 全件通過（789 passed）。alembic は単一ヘッド `0029_case_idempotency_unique`。
M2 は「同じ流儀」の解釈を拡張し、DB制約違反時のIntegrityErrorをcreate_caseで200/409へ多層防御で変換（reductions.pyと同型）。
M1 は bids.select_bid / cases.cancel_case と同じ「ロック前に軽量な当事者性照会」パターンを新規ヘルパー `_assert_party_before_lock` として3遷移に適用。

## pytest 結果
`789 passed, 793 warnings in 207.11s`（全件、失敗0）。
新規テスト2件（M4）追加後の再実行値。追加前は1件失敗（既存の `test_unverify_operator_notifies_with_inactive_flag` が新仕様と不整合、下記参照）。

## 変更ファイル
- `backend/app/main.py` — N1: lifespan内で `asyncio.create_task` の戻り値を `_startup_tasks` (set) に保持し done_callback で discard（alerts.pyと同型）。
- `backend/app/api/v1/endpoints/admin.py` — M4: verify/suspend の前値を保持し、状態が実際に変わった時だけ `background.add_task`。
- `backend/app/api/v1/endpoints/reductions.py` — M5: 誤コメント（「部分一意索引はPostgreSQL専用」）を実装（sqlite_where併記・両対応）に合わせて修正。
- `backend/app/db/models/case.py` — M2: `UniqueConstraint("user_id","idempotency_key", name="uq_cases_user_id_idempotency_key")` を追加、旧コメント（DB制約を張らない旨）を是正。
- `backend/app/api/v1/endpoints/cases.py` — M2: `create_case` の `except IntegrityError` を分岐し、idempotency制約違反は既存案件を200で返却（見つからなければ409）。
- `backend/alembic/versions/0029_case_idempotency_unique.py`（新規）— M2: 0028と同流儀（重複を止めずに自動是正）。ただし`cases`は業務データ本体のためDELETEせず、最古1行以外の`idempotency_key`をNULL化してから制約を張る。
- `backend/app/api/v1/endpoints/transactions.py` — M1: `_assert_party_before_lock`（当事者性の軽量事前照会）を新設し、complete/cancel/confirm_scheduleの3箇所で`_lock_txn_rows`より前に呼び出す。
- `backend/tests/test_admin_notifications_r6.py` — M4回帰テスト2件追加 + 既存`test_unverify_operator_notifies_with_inactive_flag`をactive始点に修正（pending始点だと新仕様上そもそも通知対象外になり失敗するため）。

## 未対応
- users.py側のsuspend（`test_user_unsuspend_notifies`が参照する別エンドポイント）にM4と同型の重複通知バグが疑われるが、指示範囲外（admin.py operatorのみ）のため未修正。
- M2の窓外極めて稀なケース（10分超で同一UUIDキーが再利用された場合）は既存案件を返す仕様とした（案件は作れないため）。挙動は多層防御コメントに明記済み。

## サマリ
✅ N1/M4/M5/M2/M1 実装完了・pytest 789 passed・alembic単一ヘッド0029確認済み。
