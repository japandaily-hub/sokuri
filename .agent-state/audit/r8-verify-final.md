# r8 最終検証（独立QA） — HEAD=24f4ee7

総合判定: **合格（Critical/High 0）**。r8-verify-fix の「一部／未対応」8項目はすべて実装が実在し、額面どおり機能する形になっている。

## 実測

| 検証 | 結果 |
|---|---|
| `backend` pytest -q | exit 0 / **819 collected・全通過**（自己申告 819 と一致） |
| `web` npx tsc --noEmit | **エラー 0** |
| `web` npx eslint src | **0 errors, 3 warnings**（unused eslint-disable ×2、`src/app/signup/page.tsx:59` の未使用 `router`） |
| alembic heads | **単一ヘッド `0031_cancellation_admin`**（32リビジョン、静的グラフ解析。`alembic heads` CLI 自体は alembic.ini の日本語を cp932 で読んで UnicodeDecodeError になる＝別件の環境問題） |
| git status | tracked 変更なし（未追跡ファイルのみ） |

## 項目別判定

### (1) 退会×落札の競合 — **塞がった**
- `app/services/case_lock.py:34-57` `lock_operator_row` は `select(Operator.deleted_at).where(...).with_for_update()`。PG では実ロック、SQLite では no-op（docstring 明記）。
- 双方から取得済み: 落札側 `app/api/v1/endpoints/bids.py:283`（`lock_case_row` は :230 → Case→Operator の順）、退会側 `app/api/v1/endpoints/operator_profile.py:448`（Case 行は掴まない）。
- 戻り値の `deleted_at` を同一トランザクションで読み直して 409（`bids.py:284-288`）。identity map の陳腐化を回避する設計になっている。
- **デッドロック無し**（検証済み）: 有向グラフは Case→Operator→Bid（select_bid）と Operator→Bid（退会）。退会側は `UPDATE bids SET status`（FK列を触らない）のみで親 `cases` 行を掴まず、`Transaction` の行ロックも取らない（`operator_profile.py:459-471` は素の SELECT count）。admin 強制終了・減額は Case→Transaction で Operator を要求しない。循環は成立しない。

### (2) `account_delete` の 429 — **塞がった**
- テスト実在: `backend/tests/test_r8_abnormal_guards.py:698-751`。`sensitive_account=1` の専用 RateLimiter を注入し、誤PW→403、続く正PW→**429 + Retry-After** を実証、`deleted_at is None` まで確認。
- 呼び順は users.py と同型: `ctx.check_account` → `verify_password` 失敗で `ctx.record_failure` + raise → 成功で `ctx.reset_account`（`operator_profile.py:436-444` ⇄ `users.py:607-613`）。
- 依頼者側の同等 429 テストも既存（`tests/test_rate_limit_api.py:562-575`）。

### (3) 誤パスワード 403 統一 / web の 400・403 両対応 — **塞がった**
- backend: `users.py:498-501` `_DELETE_WRONG_PASSWORD` = 403、`operator_profile.py:375-378` `_OPERATOR_DELETE_WRONG_PASSWORD` = 403。文言も同一「パスワードが正しくありません。」。退会以外の再認証（reauth/line-unlink）は 400 のまま、user/operator で対称。
- web: `src/app/mypage/withdraw/page.tsx:138`・`src/app/operator/profile/page.tsx:175` がいずれも `status === 400 || status === 403` を誤パスワード扱い。

### (4) 0031 と admin 強制終了の記録 — **塞がった**
- `alembic/versions/0031_cancellation_admin.py`: revision id 23文字（32字制限順守）、`batch_alter_table` で SQLite 対応、FK `ON DELETE SET NULL`、索引付与。down_revision=0030。
- 書き込み: `app/api/v1/endpoints/admin.py:786` `cancelled_by_admin_id=admin.id`。
- **API 応答に出ない**: `cancelled_by_admin_id` の出現箇所は `admin.py:786` と `app/db/models/transaction.py:180` のみ。`schemas_katadzuke.py` に該当フィールド無し（`TransactionCancellationOut` は `cancelled_by` のみ）。
- 回帰テスト: `tests/test_r8_abnormal_guards.py:757`。

