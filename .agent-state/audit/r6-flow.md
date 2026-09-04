# r6 導線監査 — 依頼者→業者→運営 一気通貫の状態整合

監査日: 2026-09-04 / 対象: main（作業ツリー未コミット差分含む）/ 観点: Block2 (1)〜(8)

## 状態値の一覧表（backend の値 × 各画面のラベル有無）

| 状態機械 | backend の全値（定義箇所） | web のラベル定義 | 網羅性 |
|---|---|---|---|
| Case.status | draft / open / bidding / closed / cancelled（`backend/app/db/models/case.py:41-45,56`） | `CASE_STATUS_LABEL: Record<CaseStatus,string>`（`web/src/lib/katadzuke-api.ts:1957-1964`）+ TS の Record 型で網羅漏れはコンパイルエラーになる | ✅ 5値とも被覆。mypage の `statusChipInfo`（`web/src/app/mypage/page.tsx:58-63`）は独自のswitchだが最終 `return` が「下書き」でdraftも被覆 |
| Bid.status | pending / selected / rejected / withdrawn（`backend/app/db/models/bid.py:28-31`, CHECK制約 `bid.py:63-67`） | `BID_STATUS_LABEL: Record<BidStatus,string>`（`katadzuke-api.ts:1970-1975`） | ✅ 4値とも被覆 |
| Transaction.status | pending / visiting / completed / cancelled（`backend/app/db/models/transaction.py:24-27,45-47`） | `TXN_STATUS_LABEL: Record<TransactionStatus,string>`（`katadzuke-api.ts:1987-1992`） | ✅ 4値とも被覆。admin一覧の `STATUS_OPTIONS` も `Object.keys(TXN_STATUS_LABEL)` から動的生成（`web/src/app/admin/transactions/page.tsx:30-35`）で追随 |
| ReductionRequest.status | pending / approved / rejected（`transaction.py:75-97`） | 業者側のみ `REDUCTION_STATUS_LABEL`/`REDUCTION_CHIP_CLASS`（`web/src/app/operator/transactions/[id]/page.tsx:248`にローカル定義、`katadzuke-api.ts`に非export） | ⚠️ **依頼者側は無定義**。`web/src/app/cases/[id]/page.tsx` は `reduction_requests` を `pendingReduction`（313行目）以外で一切参照せず、approved/rejected の履歴表示コンポーネント自体が存在しない（詳細は Medium #4） |

admin の一覧フィルタ（`admin/cases/page.tsx:30-36`, `admin/transactions/page.tsx:30-36`）はラベル定義から動的生成のため値追加時も自動追随する健全な実装。**Bid.status の一覧フィルタは admin 側に画面自体が存在しない**（bids専用のadmin一覧なし。案件詳細に埋め込み表示のみ）。

## High / Medium 台帳（上限12件・実際6件）

### H-1｜退会時の暗黙キャンセルが「入札拒否・監査記録・通知」を欠落させる
- 重大度: High
- 箇所: `backend/app/api/v1/endpoints/users.py:499, 542-545`（対比: `backend/app/api/v1/endpoints/cases.py:391-432` の正規 `cancel_case`）
- 事象: `DELETE /users/me` は保留中の案件（draft/open/bidding, txn無し）を `case.status = "cancelled"` に直接書き換えるだけ（`users.py:544-545`）。一方、通常の取り下げ経路 `cancel_case`（`cases.py`）は同じ遷移で ①pending の Bid を一括で `rejected` に更新（`cases.py:406-411`）②`Cancellation` レコードを追記（`cases.py:428-434`）③却下対象業者へ通知（`cases.py:397-402`の losers収集→通知）を行う。退会経路にはこの3つが一切無い。
- 再現: 依頼者がopen/bidding状態の案件に業者から入札(pending)を受けた状態で `/mypage/withdraw` から退会 → 案件は cancelled になるが、紐づく Bid 行は status=pending のまま永久に残る。監査証跡（Cancellation）も残らず、入札していた業者には何も通知されない。
- 修正案: `delete_my_account` 内のループ（`users.py:542-545`）で `case.status` を cancelled にする際、`cases.py` の `cancel_case` と同じ「pending Bid一括rejected」「Cancellation作成」「losers通知」ロジックを共有関数化して呼び出す。

### H-2｜業者停止中は成約済み取引の全操作（チャット・日程・減額）が本人にブロックされ、依頼者にも理由が見えない
- 重大度: High
- 箇所: `backend/app/api/deps.py:212-231`（`get_current_actor` 内 `assert_operator_not_suspended` 呼び出し, 230行目）/ `backend/app/api/v1/endpoints/transactions.py:330-500`（list_messages/create_message/propose_schedule/confirm_scheduleは全てこの `get_current_actor` を通す）
- 事象: 業者が `is_suspended=true` にされると `get_current_actor`（`deps.py:226-231`）が全操作で403を返す。`complete_transaction` は仕様上ユーザー専用（`transactions.py:231-235`「完了確定はユーザー側のみ行えます」）なので依頼者は完了・キャンセル自体はできるが、**チャット送受信・日程提案/確定・減額申請への回答受付**は業者側からもはや一切行えない。依頼者側UI（`cases/[id]/page.tsx`）には業者が停止中であることを示す表示が無く、「業者とチャット」ボタンは押せるが相手が応答不能な理由が分からないまま待たされる。
- 再現: 成約後（txn.status=pending/visiting）に運営が `PATCH /admin/operators/{id}/suspend` で業者を停止 → 業者トークンでの `/transactions/{id}/messages` 等が全て403 → 依頼者画面は通常表示のまま変化なし。
- 修正案: (a) `TransactionOut`/`TransactionListItem` に相手方（業者）の `is_suspended` を持たせ、依頼者側に「業者が現在対応できません。キャンセルをご検討ください」のバナーを出す。(b) 運営が業者停止操作時に進行中Transactionの有無を検知し、admin一覧（`docs/TODO.md` 03 の既知課題⑤とは別軸）に警告を出す。

