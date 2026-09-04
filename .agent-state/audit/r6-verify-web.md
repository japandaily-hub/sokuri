# r6 独立検証 — web品質・通知監査台帳（r6-web-quality.md）の真偽判定

検証日: 2026-09-04 / 検証者: 独立QA（立案者と無関係）/ 方法: 全項目の file:line を実コードで再読
判定凡例: CONFIRMED=事実 / PARTIAL=中核は事実だが付随主張に誤り / REJECTED=事実誤認

## 集計
CONFIRMED 3（H3, H4, M3）／PARTIAL 4（H1, H2, M1, M2）／REJECTED 1（M4）
重大度の下方修正 4件（H1→Medium, H2→Medium, M1→Low, M4→Info）／維持 3件（H3, H4, M3）

---

## H1. アカウント停止/解除で無通知 — **PARTIAL / 重大度 High → Medium**
- 事実確認: `backend/app/api/v1/endpoints/admin.py:68` の `from app.services import alerts, notify` に対し、`notify` の実使用は **1066行・1110行の2箇所のみ**（業者事前申込の承認/却下）。`suspend_operator`（`admin.py:353-360` 付近、`operator.is_suspended = body.suspended` → `commit` → `logger.info` → `return`）にも `suspend_user`（`admin.py:751-756`、`target.is_suspended` / `suspended_at` / `suspended_reason` を保存）にも通知呼び出しは無い。**無通知は CONFIRMED。**
- 重大度を下げる根拠: 停止は運営の一方的な措置であり、悪質利用者へ理由を開示しない運用は正当にありうる。加えて `admin.py:752-753` で `suspended_reason` を保存済みであり、開示するかは運用ポリシーの選択であってコード欠陥ではない。一方 **「解除（suspended=false）」の無通知には正当化理由が無い**（復帰したことを本人が知る手段がゼロ）。
- 修正案への注意: 「理由・解除条件を送る」ことをデフォルトにしない。最小構成は **解除時のみ確実に通知＋停止時は理由を含めない定型文（問い合わせ導線のみ）**。また下記 A2 のとおり dispatch 層は LINE 優先→メール fallback の排他方式なので、`notify.py` 直呼びではなく `notify_dispatch` に新関数を置くこと（LINE専用ユーザーは仮メールで届かない）。

## H2. 本人確認書類の承認・却下で無通知 — **PARTIAL / 重大度 High → Medium**
- 事実確認: `approve_identity_document`（`admin.py:1252` 起点）・`reject_identity_document`（`admin.py:1326` 起点）とも通知呼び出し無し（H1と同じ grep 根拠）。`reject_reason` の DB 保存のみ。**無通知は CONFIRMED。**
- **却下の主張は REJECTED**: 「振込先登録や入札等の下流機能がブロックされたまま」の根拠が無い。`identity_status` の参照箇所は `backend/app/api/v1/endpoints/users.py:79`、`user_identity.py:129,149,152,221,274,289,308`、`db/models/user.py:34,80`、`schemas_katadzuke.py:183` のみで、**振込先登録・入札の各エンドポイントは identity_status を一切ゲートに使っていない**。よって「下流がブロックされ続ける」という被害シナリオは現状成立しない。
- 残る実害は「再提出が必要なことに気づけない」だけなので Medium。修正は `dispatch_identity_document_reviewed(approved, reason)` の1本で足りる。

## H3. 業者の入札可否切替（verify_operator）で無通知 — **CONFIRMED / High 維持**
- `admin.py:333-334` で `operator.verified_at` と `operator.vendor_status = "active"/"pending"` を書き換えた直後、`commit`→`logger.info`→`return` のみ（`admin.py:335-341`）。通知は無い。
- High 維持の根拠: 承認方向（pending→active）は**業者が待たされ続ける**唯一のゲートで、事前申込の承認メール（`admin.py:1066`）とは別イベント。ここだけ無通知だと業者は許可証提出後いつ入札可能になったか知る手段が無く、マッチング供給側が止まる。取消方向は Medium 相当なので、実装時は `verified` 真偽で文面を出し分ける方針（台帳の修正案）で妥当。

