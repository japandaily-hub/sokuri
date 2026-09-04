# r8-fix-backend4 — H-1 残窓の閉塞 / 429 実証 / 契約統一 / Medium M-1〜M-6

日付: 2026-09-05 / 対象: `r8-verify-fix.md`・`r8-review.md` の残件（backend 主体）
正本: `C:\Users\ko13h\Claude\Projects\ソクウリ`（worktree ではなく正本を直接編集）

## 実行検証（実測）

| 項目 | コマンド | 結果 |
|---|---|---|
| pytest | `backend/.venv/Scripts/python.exe -m pytest -q` | **819 passed, 853 warnings in 202.92s / exit 0**（既存 814 + 新規 5） |
| alembic heads | `ScriptDirectory.get_heads()` | **単一ヘッド `0031_cancellation_admin`**（revid 23字・32字制限内） |
| 0031 の実行可否 | scratchpad の smoke（SQLite・batch モードで upgrade→downgrade、既存行の保全も確認） | **OK** |
| tsc（web 2ファイルのみ改変） | `web && npx tsc --noEmit` | **exit 0** |

## H-1 残窓 — Operator 行を共通の直列化点にした（リーダー指示より強い方式を採用）

指示は「`deleted_at` 先行 commit 方式」または「対象 Case 行の一括ロック」だったが、
どちらも窓が残るため採らなかった。根拠:

- **先行 commit 方式**: READ COMMITTED では、`select_bid` が「退会 commit の前に業者行を読み、
  退会側の再判定の後に commit する」順序を排除できない（読みと commit の間に窓が残る）。
- **Case 行の一括ロック**: 退会側がロック集合を確定した後に**新規 INSERT された入札**が付く
  Case は集合外で、r8-verify-fix が指摘した窓そのものが閉じない。

採用: 退会（`operator_profile.delete_my_operator_account`）と落札（`bids.select_bid`）が
**必ず触る唯一の共通行＝Operator 行**を双方が `SELECT ... FOR UPDATE` で掴む
（新設 `app/services/case_lock.py: lock_operator_row()`。ロックと同時に `deleted_at` を返す）。

- 落札が先に掴んでいれば退会側のロック取得がブロック → 解放後の進行中取引数の再判定で
  当該成約が可視化 → `rollback()` + 409。
- 退会が先に掴んでいれば落札側がブロック → 解放後に読む `deleted_at` は必ずコミット済み → 409。
- **どの Case・どの Bid に付くかに依存しない**ため、競合窓での新規入札 INSERT でも窓が開かない。
- ロック順序は **Case → Operator**（`select_bid` は `lock_case_row` の後に取得）。退会側は
  Case 行を掴まないため循環なし。`cases.cancel_case`（Case → bids 一括 UPDATE）とも循環なし。
- コスト: 落札1回につき主キー1行の `SELECT ... FOR UPDATE` が1回増えるのみ（O(1)・索引済み）。

制約（変わらず）: SQLite では `FOR UPDATE` が no-op のため、**直列化そのものは PostgreSQL 本番でのみ有効**。
テストは「退会 commit 後の落札は必ず 409」という観測可能な契約を固定する
（`test_select_bid_after_withdraw_commit_returns_409`。競合窓で入った pending 入札を再現し、
identity map ではなく再読込値で 409 になること・Transaction が 0 件のままであることを検証）。

## 変更ファイル

backend:
- `app/services/case_lock.py` — `lock_operator_row()` 新設（ロック＋`deleted_at` 再読込）
- `app/api/v1/endpoints/operator_profile.py` — 退会に Operator 行ロックを追加、docstring 全面更新
- `app/api/v1/endpoints/bids.py` — `select_bid` の退会判定を「ロック＋同一トランザクション内再読込」に変更
- `app/api/v1/endpoints/users.py` — `_DELETE_WRONG_PASSWORD` 400 → **403**（契約統一）
- `app/api/v1/endpoints/reductions.py` — `create_reduction` の先頭で `lock_transaction_rows`、`_get_txn` に `populate_existing`（M-6）
- `app/api/v1/endpoints/transactions.py` — `operator_deleted` の設定（M-5）
- `app/api/v1/endpoints/admin.py` — `Cancellation.cancelled_by_admin_id = admin.id`（M-1）
- `app/db/models/transaction.py` — `Cancellation.cancelled_by_admin_id`（FK users.id / ON DELETE SET NULL / index）
- `app/schemas_katadzuke.py` — `CASE_PURPOSE_VALUES` 削除（M-4）、`TransactionDetailOut.operator_deleted` 追加（M-5）
- `alembic/versions/0031_cancellation_admin.py` — 新規（batch_alter_table。0028/0029 と同作法）
- tests: `test_r8_abnormal_guards.py`（+5 ケース）、`test_account_api.py`（403 化）、`test_rate_limit_api.py`（tc31 の 400→403）

