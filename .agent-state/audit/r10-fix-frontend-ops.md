# r10 業者・運営画面 修正実装（r10-fix-frontend-ops）

担当: フロントエンド実装（業者 `/operator`・`/business`・運営 `/admin`）。依頼者画面は別担当のため未着手。
検証: `npx tsc --noEmit` → **エラー 0**、`npx eslint src` → **エラー 0 / 警告 3（すべて既存・後述）**。`next build` は指示どおり未実行。

---

## 1. 契約（`web/src/lib/katadzuke-api.ts`）

backend 側の実装（同一 worktree の `backend/app/schemas_katadzuke.py`・`endpoints/admin.py`）を実読して 1:1 で突き合わせ済み。

| 変更 | 内容 |
| --- | --- |
| `TransactionDetail` | `reduction_request_count: number` / `reduction_request_limit: number` を追加（backend `TransactionDetailOut:805-806` と一致） |
| `AdminIdentityDocumentListResponse` | 新設。`{items,total,counts:{pending,approved,rejected}}`。`listIdentityDocumentsAdmin` の第1引数を `status` 単体からパラメータオブジェクト（`status`/`q`/`limit`/`offset`）へ変更 |
| `AdminIdentityStatusFilter` | `"pending"｜"approved"｜"rejected"｜"all"`。`IdentityStatus` をそのまま流用すると提出物の無い `unverified` が混ざるため独立定義 |
| `AdminOperatorListResponse.counts` | `pending_with_license: number` を追加 |
| `AdminListParams` | `suspended?: boolean` を追加（`buildAdminListQuery` は true のときのみ `suspended=true` を付与）。`adminListUsers` の受け口を `includeDeleted`/`suspended` まで拡張 |
| `AdminContactMessage` / `AdminContactListResponse` / `adminListContacts` / `adminHandleContact` | 新設（`GET /admin/contacts?handled=&limit=&offset=`・`PATCH /admin/contacts/{id}/handle`）。handle の応答 `handled_at` は backend が非null固定のため `string` で受ける |
| `AdminUserListItem.deleted_at?` | **任意フィールドとして追加（[推測]）**。後述の未対応 1 を参照 |

## 2. 業者側の修正

| 項目 | 実装 | ファイル |
| --- | --- | --- |
| H1 | 取引詳細の概要カードに「訪問日時 …／未確定（チャットで日程を提案してください）」を `formatVisitSchedule(visit_date, visit_time_slot)` で表示。取引一覧の各行にも「訪問日 …／未確定」を追加 | `operator/transactions/[id]/page.tsx`・`operator/transactions/page.tsx` |
| H2・H3 | 開示カード直下に「成約後の進め方」カードを新設。①買取代金は依頼者と直接精算（現金/振込・チャットで調整・カタヅケは送金を仲介しない）②作業完了は依頼者が確定・訪問後にチャットで完了確定を依頼、の2点。キャンセル済みでは非表示。`/business` FAQ にも「買取代金はどのように支払いますか？」を追加 | `operator/transactions/[id]/page.tsx`・`business/page.tsx` |
| H4 | 申込完了画面の本文を「**承認メールに記載の招待コードでアカウントを作成してください（メール到着までお待ちください）**」に変更。`/operator/signup` リンクは「招待コードがお手元に届いている方は…」の説明を上に添えて残置 | `business/page.tsx` |
| M1 | 入札フォームに `BID_MIN=1000`/`BID_MAX=100_000_000`/`BID_STEP=1000` を導入し、`submitBid` の検証（整数・範囲・刻み）と `min/max/step` をダッシュボードと同一化。8%（β無料）注記＋範囲ヒントを `aria-describedby` 付きで併記 | `operator/cases/[id]/page.tsx` |
| M2 | `thisMonthActive` を「`cancelled` のみ除外」に変更（pending を含める）。見出しを「今月の落札」、副文を「うち完了 N 件・成約額 ¥X（完了分のみ）」に | `operator/page.tsx` |
| M4 | フォーム上部に「申請できる残り回数: n回（上限2回）」。残り 0 のときはフォームを出さず「上限に達しているため申請できません。金額の相談はチャットで」と理由を表示 | `operator/transactions/[id]/page.tsx` |
| M5 | 入札受付メッセージを「結果は**登録メールアドレス**にお知らせします」に修正（業者に LINE 連携は無い） | `operator/cases/[id]/page.tsx` |
| M6 | 用語表（イベント＝成約／オブジェクト＝取引／金額＝成約額）に沿って「落札した案件の進行状況」「落札した案件はまだありません」「落札額」「この成約をキャンセルする」「この成約では申請できません」「成約情報が見つかりません」「落札状況は…」「成約済みの案件はまだ…」を是正。`落札` は入札結果チップ（`operator/cases/page.tsx:38`）にのみ残す | 業者4ファイル |
| O-H-1 | チャットのステータスバー直下に、`cancelled` かつ `cancellation` があるとき「キャンセル: {依頼者/業者/運営}による（日時）／理由」を表示（`overflowWrap:anywhere` で長文崩れを防止） | `operator/chat/[id]/page.tsx` |