## H4. root layout の canonical が全公開ページに継承 — **CONFIRMED / High 維持**
- `web/src/app/layout.tsx:47` に `alternates: { canonical: "/" }`、`metadataBase` は `layout.tsx:28`。`grep -rn "alternates" web/src/app` の結果は **layout.tsx:47 と `web/src/app/photo-guide/page.tsx:11` の2件のみ**（台帳の実測と一致）。
- Next.js の Metadata はフィールド単位の浅いマージで、子が `alternates` を宣言しない限り最近祖先の値がそのまま解決される。よって photo-guide 以外の全ページの canonical が `https://sokuri.vercel.app/` になる、は真。
- 影響範囲は台帳より正確に限定できる: `web/src/app/*/layout.tsx` の23ファイルが `robots: { index: false, follow: false }` を持つため（admin/analyzing/applications/cases/chat/condition/create/mypage/notifications/operator/result/review/schedule 系）、実害を受けるのは **company・faq・contact・legal・privacy・terms・business・examples・vendors・vendors/[id]・login・signup・operator/login・operator/signup・password-reset・verify-email・unsubscribe** の公開ページ群。それでも SEO 投資済みページが全滅する構図は変わらないので High 維持。
- 修正案への注意: 共通ヘルパー化は良いが、`vendors/[id]` など動的ルートは `generateMetadata` 側での付与が必要。

## M1. ConfirmModal に focus trap・Esc・初期フォーカスが無い — **PARTIAL / 重大度 Medium → Low**
- 欠陥自体は CONFIRMED: `web/src/app/admin/_components/ConfirmModal.tsx:1-101` に `useEffect`・`onKeyDown`・`ref` が一切無く、import は `useState` のみ（同:10）。オーバーレイの `onClick={onCancel}`（同:53）だけが閉じる手段。
- 参照先の主張も CONFIRMED: `web/src/app/notifications/page.tsx:191-194` と `web/src/app/operator/transactions/[id]/page.tsx:82-91` に Escape ハンドラの実装あり。
- **利用箇所リストが誤り（REJECTED部分）**: 実際の import 元は `admin/page.tsx:21`・`admin/users/page.tsx:17`・`admin/operator-applications/page.tsx:28`・`admin/identity-documents/page.tsx:25` の **admin 配下4画面のみ**。台帳が挙げた `create/page.tsx`・`operator/page.tsx`・`schedule/page.tsx` は ConfirmModal を import していない（`notifications/page.tsx:215` のヒットは同名関数 `onConfirmModal` の誤検出）。台帳が漏らした `admin/identity-documents` を加えても、利用者は運営スタッフのみ。
- 「公開admin系」という表現も不正確（`web/src/app/admin/layout.tsx:7` で noindex、認証必須）。到達ユーザーが運営数名に限られるため Low。修正自体は10行程度で安価なので実施は妥当。

## M2. 入札ゼロ放置の検知・通知が無い — **PARTIAL / Medium 維持**
- 不在は CONFIRMED: `backend/app/services/notify_dispatch.py` の dispatch 関数は 71/85/101/119/133/147/164/178/196 行の9本のみで該当イベント無し。`grep -rn "APScheduler|celery|cron" backend/app` は **0件**（アプリ側スケジューラは実在しない）。
- PARTIAL の理由: これは「バグ」ではなく**未実装の新機能**であり、監査台帳の他項目（既存コードの欠陥）と粒度が異なる。ロードマップ項目として扱うべきで、修正PRのスコープに混ぜないこと。Render Cron Job の追加は運用コスト（新サービス・環境変数・多重起動制御）を伴うため、先に既存の `dispatch_*` 群と同じ fallback 規約に乗せる設計を確定させる必要がある。

## M3. sitemap.ts がトップページのみ — **CONFIRMED / Medium 維持**
- `web/src/app/sitemap.ts:11-18` は `${SITE_URL}/` の1要素のみ。`web/src/app/robots.ts:18` の disallow は `/analyzing` `/condition` `/result` の3件のみ。台帳の記述どおり。
- 修正案への注意: H4 と同一根（公開ページの発見性）なので**1PRでまとめて直すべき**。ただし `password-reset`（`web/src/app/password-reset/page.tsx` は「準備中」パネルのみ）・`verify-email`・`unsubscribe` は sitemap に入れず、むしろ noindex を足す側（下記 A2）。

## M4. `<img>` に width/height 指定が無く CLS 要因 — **REJECTED / Medium → Info**
- 指摘された `<img>` の存在自体は全て実在（`create/page.tsx:532,588,675`／`operator/cases/page.tsx:65`／`operator/cases/[id]/page.tsx:155,204`／`operator/transactions/[id]/page.tsx:224`／`admin/identity-documents/page.tsx:327,340`／`mypage/identity/page.tsx:78`）。**しかし「CLS要因になりうる」という結論が誤り** — いずれも親要素が CSS で寸法を確定させており、画像読込前後でレイアウトは動かない:
  - `create/page.tsx:532` → `.item-card-thumb` は `width:52px; height:52px`（`web/src/app/create/create.css:92-96`）
  - `create/page.tsx:588,675` → `.photo-thumb` は `aspect-ratio: 1`（`create.css:23`）
  - `operator/cases/page.tsx:65` → `.lot-thumb` が `grid-template-rows: 1fr 1fr` の固定グリッド（`web/src/app/mypage/mypage.css:281-296`）
  - `operator/cases/[id]/page.tsx:155` → `.listing-thumb` は `width:56px; height:56px`（`web/src/app/operator/operator-shared.css:272-280`）
  - `mypage/identity/page.tsx:78` → `.doc-thumb-frame` は `width:140px; height:96px`（`web/src/app/mypage/identity/identity.css:133-142`）
  - `admin/identity-documents/page.tsx:327,340` と `operator/transactions/[id]/page.tsx:224` はモーダル内＝ユーザー操作から500ms以内の変化で CLS 指標の対象外。
