# r3-vendor.md 独立検証（敵対的レビュー）— 2026-09-04

検証者: 独立品質保証（立案者と無関係）。方針: 台帳の主張を額面で受けず、全項目を実コードで再読。迷えば却下寄り。
制約: `backend/app/config.py` `backend/app/main.py` は別セッション編集中のため、これらへの修正提案は却下対象（本検証の推奨修正にも含めない。読み取りのみ実施）。

判定集計: CONFIRMED 3 / PARTIAL 1 / REJECTED 0 ／ 追加発見 High 3 件。

---

## R3-H1（セッション失効時の英語生エラー＋再ログイン導線なし）— **CONFIRMED / 重大度 High 妥当（むしろ過小評価）**

根拠（自力再確認）:
- `backend/app/api/deps.py:21-25` — `_CRED_EXC` の detail は `"Invalid credentials. Please log in again."` 固定。`get_current_user`(103-114) / `get_current_operator`(127-137) / `get_current_actor`(179-201) すべてが同一例外を送出。台帳の記載どおり。
- `web/src/lib/katadzuke-api.ts:1417-1424` — `toDisplayMessage` は `status >= 500` のみ fallback へ置換。401 は `detail` が空でも `/^HTTP \d+$/` でもないため **そのまま返す**。台帳どおり。
- `web/src/app/operator/page.tsx:299-310`（`reload()`）— `setError(toDisplayMessage(...))` のみ。401 分岐なし。
- grep 再実行: `web/src/app/operator/` 配下に `401` の文字列ヒット **0 件**（台帳の grep 主張は真）。401 ハンドリングは `notifications/page.tsx:235` と `components/kdz/AppHeaderBell.tsx:96` にのみ存在し、業者導線には無い。

**台帳が過小評価している点（重大度は据え置き High だが、再現条件が「DevTools で破損」より遥かに容易）**:
`web/src/auth.ts:149` は `session: { strategy: "jwt" }` のみで `maxAge` 未指定＝NextAuth 既定 **30日**。一方バックエンドの access_token は `backend/app/config.py:59` の `jwt_expire_minutes: int = 60*24*7` ＝ **7日**（`backend/.env.example:48` も `JWT_EXPIRE_MINUTES=10080`）。したがって **8日目以降、NextAuth セッションは生きたまま（`middleware.ts` は素通し）accessToken だけが失効し、業者の全 API 呼び出しが英語 401 を返す**。これは特殊操作ではなく全業者に必ず訪れる定常事象。台帳の再現手順（トークン破損）より現実的な経路がある。

**修正案への注意（副作用）**:
1. `request()` 共通層で 401 を無条件にリダイレクトすると、**意図的に 401 を握り潰している既存箇所を壊す**: `AppHeaderBell.tsx:96`（未ログイン時は静かに無視）、`notifications/page.tsx:233-235`（401 とパスワード不一致の区別）、`web/src/lib/line-link.ts:162`（401 → `reauth_required` 再認証フロー）。→ 共通層は「文言差し替え」に留め、リダイレクトは呼び出し側でオプトインするか、除外リストを明示すること。
2. 単純な `router.push("/operator/login")` では不十分。NextAuth セッションは生存しているため `signOut({ callbackUrl: "/operator/login" })`（`OperatorHeader.tsx:71,109` と同型）を使わないと、ヘッダー表示・middleware 判定がログイン済みのまま残る。
3. `/operator/login` には「ログイン済みなら追い出す」処理が無い（`web/src/app/operator/login/page.tsx` に該当分岐なし）ため、リダイレクトループの懸念は無い。
4. バックエンド文言の日本語化は `deps.py:21-25` の変更で足り、**config.py / main.py には触れない**（別セッション編集中）。

## R3-H2（減額申請の承認／却下が業者に通知されない）— **CONFIRMED / High 妥当**

