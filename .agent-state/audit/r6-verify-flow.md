# r6-flow 独立検証（業務フロー・状態機械）

検証日: 2026-09-04 / 対象台帳: `.agent-state/audit/r6-flow.md` / 検証者: 立案者と無関係な第三者
判定集計: CONFIRMED 4 / PARTIAL 2 / REJECTED 0 / 追加 High 2

## 状態値一覧表の検証

- Case/Bid/Transaction の値と web ラベルの対応は事実（`backend/app/db/models/case.py`, `bid.py`, `transaction.py` × `web/src/lib/katadzuke-api.ts`）。
- ReductionStatus 行は**行番号が不正確**: `REDUCTION_STATUS_LABEL`/`REDUCTION_CHIP_CLASS` の定義は `web/src/app/operator/transactions/[id]/page.tsx:36,41`（248 は使用箇所）。主張自体（依頼者側に定義なし）は正しい。

## 各項目の判定

### H-1｜退会時の暗黙キャンセルが Bid却下・Cancellation・通知を欠く — **CONFIRMED（重大度 High → Medium に修正）**
- 事実: `users.py:542-545` は `case.status = "cancelled"` の直接代入のみ。対比 `cases.py:401-411`（losers 収集＋pending Bid 一括 rejected）/ `cases.py:429-436`（Cancellation 追記）/ commit 後の losers 通知。退会経路にこの3つは無い。
- 進行中取引がある場合の挙動（要確認事項）: **退会自体が 409 で拒否される**。`users.py:528-535` が `Transaction.status IN (pending, visiting)` を数え `_DELETE_ACTIVE_TRANSACTION`（`users.py:494-497`）。よって成約済み取引が壊れることはない。影響範囲は txn 未成立案件（`users.py:544` の `txn is None` 条件）に限定。
- 重大度修正の根拠: 取り残された pending Bid は再選択されない（`bids.py:232` が `case.status != "bidding"` で 409、`create_bid` も `bids.py:255` で 409）。危険な状態遷移は発生せず、実害は「業者側に pending バッジが永久残留」「落選通知なし」「監査証跡なし」の3点。金銭・権限の誤りは生じないため High は過大、Medium が妥当。
- 修正案への注意: (a) `cancel_case` は `draft` を拒否する（`cases.py:381-386`）が退会経路は draft も cancelled にする。共有関数化するなら許可 status の差を引数化しないと退会が 409 で失敗する。(b) 共有関数は `lock_case_row` と条件付き UPDATE を伴うため、退会ループ内で案件数ぶんロックを取ることになる。多案件ユーザーでのトランザクション長大化に留意。(c) 通知は commit 後にプリミティブ値で送る既存規約（`cases.py` のコメント）を退会側でも守ること。

### H-2｜業者停止中は取引操作が全て 403、依頼者に理由が見えない — **CONFIRMED（重大度 High → Medium に修正）**
- 事実: `deps.py:230` の `assert_operator_not_suspended` が `get_current_actor` 全経路に掛かり、`transactions.py` のチャット/日程/減額系は全て `Depends(get_current_actor)`。依頼者に返る `OperatorPublicOut`（`schemas_katadzuke.py:135-146`）に `is_suspended` フィールドは存在せず、`transactions.py:167` でそのまま詰めているため UI に出しようがない。
- `docs/TODO.md:32` ⑤ は「停止した**依頼者**の open 案件」であり別事象。重複ではない → REJECTED にはしない。
- 重大度修正の根拠: 依頼者は `complete_transaction`（`transactions.py:231-235`・ユーザー専用）と `cancel_transaction`（当事者いずれか）を行使できるため詰みではない。実害は「相手が無応答な理由が分からない」説明欠如で Medium。
- 修正案への注意: (a) 案の「業者の is_suspended を依頼者へ露出」は、停止事由を推測させる情報開示になる。フィールド名を `is_suspended` のまま返さず「対応不可」相当の派生フラグにすること。(b) 業者側は 403 の `detail.code=account_suspended`（`deps.py:80-82`）を既に受け取れるので業者側の追加実装は不要。

### M-3｜取引一覧に未読チャット表示なし — **CONFIRMED（Medium 妥当）**
- 事実: `unread_count` は `TransactionDetailOut`（`schemas_katadzuke.py:690`）のみ。`TransactionListItem`（同 697-）は `has_pending_reduction`/`has_review` は持つが unread は無し。`transactions.py:78-93` の一覧構築にも算出なし。
- 修正案への注意: 案の「txn ごとに `_count_unread`（`transactions.py:206`）を適用」は N+1 クエリ。取引件数ぶん COUNT が走るので、`Message` を `transaction_id` で GROUP BY した1本の集計 SELECT に相手方 last_read_at 条件を結合する形にすべき。