web（正本の `web/src/lib/` の2ファイルのみ。ページ側は別担当に委譲）:
- `web/src/lib/case-labels.ts` — `LEGACY_CASE_PURPOSES` 追加（M-2）
- `web/src/lib/katadzuke-api.ts` — 空 MIME のフォールバック復活（M-3）

## Medium 各件の対応

- **M-1**: 0031 + モデル + `admin.py` で `cancelled_by_admin_id` を記録。API 応答には出さない（当事者に運営個人を開示しない）。テスト `test_admin_cancel_records_executing_admin` で DB 記録と API 非露出の両方を固定。
- **M-2**: `LEGACY_CASE_PURPOSES = ["不用品処分","断捨離"]` を追加し、`formatPurposeLabel` は `CASE_PURPOSES ∪ LEGACY` をそのまま返す（選択肢には出さない）。コメントの虚偽（L-3「backend は free string」）も同時に是正。
- **M-3**: `file.type === ""` のときだけ従来どおり `image/jpeg` で送り、最終判断を backend のマジックバイト判定に委ねる。明示的な非対応 MIME（HEIC 等）はクライアントで弾いたまま。
- **M-4**: `CASE_PURPOSE_VALUES` を削除し `CasePurpose`（Literal）を単一の正本に。集合が要る場合は `typing.get_args()` を使う旨をコメントで明示。
- **M-5**: `TransactionDetailOut.operator_deleted: bool` を追加（既定 false の**加算的**変更）。停止と畳まず独立の旗にしたのは、退会は復帰しないため web の導線が「待つ」ではなく「キャンセルして出し直す／運営に相談」になるため。入札一覧 `BidOut` は `operator_suspended` への流用のまま（一覧に必要なのは「選べない」という単一の意味だけ）。
- **M-6**: `create_reduction` の先頭で `lock_transaction_rows`（Case → Transaction。当事者経路と同一規約）→ `populate_existing=True` で再取得 → pending 判定・上限判定。認可判定より前にロックを取るのは admin 強制終了・`transactions.cancel` と同じ作法（保持は数 ms）。404 が 403/500 に化けないことを新テストで固定。

## web へ伝える契約変更

1. **退会の誤パスワードは 400 → 403 に統一**（`DELETE /users/me`）。業者退会 `DELETE /operator/me` は従来どおり 403。
   `web/src/app/mypage/withdraw/page.tsx:138` は `status === 400` 分岐のため、**400/403 の両方**を
   「パスワードが正しくありません」として扱うこと。`operator/profile/page.tsx:175` は 403 のままで可。
2. **`GET /transactions/{id}` に `operator_deleted: boolean` を追加**（加算的・既定 false）。
   true のときは「業者が退会したためこの取引は進行できません」＋キャンセル導線を出す。
3. `web/src/lib/case-labels.ts` と `web/src/lib/katadzuke-api.ts` は**本タスクで直接修正済み**
   （M-2/M-3）。同ファイルを触る場合は競合に注意。ページ側（`/create` の選択肢等）は変更していない。

## 対応不要と判断した件（根拠つき）

- **業者 reauth（`POST /operator/reauth-token`）の 400 → 403 化は見送り**。理由: この 400 は
  パスワード変更・`/users/me/reauth-token`・bank-account・line-link と共有する
  「現在のパスワードが正しくありません。」ファミリで、**user 側と operator 側で既に対称**
  （`test_account_api.py` に「同じ規約（400）に統一する」という明示の規約テストが4件ある）。
  業者 reauth だけを 403 にすると user reauth 400 との**新しい非対称**を作り、
  `web/src/app/mypage/bank-account/page.tsx:179,217` の 400 分岐も壊れる。
  そこで「**不可逆操作（退会）＝403 / それ以外の再認証失敗＝400**」という説明可能な軸で統一した。
  ファミリ全体を 403 に寄せる案は、web 4画面の同時改修が前提のため次周の判断事項とする。

## 未対応（本タスクのスコープ外）

- 運営 web UI の退会バッジ・`include_deleted` トグル（web ページ側）
- `ConfirmModal` の L-1（busy 中の Esc/背景クリック）・textarea の maxLength（web ページ側）
- 退会業者のレビュー統計・`Operator.rating` の再計算 [要確認: 集計仕様が未定]
- Postgres での競合テスト層（testcontainers 等）。SQLite では行ロックが no-op のままである事実は変わらない
- **0030 と 0031 は本番未適用。migrate → deploy の順を厳守**（`deps.py`/`auth.py` が `operators.deleted_at` を無条件参照するため、順序を誤ると業者側の全リクエストが 500）

サマリ: ✅ pytest 819 passed / H-1 残窓を Operator 行ロックで閉塞・429 実証・退会の 403 統一・Medium 6件すべて対応（reauth の 403 化のみ根拠つきで見送り）