根拠（自力再確認）:
- `backend/app/api/v1/endpoints/reductions.py:100-131` — `decide_reduction` 全文を読了。`BackgroundTasks` を引数に取っておらず、notify/dispatch 呼び出しは **1 行も無い**（`session.commit()` → `refresh` → return のみ）。
- `backend/app/services/notify_dispatch.py` の `def dispatch_*` は 71/85/101/113/127/145 の 6 本のみ（bid_selected / bank_account_changed / bid_lost / schedule_confirmed / bid_received / message_received）。reduction 系は **不在**。台帳どおり。
- `web/src/app/operator/transactions/page.tsx:45,92` — `attentionCount` もバッジも `has_pending_reduction` のみ。`backend/.../transactions.py:91-93` で当該フラグは `r.status == "pending"` の any 判定＝決定と同時に false 化。「静かに消える」は真。
- `web/src/app/operator/transactions/[id]/page.tsx:145,171` — `pendingReduction` は `status==="pending"` 限定。同ファイルに `setInterval` / ポーリングは無い（grep 0件を再確認）。
- 承認時に `final_amount` が書き換わることも確認（`reductions.py:126-128`）。業者が旧額で対応するリスクの記述は妥当。

**修正案への注意**: `dispatch_reduction_decided` 新設は `dispatch_bid_selected`（`bids.py:307-` の `background.add_task(...)` パターン）と同型で成立する。ただし `decide_reduction` は現状 `BackgroundTasks` を受け取っていないため引数追加が必要で、**commit 後にプリミティブ値（line_user_id / email / 文字列）だけを渡す**規約（`bids.py:265-267` のコメントで明文化された「ORM オブジェクトを BackgroundTasks に渡さない」）を必ず踏襲すること。ORM の `reduction` / `txn` をそのまま渡すと detach 後に落ちる。

## R3-M1（規約の8%と fee_amount=0 の矛盾）— **PARTIAL（事象は真だが、根拠・修正範囲が不完全。重大度は Medium 据え置き）**

真であることの確認:
- `backend/app/api/v1/endpoints/bids.py:277` — `Transaction(..., fee_amount=0, ...)`。生成時固定。
- `backend/app/api/v1/endpoints/transactions.py:225-246` — `complete_transaction` は `final_amount` と `status` のみ更新。`fee_amount` 再計算なし。
- grep 全域: `fee_amount` の非テスト参照は `bids.py:277` / `db/models/transaction.py:40`(default=0) / `schemas_katadzuke.py:645` / `katadzuke-api.ts:193` / `chat/[id]/page.tsx:518` のみ。**8% を算出・保存する経路は backend に存在しない**。台帳の主張は真。
- `web/src/app/operator/chat/[id]/page.tsx:517-519` — `completed` で `yen(detail.fee_amount)`（=¥0）、それ以外は `×0.08` の予定額。完了の瞬間に表示が食い違う。真。
- `docs/beta-operator-onboarding.md:35` に「手数料は無料です（β期間中）」。アプリ内の β 無料表記は grep 0 件。真。

**PARTIAL とした理由（修正範囲の欠落。台帳どおり3画面だけ直すと矛盾が残る）**:
台帳が挙げた `terms/TermsTabs.tsx:144`・`business/page.tsx:43,54,76`・`operator/profile/page.tsx:697` 以外にも「無条件8%」表記が存在する。
- `web/src/app/legal/page.tsx:111-113` — **特定商取引法表記ページ**に「成約時に登録業者が支払う手数料：買取金額の8%」。法定表示面であり、ここを直さずに規約だけ直すと表示の整合が崩れる（最優先で是正すべき箇所）。
- `web/src/app/faq/page.tsx:33`、`web/src/app/page.tsx:421`（トップ「成約時8%のみ」）、`web/src/app/business/page.tsx:275`、`web/src/app/operator/page.tsx:256`（業者ダッシュボード内「成約時のみ買取額の8%が手数料」）。
- さらに文書間の不整合: `docs/business_plan_katazuke_20260831.md:351,455` は正式ローンチ時の手数料率を **15%** と置いている（UI 全面の 8% と不一致）。β無料の注記を入れる際、この 8%/15% のどちらを正とするかを先に確定しないと、注記自体がまた陳腐化する。

