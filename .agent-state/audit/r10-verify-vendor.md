# r10 業者導線監査 — 独立検証（r10-verify-vendor）

検証者: 立案者と無関係な独立QA。対象台帳 `.agent-state/audit/r10-vendor.md`（High 4 / Medium 6）。
方法: 全項目の file:line を実読。読み取りのみ、コード変更なし。
結論: **CONFIRMED 6 / PARTIAL 3 / REJECTED 0**。ただし **重大度は 3 件を下方修正、1 件を下方修正**（H4→Medium、M1→Low、M3→Low、M6→Low）。
再較正後: **High 3 / Medium 3 / Low 4**（＋独立発見 High 1）。

---

## High の検証

### R10-V-H1 訪問確定日時が業者UIに出ない → **PARTIAL / High → Medium**
- 事実は確認。`web/src/app/operator/` 配下に `visit_date` / `visit_time_slot` / `formatVisitSchedule` の参照は **0 件**（grep 実施。ヒットは `operator/page.tsx:19,20,412,531` の「訪問」文言と `transactions/[id]/layout.tsx:6` の description のみ）。取引詳細（`web/src/app/operator/transactions/[id]/page.tsx:165-360` を実読）には訪問日程の描画が無い。
- **ただし PARTIAL**: 日程確定時に backend がシステムメッセージを作る。`backend/app/api/v1/endpoints/transactions.py:724-735` が `confirm_body = f"訪問日程が {body.visit_date} {body.visit_time_slot} に確定しました。"` を `kind="schedule_confirmed"` で保存し、業者チャットは全メッセージの `m.body` をそのまま描画する（`web/src/app/operator/chat/[id]/page.tsx:422`）。**日時はチャットに必ず表示される**。「業者UIのどこにも表示されない」は誤り。正しくは「取引詳細・取引一覧に出ず、チャットのスクロールバックにしか無い」。
- 重大度: 情報の欠落ではなく**発見性の問題**。訪問当日の取り違えリスクは残るため Medium が妥当。
- 修正案: 妥当。`transactions/[id]` 概要カードへ `formatVisitSchedule(txn.visit_date, txn.visit_time_slot)` を追加（`web/src/lib/categories.ts:20`、依頼者実装 `web/src/app/cases/[id]/page.tsx:848` と同型）。一覧への追加は任意。

### R10-V-H2 当事者間精算の説明が業者UIに無い → **CONFIRMED / High 維持**
- `web/src/app/operator/` 配下に「精算 / 当事者間 / 入金 / 支払 / 振込 / 代金」は **0 件**（grep 実施。`operator/chat/[id]/page.tsx:539-541` の手数料コメントのみ）。取引詳細の開示カードは住所と `contact_email` だけ（`web/src/app/operator/transactions/[id]/page.tsx:228-238` 実読）。
- 対称性が崩れている根拠が強い: 依頼者側は `web/src/app/mypage/bank-account/page.tsx:303`「買取代金の受け取り方法（現金・お振込み）は、成約後に**業者とチャットで調整します**」と案内し、`web/src/app/legal/page.tsx:147` は「当社が買取代金をお預かりしたり、ユーザーへお振込みしたりすることはありません」と宣言。**依頼者は業者と調整せよと言われ、業者は何も知らされていない。**
- 注意: `docs/TODO.md:25`（02 課題・構想）に「『入金はカタヅケ経由』がトップ・FAQ・業者向け・規約で一貫しているか」が未決として残る。除外対象は 01/03 のみなので本件は有効だが、**文言を入れる前に 02 の決着（当事者間精算で確定か）が必要**。
- 修正案: 妥当。ただし追加先は `transactions/[id]` の開示カード直下を最優先（成約直後に必ず通る）。

### R10-V-H3 完了確定が依頼者のみである旨の説明が無い → **CONFIRMED / High 維持**
- backend は `backend/app/api/v1/endpoints/transactions.py:418-422` で業者を 403「完了確定はユーザー側のみ行えます。」。業者の取引詳細は `web/src/app/operator/transactions/[id]/page.tsx` 全体で「完了」の文言 **0 件**（grep 実施。同ディレクトリのヒットは `profile/page.tsx:660,745`・`login/page.tsx:40,168`・`page.tsx:218,540` のみ）。評価カードは `:349` の `txn.status === "completed"` でのみ出現。
- 重大度: 訪問後に業者が次の手を持たない＝取引が滞留する。High 維持。
- 修正案: 妥当。`active`（pending/visiting）時に1文の常設案内で足りる。定型文ボタンは任意（過剰）。