## 3. 運営側の修正

| 項目 | 実装 |
| --- | --- |
| O-M1〜M3 | `/admin/identity-documents` を `{items,total,counts}` 契約へ切替。`StatusFilterBar`（審査待ち/承認済み/差し戻し/すべて＋counts 件数）、メール・氏名の部分一致検索（`qInput`→`q` の既存パターン）、`AdminPagination` に `total` を渡して末尾判定を正確化。`/admin` トップの「本人確認書類の審査へ」に `counts.pending` の赤バッジ（取得失敗時は「件数取得失敗」） |
| O-M4 | `/admin` 業者一覧のフィルタ直下に「pending N件（うち許可証提出済み M件＝いま審査に着手できる件数）」を併記 |
| O-M5 | `/admin/users` に「退会済みを含む」「停止中のみ」チェックボックス（変更時は `offset` を 0 に戻す）。退会済み行は `退会済み` バッジ＋操作ボタン非表示（業者一覧と同型） |
| O-M6 | **`/admin/contacts` を新設**（`web/src/app/admin/contacts/page.tsx`）。未対応/対応済み/すべての絞り込み、受信日時・氏名・メール・種別・本文・状態の一覧、`ConfirmModal` による「対応済みにする」、`AdminPagination`。`/admin` トップに「お問い合わせへ」導線＋未対応件数バッジ |
| 共通 | `/admin` の `Promise.allSettled` を 4本→6本に拡張（本人確認 counts・未対応問い合わせ）。1本が 5xx でも他区画は生存する既存方針を維持 |

XSS: 問い合わせ本文・氏名・メール・キャンセル理由はいずれも JSX テキストノードとして描画（`dangerouslySetInnerHTML` は不使用）。長文は `whitespace-pre-wrap break-words` / `overflowWrap:anywhere` で表示崩れのみ抑止。

## 4. 未対応・要確認

1. **`AdminUserListItem.deleted_at` が backend 未実装**（`schemas_katadzuke.py:1021-1031` に無い）。フロント側は任意フィールドとして受ける実装にしてあるため型・描画は壊れないが、**「退会済みを含む」を ON にしても運営はどの行が退会済みか判別できない**。backend に 1 フィールド追加が必要（要 backend 担当）。
2. **取引一覧の訪問「時間帯」が出ない**。`TransactionListItem` に `visit_time_slot` が無いため一覧は日付のみ（時間帯は取引詳細で表示）。契約固定の指示に従い一覧側は日付表示に留めた。
3. **M2 と M6 の指示が競合**。M6 の用語表は「イベント＝成約」だが、M2 は見出しを「今月の落札」と明示していたためリーダー指示を優先。結果として業者画面に残る `落札` は ①入札結果チップ ②このKPI見出し の 2 箇所。どちらかに寄せる場合は要指示。
4. `eslint` 警告 3 件はいずれも**既存**（`notifications/page.tsx:196`・`signup/page.tsx:47` は他担当領域、`operator/transactions/[id]/page.tsx:90` は今回変更していない Escape ハンドラの stale disable directive）。無関係な差分を増やさないため未修正。
5. `/business` FAQ の「カタヅケがやり取りするのは成約時の手数料のみです」は既存の手数料 FAQ・`/legal` と整合させた文言。`docs/TODO.md:25` の「入金はカタヅケ経由か」の論点が当事者間精算で確定していることを前提にしている。