### M-3｜取引一覧（mypage/operator双方）に未読チャット表示が無い
- 重大度: Medium
- 箇所: `backend/app/api/v1/endpoints/transactions.py:48-93`（`list_transactions` のSELECTに `unread_count` 算出が無い）/ `web/src/lib/katadzuke-api.ts:172-187`（`TransactionListItem` に `unread_count` フィールド自体が存在しない）/ `web/src/app/mypage/page.tsx`・`web/src/app/operator/transactions/page.tsx:92-93`（一覧に unread 表示なし）
- 事象: `unread_count` は `TransactionOut`（詳細取得, `katadzuke-api.ts:234`）にのみ存在し、一覧APIのレスポンス型 `TransactionListItem` には無い。依頼者・業者いずれも複数の取引を並行して進めている場合、どの取引に未読メッセージがあるかは一覧画面から判別できず、各取引を1件ずつ開いて確認する以外の手段がない。
- 再現: 依頼者が3件の成約済み案件を持ち、うち1件だけ業者から新着メッセージが届いても `/mypage` の一覧・`/operator/transactions` の一覧ともに見た目の変化なし。
- 修正案: `list_transactions`（`transactions.py:48-93`）に `_count_unread`（既存関数, `transactions.py:206`）をtxnごとに適用して `unread_count` を追加し、一覧カードに未読バッジを出す。

### M-4｜減額申請の承認/却下履歴が依頼者側に一切表示されない
- 重大度: Medium
- 箇所: `web/src/app/cases/[id]/page.tsx:313, 682-719`（`pendingReduction` のみ参照、`reduction_requests` の全件表示なし）/ 対比 `web/src/app/operator/transactions/[id]/page.tsx:240-256`（業者側は `REDUCTION_STATUS_LABEL`/`REDUCTION_CHIP_CLASS` で全件履歴表示）
- 事象: 依頼者側の成約パネルは `pendingReduction`（status===pending の1件）のみを条件表示し、承認・却下が完了した過去の申請は跡形もなく消える（`reduction_requests` 配列自体をそれ以外の箇所で参照していない）。業者側は同じデータを履歴チップ付きで全件表示している。承認直後は確定額の更新で気づけるが、後から取引詳細を見返しても「なぜ確定額が変わったか」の理由（reason）を確認する手段が依頼者側に無い。
- 再現: 業者が減額申請→依頼者が承認→確定額が更新される→依頼者が後日 `/cases/{id}` を再訪しても reason や申請履歴はどこにも出ない（final_amount の数字だけが残る）。
- 修正案: `REDUCTION_STATUS_LABEL`/`REDUCTION_CHIP_CLASS` を `katadzuke-api.ts` にexportし、`cases/[id]/page.tsx` の成約パネルにも `txn.reduction_requests` の履歴リストを追加する。

### M-5｜訪問予定日を過ぎても「完了/キャンセルすべき」というリマインドが双方に無い
- 重大度: Medium
- 箇所: `backend/app/api/v1/endpoints/transactions.py`（overdue検知・バッチ処理なし。grep結果に該当なし）/ `web/src/app/cases/[id]/page.tsx:674-678`（visit_dateをそのまま表示するのみ）/ `web/src/app/operator/transactions/[id]/page.tsx:186-187`（statusのみでbadgeの色分け、日付超過の判定なし）
- 事象: `Transaction.status` が `visiting` のまま `visit_date` を過ぎても、依頼者・業者いずれの画面にも「予定日を過ぎています」等の警告は出ない。完了/キャンセルのボタン自体は常設（`cases/[id]/page.tsx:722-750`）なので操作は可能だが、能動的に気づく手段（バッジ・通知・バッチ）が無いため訪問後に双方が完了操作を忘れた場合、取引が`visiting`のまま無期限に滞留しうる。
- 再現: visit_date=昨日 のtxn.status="visiting"を用意し `/cases/{id}` と `/operator/transactions/{id}` を表示 → どちらにも超過の視覚的手がかりなし。
- 修正案: `visit_date < today && status==="visiting"` を判定してカード内に警告表示、または運営向けの `admin/transactions` フィルタに「訪問日超過」条件を追加する。

### M-6｜Bid専用のadmin一覧画面が存在せず、退会等で発生した孤立pending入札を運営が発見できない
- 重大度: Medium
- 箇所: `web/src/app/admin/*`（Bid単体の一覧ルートなし。`cases.py`/`bids.py` にも `/admin/bids` 相当のエンドポイントなし）
- 事象: H-1で発生しうる「案件はcancelledだがBidはpendingのまま」という不整合状態を運営側から横断的に検知する手段が無い（admin/cases一覧は案件単位でCase.statusしか出さず、内部のBid.statusまでは見えない）。
- 再現: H-1の再現後、admin画面のどこにもこの不整合を示す指標が出ない。
- 修正案: H-1修正を優先。恒久対策として `Bid.status='pending' AND Case.status IN ('closed','cancelled')` を検知するヘルスチェック/admin一覧を追加。

## 保存パス
`C:\Users\ko13h\Claude\Projects\ソクウリ\.agent-state\audit\r6-flow.md`

## サマリー
⚠️ High 2件・Medium 4件を検出。特に H-1（退会時の暗黙キャンセルが入札拒否・監査記録・通知を欠落）は依頼者→業者→運営を横断する状態不整合の実害があり優先対応を推奨。「問題ゼロ」ではない。