### R10-V-H4 `/business` 完了画面 CTA → 先行登録 → 承認 409 → 詰み → **PARTIAL / High → Medium**
- 経路は全段確認。CTA 実在（`web/src/app/business/page.tsx:725-728`「招待コードでアカウントを作成」→ `/operator/signup`。直前 `:723` は「承認時は招待コードをお送りします」と矛盾）。招待コードは任意で、無しなら `vendor_status="pending"` で登録成立（`backend/app/api/v1/endpoints/auth.py:322-323,341-349`、トークンは `:378` で即時発行）。同メールの Operator が居ると承認は必ず 409（`backend/app/api/v1/endpoints/admin.py:1252-1261`）で、`application.status` は `received` のまま。
- **ただし PARTIAL — 「詰む」のは申込レコードだけで、業者は詰まない。** 別エンドポイント `PATCH /admin/operators/{id}`（`backend/app/api/v1/endpoints/admin.py:371-378`）が `vendor_status` を `active` にでき、これが承認の実経路（許可証画像の提出が条件）。業者は入札可能になる。台帳の「業者側は招待コードを待ち続ける」は、運営が正しい導線を知っていれば成立しない。
- 実害は 2 点に縮小: (a) `OperatorApplication` が永久に `received`（残る出口は `reject` のみで、承認済み業者に却下メールが飛ぶ）。(b) 申込者が CTA を信じて先行登録すると招待コード運用から外れる。
- 重大度: 運営の手順知識で回避可能／データ整合の問題に留まるため **Medium**。
- 修正案: **CTA 文言の変更のみ先行で十分**（「招待コードが届いたら本登録できます」＋リンク削除）。admin 側の「既存業者へ紐付けて approved で閉じる」分岐は妥当だが Medium 相当。

---

## Medium の検証

### R10-V-M1 案件詳細の入札フォームがダッシュボードと非対称 → **PARTIAL / Medium → Low**
- 非対称は事実。ダッシュボードは `BID_MIN/BID_MAX/BID_STEP` 検証＋`BID_RANGE_HINT`＋手数料8%・β注記（`web/src/app/operator/page.tsx:246-247,256-265`）。案件詳細は `min={1000} step={1000}` のみで max 無し（`web/src/app/operator/cases/[id]/page.tsx:266-276`）、JS 検証は `!Number.isFinite(value) || value <= 0` だけ（同 `:92-96`）、手数料の記載なし。
- 422 が「入札に失敗しました」に潰れる機構も再現可能: FastAPI の `detail` は配列で、`throwHttpError` の分岐は string / 非配列 object 前提（`web/src/lib/katadzuke-api.ts:726-732`）→ message は `HTTP 422` のまま → `toDisplayMessage` がプレースホルダ判定して fallback（同 `:2103-2105`）。
- **ただし 422 の握りつぶしは `docs/TODO.md:41`（03 積み残し）に既載 → その部分は REJECTED（重複）。** 新規性があるのは「TODO 03 が前提にする『入札額は事前検証で回避中』がこの画面では成立していない」点と手数料注記の欠落のみ。
- 重大度: 上限超過の入力は現実には稀（1億円）。手数料非表示の方が実害だが軽微。**Low**。

### R10-V-M2 「今月の成約」が pending を除外 → **CONFIRMED / Medium 維持**
- `web/src/app/operator/page.tsx:420-429` の `thisMonthActive` は `t.status !== "visiting" && t.status !== "completed"` を除外＝ **pending を数えない**。同 `:413-416` の `negotiatingTxns` は pending を含む。KPI は `:526-542` で「交渉中」と「今月の成約」が並置され、同一取引が片方に 1・片方に 0 として同時に見える。落札直後は全て pending なので**初回成約の業者は必ずこの矛盾に当たる**。
- 重大度: 規模に依らず初日から発生。Medium 妥当。修正案も妥当（`pending` を含める案を推奨）。

### R10-V-M3 KPI が先頭100件の切り詰め → **CONFIRMED / Medium → Low**
- `LIST_DEFAULT_LIMIT = 100`（`web/src/lib/katadzuke-api.ts:1530,1557`）。`hasMoreTxns` は `web/src/app/operator/page.tsx:295` で保持されるが使用は `:655,698`（「さらに読み込む」）のみで、KPI 帯（`:515-551`）には注記が無い。案件一覧側には注記あり（`web/src/app/operator/cases/page.tsx:227`）。非対称は事実。
- 重大度: 発現条件が「1業者あたり取引 100 件超」。ローンチ前の現規模では到達しない。**Low**（将来 High 化しうる負債として TODO 03 相当）。