**重大度**: Medium 妥当（High に上げない）。実課金額（0円）は表示額（8%）より**少ない**方向の乖離であり、業者への過大請求は発生しない。リリース判定上は「実装ではなく表記のみ」で解消可能。
**修正案への注意**: 台帳の (b)「`complete_transaction` で fee_amount を算出・保存」は**リリースには不要**であり、β無料方針と正面から矛盾する（実装すると 0 でない請求根拠が DB に残る）。リリース時点では (a) の表記是正のみに限定し、(b) は課金開始判断とセットで別 Issue にすること。

## R3-M2（入札 409 後に案件状態が再取得されない）— **CONFIRMED / Medium 妥当**

根拠（自力再確認）:
- `web/src/app/operator/cases/[id]/page.tsx:87-105` — `try { createBid; setBidDone(true); await reload(); } catch (err) { setError(toDisplayMessage(...)) }`。catch に `reload()` なし。真。
- `web/src/app/operator/page.tsx:379-395` — `confirmBid` も同型（`await reload()` は成功パスのみ、catch は `showToast` のみ）。真。
- 409 分岐の実在: `backend/app/api/v1/endpoints/bids.py:120-124`（`case.status not in ("open","bidding")` → 409「この案件は入札を受け付けていません。」）。真。同 125-138 に「既に入札済み」「取り下げ済みで再入札不可」の 409 も存在。
- `cases/[id]/page.tsx:130` の `canBid` は `caseData.status` 依存のため、reload しない限りフォームが残り続けるという因果も成立。

**修正案への注意**: catch 内 `void reload()` は妥当だが、409 の種類で望ましい挙動が異なる。「取り下げ済みのため再入札不可」（`bids.py:129-133`）と「既に入札済み」（134-138）は案件が閉じたわけではないため、reload 後もフォーム消滅ではなく `my_bid` 反映で自然に解決する。一方、案件が closed/cancelled 化した場合は `getCaseMasked` が 404/403 を返す可能性があり、その際は現状の `if (!caseData)` 分岐（`cases/[id]/page.tsx:120-130`）が「案件が見つかりません。」を出す。エラー文言が上書きされて消えないよう、reload 前の `setError` を保持する順序に注意。

---

## 「確認したが問題なし」節の抜き取り検証（2項目）

1. **状態遷移（pending/active/suspended）— 断定は正しい**。`deps.py:74-85` に `assert_operator_not_suspended` が定義され、`get_current_operator:136`、`get_current_actor:199` から呼ばれる。`get_verified_operator:141-162` は `vendor_status != "active"` を 403、加えて `is_suspended` を再度 403（`get_current_operator` 経由で既に弾かれるための冗長チェックだが無害）。業者トークンを受ける経路は `get_current_operator` / `get_verified_operator` / `get_current_actor` の 3 本のみで、停止ゲートを迂回する経路は見つからなかった。台帳の断定は真。
2. **公開プロフィール `/vendors/[id]` の情報露出 — 断定は正しい（むしろ台帳より堅い）**。`OperatorPublicProfileOut`（`schemas_katadzuke.py:993-1011`）に連絡先・住所・許可番号・license 画像は無し。`OperatorPublicOut`（同 107-118）も同様。`get_vendor_public_profile`（`operator_profile.py:164-209`）は停止業者を 404 化、レビューは `Review.reviewer_type == "user"` に加え `Review.hidden_at.is_(None)`（非表示化済みレビューの除外・台帳は言及なし）でフィルタ。公開される `PublicReviewOut`（同 750-759）は id/rating/comment/created_at のみで**投稿者識別子を一切含まない**。PII 非露出は真。

---

## 追加発見（台帳に無い High／同一観点の見落とし）

