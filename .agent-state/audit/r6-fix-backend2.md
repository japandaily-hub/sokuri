# r6 修正実装（backend2）— 成約まわりの同時実行・状態整合 / 2026-09-04

対象台帳: `.agent-state/audit/r6-backend.md`（M-1〜M-4・M-6）＋ `r6-verify-backend.md`（ADD-2）
＋ `r6-flow.md`（H-1・H-2・M-3）＋ `r6-verify-flow.md`（ADD-1・ADD-2）

## 結論

- 指示 10 項目すべて実装。`pytest -q` = **774 passed / 0 failed**（着手時 753 passed。差分は本担当 +11、並走担当 +10）。
- 状態遷移の穴（減額の事後書き換え・停止業者の選定・キャンセル二重記録）はアプリ層のガードと
  **DB 制約の二層**で塞いだ。SQLite テストでも同じ制約が効くよう部分一意索引に `sqlite_where` を併記した。
- 行ロックは **Case → Transaction の順**に固定（既存 `bids.py` / `cases.py` と同順。逆順はデッドロックを新設する）。

## 実装内容

| # | 項目 | 実装 |
|---|---|---|
| 1 | 減額ガード（flow ADD-2 / backend M-3） | `decide_reduction` に `txn.status not in ("pending","visiting")` → 409「回答できる状態ではありません。」。`complete_transaction` に pending 減額の残存 → 409「減額申請への回答が必要です。…」 |
| 2 | 停止業者の選定禁止（flow ADD-1） | `select_bid` はロック取得後に `operator.is_suspended` → 409 / `vendor_status != "active"` → 409。`list_bids` は**除外せず** `operator_suspended` を付与 |
| 3 | 行ロック（M-1） | `_lock_txn_rows()` を新設し `complete` / `cancel` / `confirm_schedule` の先頭で Case→Transaction をロック。`cancel_count` は `UPDATE ... SET cancel_count = cancel_count + 1` の原子更新へ変更（Case ロックでは業者行を守れないため） |
| 4 | キャンセル冪等（M-2） | ロック後の再判定で 2 行目を作らない＋`uq_cancellations_transaction_id`（0028・モデルにも `UniqueConstraint`）＋`IntegrityError` → 409 |
| 5 | 減額 pending 一意（M-4） | `uq_reduction_requests_pending`（`transaction_id WHERE status='pending'` 部分一意索引。PG/SQLite 両対応）＋ `create_reduction` に `IntegrityError` → 409 |
| 6 | M-6（Low・同梱） | `ix_transactions_bid_id`（0028 ＋ モデル `index=True`） |
| 7 | ADD-2 | `GET /transactions` に `limit`（既定 100・`le=200`）/ `offset`。応答形状は配列のまま不変 |
| 8 | 退会時の暗黙キャンセル（flow H-1） | `users.py` に `_cancel_open_case_on_withdrawal()` を追加。`lock_case_row` → losers 収集 → 条件付き Case UPDATE → pending Bid 一括 rejected → `Cancellation` 記録 → commit 後に `dispatch_bid_lost`。draft は従来どおり status のみ更新 |
| 9 | 業者停止の可視化（flow H-2） | `TransactionDetailOut.operator_suspended` / `BidOut.operator_suspended`。停止**事由**は返さない（開示は運営経由） |
| 10 | 未読数（flow M-3） | `TransactionListItem.unread_count`。`_unread_counts()` が `Message ⋈ Transaction` の **GROUP BY 1本**で算出（N+1 なし） |

## 判断・逸脱

- **`vendor_status` の許容値**: 指示は「active/limited でない場合 409」だったが **`active` のみ許可**にした。
  `limited` はレガシー値で `get_verified_operator`（`deps.py:182`）が入札自体を禁じており、選定側だけ緩めると
  「入札できない業者が落札業者になる」不整合を残す。`get_transaction` の `awaiting_approval` 判定
  （`!= "active"`）とも基準が揃う。r6-verify-flow ADD-1 の修正案（`!= "active"`）と一致。
- **`list_bids` は除外ではなく旗**: 除外すると依頼者からは入札が黙って消えたようにしか見えず、
  選択できない理由も伝わらない（本監査の主題「静かに壊れる」を新設してしまう）。
- **キャンセルは冪等 200 ではなく 409**: 「既にキャンセル済み」を利用者に伝える方が誤操作の検知に資する。
- **0028 のバックフィル**: 完了・キャンセル済み取引に取り残された pending 減額を `rejected` へ更新する。
  これを入れないと項目 1 のガード追加後に回答不能な申請が残り、`create_reduction` の in-memory 判定で
  業者が恒久的に 409 になる（downgrade では復元不可＝片道の是正であることを migration の docstring に明記）。
- **0028 は既存重複を検査してから制約を張る**: `cancellations` / `reduction_requests(pending)` の重複を
  `SELECT ... GROUP BY ... HAVING count(*)>1` で確認し、在れば `RuntimeError` で中断（黙ってデータを壊さない）。

## 未対応 / 申し送り

1. **`cancel_case` との共通化**: `users.py` の `_cancel_open_case_on_withdrawal` は `cases.py:cancel_case` の
   手順を複製している（`cases.py` が別担当のため）。**`services/` の共通関数へ統合すべき**（許可 status と
   reason を引数化）。放置すると片方だけ直る二重メンテになる。
2. **既存データのバックフィル（H-1 の遡及分）**: 退会で `cancelled` になった案件に取り残された
   `Bid.status='pending'` は本修正では遡及しない。`Bid.status='pending' AND Case.status IN ('closed','cancelled')`
   の一度きりの是正が要る（flow M-6 と同じ検知条件）。
3. **本番適用前の確認（必須）**: `SELECT transaction_id, count(*) FROM cancellations WHERE transaction_id IS NOT NULL GROUP BY 1 HAVING count(*)>1;`
   が 0 行であること。1 行でもあると 0028 が `RuntimeError` で停止する。
4. **同時実行の実証は未実施**: SQLite の逐次テストでは `FOR UPDATE` の効きを再現できない。
   ロック順序・原子加算の正しさは PostgreSQL での並行 2 リクエスト実測でのみ確定する。[要確認]
5. **admin の代理キャンセル**: 将来「同一成約に運営が 2 行目の Cancellation を積む」運用が出た場合、
   `uq_cancellations_transaction_id` を `(transaction_id, cancelled_by)` の複合一意へ緩める必要がある。
