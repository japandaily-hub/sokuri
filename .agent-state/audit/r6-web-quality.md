# カタヅケ 導線監査 第6周（r6）— 画面品質・通知品質

監査日: 2026-09-04 / 対象: web/（Next.js 15 App Router 全50ルート）, backend/app/services/notify.py・line_notify.py・notify_dispatch.py
既知・意図的未対応（docs/TODO.md 03）は再指摘しない。デザイン意匠（明朝・角丸0・#1447e0）は対象外。

## High / Medium 台帳

### H1. アカウント停止（依頼者・業者）で通知が一切飛ばない
- **重大度**: High
- **箇所**: `backend/app/api/v1/endpoints/admin.py:359`（`suspend_operator` の `operator.is_suspended = body.suspended` 直後）、`backend/app/api/v1/endpoints/admin.py:753-755`（`suspend_user` の `target.is_suspended = ...` 直後）
- **事象**: 両エンドポイントとも `notify` / `line_notify` / `notify_dispatch` の呼び出しが一切ない（`admin.py` 全体で notify を import・使用しているのは operator application の承認/却下の2箇所のみ、r6実測で確認済み）。停止された本人は次回操作で 403（`assert_operator_not_suspended` / `assert_user_not_suspended`）を突然食らうだけで、理由も解除方法も知らされない。解除時も同様に無通知。
- **再現**: 管理画面 `/admin/users` または `/admin` から任意アカウントを停止 → 対象アカウントでログイン・操作 → 403 のみ。メール・LINEに何も届かない。
- **修正案**: `notify.py`/`line_notify.py`/`notify_dispatch.py` に `send_account_suspended` / `push_account_suspended`（理由・解除条件・問い合わせ導線を含む）を追加し、`suspend_operator`/`suspend_user` の commit 後に `background.add_task` で発火する。

### H2. 本人確認書類の承認・却下で通知が一切飛ばない
- **重大度**: High
- **箇所**: `backend/app/api/v1/endpoints/admin.py:1252`（`approve_identity_document`）、`backend/app/api/v1/endpoints/admin.py:1326`（`reject_identity_document`、`reject_reason` を DB には保存するが通知はしない）
- **事象**: 却下理由 `body.reject_reason` は `UserIdentityDocument.reject_reason` に保存され `/mypage/identity` で閲覧はできるが、却下されたこと自体をユーザーへ能動的に知らせる手段（メール／LINE）が無い。ユーザーは自発的に `/mypage/identity` を再訪しない限り、なぜ振込先登録や入札等の下流機能がブロックされたままか分からない。
- **再現**: 管理画面 `/admin/identity-documents` で書類を却下 → 対象ユーザー宛のメール／LINEを確認 → 何も届かない。
- **修正案**: `send_identity_document_reviewed(approved: bool, reason: str | None)` を追加し、承認・却下の両commit後に dispatch する。

### H3. 業者の入札可否切替（vendor_status 遷移）で通知が一切飛ばない
- **重大度**: High
- **箇所**: `backend/app/api/v1/endpoints/admin.py:315-340`（`verify_operator`。`operator.vendor_status = "active" if body.verified else "pending"`）
- **事象**: 事前申込の承認（`approve_operator_application`, admin.py:1067）とは別に、実際に入札権限を on/off する `verify_operator` には notify 呼び出しが無い。業者は「入札できるようになった／できなくなった」ことを画面を能動的に確認するまで知らない。
- **再現**: `/admin` の業者一覧から pending → active（または逆）に verify 操作 → 対象業者にメール／LINE届かず。
- **修正案**: `verified` の真偽で `send_operator_verified` / `send_operator_unverified` を出し分けて dispatch。