### ADD-1（High）成約キャンセルが相手方に一切通知されない — 業者が解約済み現場へ訪問しうる
- `backend/app/api/v1/endpoints/transactions.py:248-279` — `cancel_transaction` は `BackgroundTasks` を**引数に取っておらず**、notify/dispatch 呼び出しがゼロ。`txn.status="cancelled"` / `case.status="cancelled"` を書いて commit するのみ。
- 依頼者がキャンセルした場合、業者へメール・LINE いずれも飛ばない。業者側の発見手段は `/operator/transactions` を能動的に再訪することのみ（同一覧にポーリング無し: `transactions/page.tsx:38-43` は初回 `useEffect` の 1 回だけ）。
- 影響: 訪問日確定済み（`dispatch_schedule_confirmed` は `transactions.py:490` で通知済み＝業者は訪問日を認識している）案件がキャンセルされても業者は知らず、**当日現地へ出向く**。R3-H2 より実害が大きい。
- 対比根拠: 落選通知は `bids.py:308` / `cases.py:456`、メッセージは `transactions.py:370`、日程確定は `transactions.py:490` と、他の状態遷移には dispatch が入っている。キャンセルだけが穴。

### ADD-2（High）減額申請の**送信**も依頼者に通知されない — 業者が回答不能状態で無期限にブロックされる
- `backend/app/api/v1/endpoints/reductions.py:56-95` — `create_reduction` も `BackgroundTasks` 無し・dispatch 無し。依頼者は「減額申請が来た」ことをメール/LINEで知らされない。
- かつ `reductions.py:69-73` により **pending が 1 件でもあると次の申請が 409** で拒否される。依頼者が気づかない限り、業者は減額申請を出したまま撤回も再申請もできない（撤回 API は存在しない: `reductions.py` に DELETE/withdraw エンドポイント無し）。
- R3-H2（decided → 業者）と合わせ、減額フローは**往路・復路とも通知がゼロ**。台帳は復路のみを起票しており、往路の欠落を見落としている。

### ADD-3（High）NextAuth セッション（30日）が backend JWT（7日）より長く、8日目に全業者が英語 401 で静かにロックアウトされる
- `web/src/auth.ts:149`（`session: { strategy: "jwt" }`・maxAge 未指定＝既定30日）× `backend/app/config.py:59`（`jwt_expire_minutes = 60*24*7`）／`backend/.env.example:48`。
- `web/src/middleware.ts:50-79` はセッションの有無と `accountType` しか見ないため、期限切れ accessToken を持つ業者を `/operator` 配下に通してしまう。結果 R3-H1 の症状が「事故」ではなく「仕様上の必然」として全業者に発生する。
- 修正は web 側（`auth.ts` の `session.maxAge` を backend の JWT 有効期限に合わせる、または jwt callback で `exp` 検証して失効させる）で行うこと。**`backend/app/config.py` の値変更で辻褄を合わせるのは不可**（別セッション編集中のため本検証では却下）。

---

## (b) この台帳の全項目を修正しても業者導線がリリース可能にならないケース

**ある。** 「成約後の状態変化が業者に届かない」という穴が台帳の 4 項目の外側に残るため。具体的には、依頼者が訪問日確定後に成約をキャンセルしても業者に何の通知も行かず（ADD-1: `transactions.py:248-279`）、業者は解約済みの現場へ実際に出向く。R3-H1（401 文言）・R3-H2（減額の回答通知）・R3-M1（8%表記）・R3-M2（409 後の再取得）をすべて直しても、この経路は 1 行も変わらない。業者が現地に空振り訪問する事故は信用・実費の両面で不可逆であり、クローズドβであっても招待業者の離脱に直結する。よってリリース前提条件は「台帳4件 + ADD-1 + ADD-2（減額往路通知）」であり、最低限 ADD-1 は必須。

---
判定サマリ: CONFIRMED 3 / PARTIAL 1 / REJECTED 0 / 追加 High 3。台帳は誤検知ゼロ（起票された事象はすべて実コードで再現可能）だが、R3-M1 の修正範囲が法定表示面（`/legal`）を取りこぼしており、かつ通知欠落の観点で自らの H2 より重い ADD-1 / ADD-2 を見落としている。