- 残る唯一の未確定は `operator/cases/[id]/page.tsx:204` の `.op-photo-grid img`（`operator-shared.css:83-89` は列幅 `minmax(84px,1fr)` のみで高さ未固定）。ここだけ `aspect-ratio:1` を足せば足りる、1行修正。
- 台帳が挙げなかった同種 `<img>`（`cases/page.tsx:76`／`cases/[id]/page.tsx:466`／`mypage/page.tsx:76`／`operator/page.tsx:155`／`admin/page.tsx:745`）も全て Tailwind もしくは inline style で寸法確定済み。
- `next/image` が `web/src/app/admin/page.tsx` の1件のみ、は CONFIRMED（ただしこれは指摘ではなく事実の記載）。

---

## 通知マトリクスの検証
- 記載された dispatch 名は全て実在: `dispatch_bid_selected`(notify_dispatch.py:71)・`dispatch_bank_account_changed`(85)・`dispatch_bid_lost`(101)・`dispatch_reduction_requested`(119)・`dispatch_reduction_decided`(133)・`dispatch_transaction_cancelled`(147)・`dispatch_schedule_confirmed`(164)・`dispatch_bid_received`(178)・`dispatch_message_received`(196)。**捏造なし。**
- `notify.py` 側も `send_case_created`(114)・`send_operator_application_received`(206)/`_admin_alert`(218)/`_approved`(230)/`_rejected`(334)・`send_contact_received`(316) が実在し、マトリクスの各行と一致。
- 「入札ゼロ放置」「停止」「本人確認」「verify」の×表記も、上記の grep 結果と整合。**マトリクスの網羅性は妥当。**
- ただし表記に重大な誤りが1点あり（下記 A2）。

---

## 追加発見（台帳の見落とし）

### A1. LINE専用ユーザーは「案件登録完了」通知を一切受け取れない — **High**
- 箇所: `backend/app/api/v1/endpoints/cases.py:257-258`
  ```python
  if not notify.is_placeholder_email(user.email):
      background.add_task(notify.send_case_created, user.email, str(case.id))
  ```
- LINE ログインで作られるユーザーは `backend/app/api/v1/endpoints/auth.py:794` で `line-{line_user_id}@line.katazuke.internal` の仮メールを持ち、`notify.is_placeholder_email`（`notify.py:41-51`）が真になる。よって **LINE専用ユーザーは案件登録完了通知がメールもLINEもゼロ**。
- 他の全イベントが `notify_dispatch` 経由で「LINE優先→メールfallback」を守っているのに対し、**この1本だけが `notify` 直呼びで設計不変条件を破っている**（マトリクスは備考欄に事実を書いているが、High 欠陥として立てていない）。LINE 連携は主要導線であり、出品直後という最重要タッチポイントで音沙汰なしになる。
- 最小修正: `dispatch_case_created(line_user_id, email, case_id)` を `notify_dispatch.py` に追加し、`line_notify.push_case_created` を新設して cases.py:257-258 を置換。既存9本と同じ `@_best_effort` + LINE優先パターンをそのままなぞれば10数行。

### A2. マトリクスの「○メール／○LINE」表記が実装の意味を取り違えている — **重大度 Medium（台帳自体の欠陥・修正設計を誤らせる）**
- `notify_dispatch.py:78-82`（bid_selected）、`110-116`（bid_lost）、`124-130`（reduction_requested）等は **LINE push が成功したらメールを送らない排他フォールバック**。両チャネル併用は `dispatch_bank_account_changed`（`notify_dispatch.py:96-98`）だけで、これは台帳も正しく注記している。
- しかしマトリクスは「新規入札」「落札」「落選」「訪問日程確定」「減額」「成約キャンセル」の各行を ○メール ＋ ○LINE と並べており、**実装では二者択一**であることが読み取れない。この誤読のまま H1/H2/H3 を修正すると「メールだけ実装すれば足りる」と判断され、LINE専用ユーザー（＝仮メール保持者）に届かない通知を量産する。
- 是正: マトリクスの該当セルを「LINE優先／未連携・失敗時にメール」に書き換え、併用は振込先変更のみと明示する。

---

## 保存パス
`C:\Users\ko13h\Claude\Projects\ソクウリ\.agent-state\audit\r6-verify-web.md`
