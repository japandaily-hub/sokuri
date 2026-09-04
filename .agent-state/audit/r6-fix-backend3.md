# r6-fix-backend3 — H2/H3 是正（2026-09-05）

## 結論
1. H2（ai_status=pending の恒久残留）: GET /cases/{id}・依頼者向け一覧での遅延回収（10分超→failed, reason="stale"）と、main.py lifespan 起動時の一括スイープの両方を実装。フォールバック要約は既存仕様のまま保持される。
2. H3（0028 の重複データで RuntimeError 停止）: 重複を検知しても止めず、cancellations は transaction_id ごとに最古の1行を残して他を削除、reduction_requests(pending) は最古以外を rejected へ自動是正してから一意制約/索引を張るよう変更。SQLite の ALTER 制約非対応も batch_alter_table で合わせて修正。
3. docs/ops/ に 0028 の事前確認 SQL を記載したファイルは存在しない（alerting.md のみ）ため該当ドキュメント更新は無し。事前確認 SQL は `.agent-state/audit/r6-fix-backend2.md` にのみ記載されており、docs/ops 配下ではないため対象外。

## pytest 結果
`.venv/Scripts/python.exe -m pytest -q` → **787 passed, 0 failed**（348.66s）。内訳: 既存784 + 新規3（test_case_ai_background.py に2件、tests/test_0028_migration_dedup.py に1件）。

## 変更ファイル
- `backend/app/api/v1/endpoints/cases.py` — `_AI_STALE_PENDING_WINDOW`/`_reap_stale_pending_ai`/`sweep_stale_pending_ai` を追加。`list_cases`（依頼者分岐）・`get_case`（依頼者分岐）から遅延回収を呼び出し。
- `backend/app/main.py` — `_run_stale_pending_ai_sweep` を追加し、lifespan 起動時に `asyncio.create_task` で起動（失敗しても起動継続、_run_seed と同方針）。
- `backend/alembic/versions/0028_txn_state_integrity.py` — `_assert_no_duplicates`（RuntimeError）を廃止し `_dedupe_cancellations` / `_reject_duplicate_pending_reductions` に置換（削除・更新件数をログ出力）。`op.create_unique_constraint` を `batch_alter_table` 経由に変更（SQLite は既存テーブルへの ALTER TABLE ADD CONSTRAINT 自体を未サポートのため、この修正なしでは SQLite 上で 0028 が原理的に適用不能だった＝H3 のテスト要件を満たすために必須の付帯修正）。downgrade も揃えて更新。
- `backend/tests/test_case_ai_background.py` — H2 のテスト2件（GET/一覧での遅延回収、起動時スイープの選択的回収）を追加。datetime import を追加。
- `backend/tests/test_0028_migration_dedup.py`（新規） — 0027相当スキーマを直接構築→重複データ投入→`command.stamp`+`command.upgrade`で0028を適用し、RuntimeErrorを出さず完走・重複是正・制約実在を検証。alembic.ini読込がcp932ロケールでUnicodeDecodeErrorになる既知の罠を回避するため`Config()`無引数構築を採用。

## 未対応
- H1（web の limit/offset 未追随）は本ミッションの対象外（web/ 担当）。
- 「[要確認]」既存の未解決リスク（PG実測・DB_POOL_SIZE・Gemini同時実行）は本修正の範囲外のまま。

## サマリ
✅ H2/H3 実装完了・pytest 787 passed 0 failed・既存スタイル継承・docs/ops 更新対象ファイル無し。