### H4. root layout の canonical（`alternates.canonical: "/"`）が全公開ページに継承され、個別ページの canonical が実質すべてトップページを指す
- **重大度**: High
- **箇所**: `web/src/app/layout.tsx:47`（`alternates: { canonical: "/" }`）／`web/src/app/company/page.tsx:5-9` ほか `metadata` を export する44ファイル中、`alternates` を自前で上書きしているのは `web/src/app/photo-guide/page.tsx` のみ（r6実測: `grep -rl "alternates" web/src/app` の結果は layout.tsx とphoto-guide/page.tsxの2件のみ）
- **事象**: Next.js の Metadata API は `alternates` をページ単位でエクスポートしない限り最も近い祖先（ここではルート layout）の値をそのまま継承する。company/faq/contact/legal/privacy/terms/business/examples/vendors 等、SEO投資（title/description/OGP）をしている公開ページの canonical タグが軒並み `https://sokuri.vercel.app/` になり、検索エンジンにトップページの重複ページとして扱われうる。
- **再現**: 各ページの生成HTMLの `<link rel="canonical">` を確認（`photo-guide` 以外は自ページURLでなくトップURLになるはず）。
- **修正案**: 各 `page.tsx` の `metadata` に `alternates: { canonical: "<自ページパス>" }` を追加する共通ヘルパーを作る。

### M1. 公開admin系の共有 ConfirmModal に focus trap・Esc・初期フォーカスが無い
- **重大度**: Medium
- **箇所**: `web/src/app/admin/_components/ConfirmModal.tsx`（全体。`role="dialog" aria-modal="true"` はあるが keydown リスナー・focus trap・オープン時フォーカス移動が無い）
- **事象**: このモーダルは `admin/page.tsx`・`admin/users/page.tsx`・`admin/operator-applications/page.tsx`・`create/page.tsx`・`operator/page.tsx`・`schedule/page.tsx` から共有され、停止／却下等の破壊的操作の確認に使われる。一方 `web/src/app/notifications/page.tsx:191` と `web/src/app/operator/transactions/[id]/page.tsx:86` は独自に Escape ハンドラを実装済みで、パターン自体はチーム内に存在するのに最も再利用されるコンポーネントに反映されていない。キーボードユーザーは Tab で背景要素へ抜けられ、Esc でキャンセルもできない。
- **再現**: `/admin/users` で停止確認モーダルを開き、Tab を連打 → 背景の一覧行やナビゲーションにフォーカスが移る。Esc を押しても閉じない。
- **修正案**: ConfirmModal に `useEffect` で mount 時フォーカス・`keydown(Escape)→onCancel`・簡易 focus trap（Tab/Shift+Tab を dialog 内で循環）を追加する。

### M2. 入札ゼロで放置された案件の検知・通知の仕組みが存在しない
- **重大度**: Medium
- **箇所**: `backend/app/services/notify_dispatch.py`（全体。イベント一覧に「入札ゼロ放置」相当が無い）／バックエンド全体に cron・scheduler・batch の仕組み自体が無い（r6実測: `find backend -iname "*scheduler*" -o -iname "*cron*" -o -iname "*batch*"` は `.venv` 内のライブラリコードのみヒットし、アプリ側の実装は0件）
- **事象**: 依頼者が案件を出品しても入札が全く付かないまま放置された場合、それを検知して依頼者にリマインド（条件緩和の提案・運営への相談導線）を送る仕組みがコード上に存在しない。プロンプトの想定課題どおりの欠落。
- **再現**: コードベース全体で該当機能なし（再現ではなく不在の確認）。
- **修正案**: 案件作成から N 時間経過かつ bid 0 件を検出する軽量バッチ（Render Cron Job 等）＋ `notify_dispatch.dispatch_no_bid_reminder` を新設。

### M3. `web/src/app/sitemap.ts` にトップページ以外の公開ページが一切含まれていない
- **重大度**: Medium
- **箇所**: `web/src/app/sitemap.ts:11-18`（配列要素が `/` の1件のみ）
- **事象**: `robots.ts:18` が明示的にクロール禁止しているのは `/analyzing` `/condition` `/result` の3つだけで、`company` `faq` `contact` `legal` `privacy` `terms` `business` `examples` `photo-guide` `vendors` `login` `signup` 等はクロール許可されているにもかかわらず、sitemap には載っていない。title/description/OGP を個別に整備した公開ページ群が検索エンジンからの発見性で損をする。
- **再現**: `/sitemap.xml` を開く → `/` の1URLのみ。
- **修正案**: 静的な公開ページ（company/faq/contact/legal/privacy/terms/business/examples/photo-guide/vendors）を sitemap 配列に追加する。