### R10-V-M4 減額申請の上限2回が UI に出ない → **CONFIRMED / Medium 維持**
- backend は `backend/app/api/v1/endpoints/reductions.py:109-113` で `len(txn.reduction_requests) >= _MAX_REDUCTION_REQUESTS` → 409「減額申請は1つの取引につき2回までです。」。UI は `web/src/app/operator/transactions/[id]/page.tsx:278` の `active && !pendingReduction` だけでフォームを出し続け、残回数の表示は無い（`:260-323` 実読）。3回目は確認モーダル通過後に 409。
- 重大度: 現地で入力してから弾かれるため業務中に効く。Medium 妥当。修正案（`reduction_requests.length >= 2` でフォーム非表示＋残回数表示）は最小構成として妥当。

### R10-V-M5 業者の LINE 連携導線が無いのに文言が LINE を示唆 → **CONFIRMED / Medium 維持**
- `web/src/app/operator/` 配下の「LINE」ヒットは **1 件のみ**＝`web/src/app/operator/cases/[id]/page.tsx:221`「結果はLINE連携済みならLINE、未連携ならメールでお知らせします」。連携UI（`/api/line/link/start`）への参照は 0 件。`/notifications` は依頼者専用の保護ルート（`web/src/lib/protected-routes.ts:26`）。
- 重大度: **実装不能の約束を UI が明言している**（景表法・期待値の観点でも不利）。Medium 妥当。
- 修正案の最小構成は**後者**（`:221` の文言を「結果はメールでお知らせします」に戻す）。連携UIの新設は Medium 案件としては過大。

### R10-V-M6 文言揺れ（落札／成約・取引／案件） → **CONFIRMED / Medium → Low**
- 実在確認: `web/src/app/operator/transactions/[id]/page.tsx:135`「成約情報が見つかりません」・`:177`「落札額」・`:322`「この成約では申請できません」・`:343`「この成約をキャンセルする」が**同一ファイル内で混在**。ダッシュボードは `:534`「今月の成約」。
- 重大度: 誤操作・データ損失に繋がらない表記の一貫性問題。**Low**。用語表の一本化という修正案自体は妥当。

---

## 独立発見（台帳に無い High）

### VERIFY-A1 / High / 未審査の自己登録業者が全公開案件の室内写真と所在市区を閲覧できる
- `POST /auth/operator/signup` は招待コード無しで通り（`backend/app/api/v1/endpoints/auth.py:322-323,349`）、メール確認も無くその場でアクセストークンを発行する（同 `:378-383`）。生成される業者は `vendor_status="pending"`。
- 案件一覧はその `pending` を通す設計: `backend/app/api/v1/endpoints/cases.py:631-647`、コメント `:632-633`「案件の『閲覧』は vendor_status を問わず許可する（pending/limited/active いずれも可）。入札のみ get_verified_operator で別途ブロックする」。返るのは `_to_masked_out` だが、業者向け一覧には写真4枠・品目要約・都道府県/市区が含まれる（台帳 6 行目および `web/src/app/operator/cases/page.tsx:47-114`）。
- 帰結: **任意のメールアドレスで登録した第三者が、審査も本人確認も経ずに全依頼者の自宅内部写真と市区町村を閲覧できる。** 番地と氏名・電話は非開示だが、写真＋市区で特定に至りうる。
- 意図的設計（コメントで明示）だが、**リスクの所在が台帳の全19行に一度も現れていない**。最小の緩和: (a) signup にメール確認を必須化する、または (b) `pending` には写真をぼかす／点数と品目だけ返す（`_to_masked_out` に vendor_status 分岐）。少なくとも製品判断としてユーザーに提示すべき。

（High 追加は 1 件のみ。他に High 相当の見落としは検出せず。）

---

## 再較正後の一覧

| ID | 判定 | 重大度（台帳→検証） |
|---|---|---|
| H1 訪問日時 | PARTIAL | High → **Medium**（チャット本文には出る） |
| H2 当事者間精算 | CONFIRMED | High |
| H3 完了確定の主体 | CONFIRMED | High |
| H4 /business CTA 詰み | PARTIAL | High → **Medium**（業者は別経路で承認可） |
| M1 入札フォーム非対称 | PARTIAL | Medium → **Low**（422 部分は TODO 03 重複＝REJECTED） |
| M2 今月の成約の矛盾 | CONFIRMED | Medium |
| M3 KPI 100件切り詰め | CONFIRMED | Medium → **Low** |
| M4 減額上限の非表示 | CONFIRMED | Medium |
| M5 業者 LINE 導線欠落 | CONFIRMED | Medium |
| M6 文言揺れ | CONFIRMED | Medium → **Low** |
| **A1 未審査業者の案件閲覧** | 新規 | **High** |

着手順の推奨: H3 → H2（TODO 02 決着後）→ A1（製品判断）→ H4 の CTA 文言 → M5 の文言 → M2 → M4 → H1。