### (5) `create_reduction` のロック内件数判定 — **塞がった**
- `app/api/v1/endpoints/reductions.py:85` で `lock_transaction_rows`（Case→Transaction）を**認可判定より前**に取得 → `:90` `_get_txn`（`execution_options(populate_existing=True)` + `selectinload(Transaction.reduction_requests)`、`reductions.py:38-55`）で読み直し → `:109` `len(...) >= _MAX_REDUCTION_REQUESTS(=2)` を**ロック内**で判定。
- 多層防御として部分一意索引 `uq_reduction_requests_pending`（0028）違反を 409 へ変換（`:131-141`）。

### (6) `operator_deleted` — **塞がった**
- backend: `app/schemas_katadzuke.py:766`（`TransactionOut.operator_deleted`）、設定は `app/api/v1/endpoints/transactions.py:370`。
- web: 型 `src/lib/katadzuke-api.ts:294`、依頼者の成約詳細 `src/app/cases/[id]/page.tsx:801,835,942`（退会時は日程/完了導線を隠す）、チャット `src/app/chat/[id]/page.tsx:281,373,447,479`（送信・確定を disabled 化）。

### (7) ConfirmModal / admin 一覧 — **塞がった**
- `src/components/kdz/ConfirmModal.tsx`: `busyRef` で最新 busy を参照し Esc を無効化（:88-95）、背景クリックも `if (busy) return`（:118-121）、Tab トラップは busy 中も維持（:96-110）、キャンセル/確定ボタンとも `disabled={busy...}`（:186-196）。
- パスワード欄: `type="password"` / `autoComplete="current-password"` / `maxLength=128`、空なら確定 disabled、Enter 確定は `isComposing` 除外（:163-181）。
- 理由欄: `maxLength=500` + 残り文字数と「個人情報や誹謗中傷は記載しないでください」の注記（:143-153）。
- admin 業者一覧 `src/app/admin/page.tsx`: 「退会済みを含める」トグル :584（backend 既定 `include_deleted=false`：`admin.py:261-281`）、`StatusBadge 退会済み` :604、操作ボタン非表示＋「退会済みのため操作できません」:592-622。backend も 409 で二重防御（`admin.py:364,419`）。

## 新規回帰（High 以上）
**なし。** pytest 819 全通過・tsc 0・eslint 0 errors。退会/落札/減額/強制終了のロック順序を追跡した結果、新規のデッドロック経路も認可の緩みも検出できなかった。

## 未解決リスク
1. **[中] PG 上での直列化は一切実証されていない。** `with_for_update()` は SQLite で no-op（`app/services/case_lock.py:47`）のため、H-1 を守るテスト（`tests/test_r8_abnormal_guards.py:618,650`）はいずれも「退会 commit 後の逐次実行」しか検証できていない。真の同時実行窓が閉じているかは PG 実機での並行テスト無しには未確認。
2. **[中] 「新規 INSERT された入札」の閉塞は PostgreSQL の暗黙 FK ロックに依存している。** `bids.create_bid`（`app/api/v1/endpoints/bids.py:124`）は `lock_operator_row` を呼ばず、退会中に新規入札を止めているのは `bids.operator_id` の FK が INSERT 時に親 `operators` 行へ取る `FOR KEY SHARE`（`FOR UPDATE` と競合）だけ。この依存はコード上どこにも明記されておらず、FK の削除・`DEFERRABLE` 化・別経路での入札生成が入った瞬間に、docstring が「閉じた」と主張する窓が無言で再開する。
3. **[低] `ConfirmModal` の Esc ハンドラは mount 時の `onCancel` を閉じ込めている**（`src/components/kdz/ConfirmModal.tsx:88-110`、deps `[]` + eslint-disable）。busy は ref 化されたが `onCancel` はされていないため、親が状態依存のクロージャを渡すと Esc が陳腐化した関数を呼ぶ。現行の呼び出し元は単純な setState のため顕在化しないが、脆い契約。
4. **[低] 理由欄の 500 字上限は backend と一致していない。** `TransactionCancelRequest.reason` は `max_length=2000`（`app/schemas_katadzuke.py`）。クライアント側が厳しいだけなので 422 は起きないが、コメントの「管理系は概ね 500」は事実と異なる。
5. **[低] `BidOut` に `operator_deleted` が無い**（`app/api/v1/endpoints/bids.py:71` が `operator_suspended` へ流用）。依頼者は入札一覧で退会業者を「停止中」と誤読し、選択して初めて 409 の文言で退会を知る。