### M-4｜減額の承認/却下履歴が依頼者側に出ない — **CONFIRMED（Medium 妥当）**
- 事実: `web/src/app/cases/[id]/page.tsx:313` が `reduction_requests` の唯一の参照で `pendingReduction` のみ。表示は同 682-719 の承認待ちパネルだけ。業者側は `operator/transactions/[id]/page.tsx:240-256` で全件履歴表示。API は依頼者にも全件返している（`transactions.py:169`）ため純粋に UI 欠落。
- 修正案への注意: ラベル定数を `katadzuke-api.ts` へ移す際、業者側のローカル定義（同ファイル 36,41 行）を削除して二重定義を残さないこと。

### M-5｜訪問予定日超過のリマインドが無い — **CONFIRMED（Medium 妥当）**
- 事実: backend 全体で `visit_date` は保存・表示・通知（`transactions.py:491,499,522`）のみに使われ、超過判定・バッチ・cron は存在しない（`backend/app` に overdue 相当の実装なし）。web も `cases/[id]/page.tsx:674-678` で素の表示のみ。
- 修正案への注意: クライアント側 `visit_date < today` 判定は端末TZ依存。JST 固定で比較しないと日付境界で誤警告が出る。

### M-6｜Bid 専用の admin 一覧が無く孤立 pending 入札を検知できない — **PARTIAL（重大度 Medium → Low）**
- 事実確認: `web/src/app/admin/` 配下は `cases / transactions / users / identity-documents / operator-applications` のみで bids 画面は無い。事実は正しい。
- 減格の根拠: これは H-1 の派生であり単独の導線欠陥ではない。H-1 を直せば新規の孤立入札は発生せず、既存行は一度きりのバックフィルで足りる。恒久的な admin 画面追加を Medium 課題として立てるのは過大。台帳自身も「H-1修正を優先」と書いており独立項目としての価値が薄い。

## 追加発見（同観点で見落とされた High）

### ADD-1｜停止中／承認取消の業者の入札を依頼者が選択でき、即座に操作不能な成約が生まれる — **High**
- 箇所: `backend/app/api/v1/endpoints/bids.py:232-247`（`select_bid` は `case.status` と `target.status` のみ検証し、`target.operator.is_suspended` / `vendor_status` を一切見ない）/ `bids.py:88-95`（`list_bids` も停止業者の入札を依頼者一覧から除外しない）。
- 事象: 入札後に運営が業者を停止（`admin.py` の suspend）しても、その入札は依頼者の入札一覧に pending のまま並び選択できる。選択すると `Transaction(status="pending")` が生成される（`bids.py:270-277`）が、当該業者は `deps.py:230` により全 API で 403。つまり **H-2 の行き詰まり状態を新規に生成できる**うえ、依頼者は他の入札を捨てて（`bids.py:266-269` で他の pending は rejected）その業者に確定してしまう。`vendor_status != "active"` の場合も同様に選択可能で、成約後に `awaiting_approval=true`（`transactions.py:176-180`）で住所非開示のまま停滞する。
- 修正の最小構成: `select_bid` のロック後・条件付き UPDATE 前に `target.operator.is_suspended` と `vendor_status != "active"` を 409 で弾く。併せて `list_bids` の依頼者向け返却から停止業者の入札を除外（または「対応不可」フラグ付与）。注意: 既存の落札済みデータには遡及しないため、H-2 側の表示対応と両方必要。

### ADD-2｜減額申請の承認/却下が完了済み・キャンセル済み取引にも通り、確定額が事後に書き換わる — **High**
- 箇所: `backend/app/api/v1/endpoints/reductions.py:126-152`（`decide_reduction` に `txn.status` のガードが無い。対比 `reductions.py:70-74` の `create_reduction` は `pending/visiting` 以外を弾く）/ `backend/app/api/v1/endpoints/transactions.py:236-246`（`complete_transaction` も pending な減額申請の有無を検証しない。UI 側 `cases/[id]/page.tsx:724` の `disabled={busy || Boolean(pendingReduction)}` だけが抑止）。
- 事象: 減額申請が pending のまま依頼者が完了確定すると `final_amount = initial_amount` で確定する（`transactions.py:243-244`）。その後も同じ申請は pending のままなので `decide_reduction` が通り、**completed 済み取引の `final_amount` が後から書き換わる**（`reductions.py:152`）。キャンセル済み取引でも同様。UI の disabled は同一画面での抑止に過ぎず、API 直叩き・別タブ・業者の申請とユーザーの完了操作の競合で普通に到達する。金額＝精算額の事後変更であり状態機械の穴として High。
- 修正の最小構成: `decide_reduction` の冒頭に `txn.status in ("pending","visiting")` チェック（409）を追加し、`complete_transaction` にも pending 減額があれば 409 を返すサーバ側ガードを追加する。注意: 既存の completed 取引に pending 減額が残っている行があれば、ガード追加後は回答不能になるため一括 rejected のバックフィルが要る。

## 保存パス
`C:\Users\ko13h\Claude\Projects\ソクウリ\.agent-state\audit\r6-verify-flow.md`

## サマリー
⚠️ 台帳6件は全て事実として成立（捏造ゼロ）だが、重大度は H-1・H-2 ともに Medium が妥当で M-6 は Low。一方で見落とされた真の High が2件（停止業者の入札を選択できる／完了後に確定額が書き換わる）あり、優先順位は台帳のままでは誤る。