### M4. LP以外のページで next/image が使われず、`<img>` に width/height/loading 指定が無いものが混在
- **重大度**: Medium
- **箇所**: `web/src/app/create/page.tsx:532,588,675`（アップロード写真プレビュー）、`web/src/app/operator/cases/page.tsx:65`、`web/src/app/operator/cases/[id]/page.tsx:155,204`、`web/src/app/operator/transactions/[id]/page.tsx:224`、`web/src/app/admin/identity-documents/page.tsx:327,340`、`web/src/app/mypage/identity/page.tsx:78`
- **事象**: トップページ（`web/src/app/page.tsx`）の装飾アイコンは `width={512} height={512} loading="lazy" decoding="async"` を全箇所で明示済みで良好だが、上記の実データ画像（出品写真・本人確認書類プレビュー）は寸法指定が無くCLS要因になりうる。加えて全ページ中 `next/image` 使用は1件のみ（r6実測: `grep -rln "next/image" web/src/app web/src/components` が1件）。
- **再現**: 低速回線で `/create` の写真アップロード後プレビューやオペレーター側の案件詳細を開くと、画像読込前後でレイアウトが動く。
- **修正案**: アップロード系プレビューにも `width`/`height`（アスペクト比CSSでも可）を付与する。next/image 未採用は外部Blob URL（署名付きURL等）のため意図的な可能性があり、その場合はコメントで明記する。

## 通知マトリクス（イベント × チャネル）

| イベント | 依頼者 メール | 依頼者 LINE | 業者 メール | 業者 LINE | 備考 |
|---|---|---|---|---|---|
| 案件登録完了 | ○ `send_case_created` | × | - | - | ユーザー宛LINE版が存在しない（dispatch層を経由せず cases.py:258 で直接メール呼び出し） |
| 新規入札 | ○ | ○ | - | - | `dispatch_bid_received` |
| 落札（選定） | - | - | ○ | ○ | `dispatch_bid_selected` |
| 落選 | - | - | ○ | ○ | `dispatch_bid_lost` |
| 訪問日程確定 | - | - | ○ | ○ | `dispatch_schedule_confirmed` |
| 減額相談の申請 | ○ | ○ | - | - | `dispatch_reduction_requested` |
| 減額相談の可否決定 | - | - | ○ | ○ | `dispatch_reduction_decided` |
| 成約キャンセル | ○ | ○ | ○ | ○ | `dispatch_transaction_cancelled`（相手方のみ） |
| 振込先口座 登録/変更/削除 | ○ | ○ | - | - | 両チャネル送信（フォールバックでなく併用） |
| 新着チャットメッセージ | × | ○ | × | ○ | LINEのみ・5分デバウンス。メール版は意図的に未実装（notify_dispatch.py:203） |
| 業者事前申込 受付 | - | - | ○ | × | 業者はまだLINE未連携が前提の申込段階 |
| 業者事前申込 admin通知 | ○(admin宛) | × | - | - | |
| 業者事前申込 承認（招待コード） | - | - | ○ | × | |
| 業者事前申込 却下 | - | - | ○ | × | |
| お問い合わせ受付 | ○(admin宛) | × | - | - | |
| **アカウント停止/解除（依頼者）** | **×** | **×** | - | - | **H1: 通知経路そのものが未実装** |
| **アカウント停止/解除（業者）** | - | - | **×** | **×** | **H1: 同上** |
| **本人確認 承認/却下** | **×** | **×** | - | - | **H2: 通知経路そのものが未実装** |
| **業者 入札可否切替（verify）** | - | - | **×** | **×** | **H3: 通知経路そのものが未実装** |
| **入札ゼロ放置リマインド** | **×** | **×** | - | - | **M2: イベント自体が存在しない（検知バッチ無し）** |

## 保存パス
`C:\Users\ko13h\Claude\Projects\ソクウリ\.agent-state\audit\r6-web-quality.md`
