# r3 フロントエンド実装（5項目）— 実装結果

対象根拠: r3-user.md/verify-user.md（H1・H3・A1）、r3-vendor.md/verify-vendor.md（R3-H1・R3-M2・ADD-3）、
r3-operator.md（H1）。tsc --noEmit / eslint src とも 0 エラー。

---

## 1. 401共通処理

- 対応内容: `katadzuke-api.ts` の共通 `request<T>()` および全ての raw-fetch 関数
  （`uploadOperatorLicenseImage`/`uploadCasePhoto`/`uploadIdentityDocument`/
  `fetchMyIdentityDocumentBlob`/`fetchIdentityDocumentBlobAdmin`/`adminGetOperatorLicenseImage`）を
  新設の共通ヘルパー `throwHttpError()` に統一。401 検知時は backend の英語 detail を破棄し、
  `SESSION_EXPIRED_MESSAGE`（「セッションの有効期限が切れました。もう一度ログインしてください。」）を
  `KdzApiError` に載せて throw。同時に `handleSessionExpired()` が NextAuth `signOut({redirect:false})` を
  実行し、現在のパスが `/operator` 配下かで役割別ログイン画面（`/login` or `/operator/login`）へ
  `callbackUrl` 付きで `window.location.href` 遷移。モジュールスコープの `sessionExpiredHandled` フラグで
  同時多重401（複数リクエスト同時失敗）でも signOut/遷移は1回のみ。
  `request()` には `skipAuthRedirect` オプションを追加済み（本ファイル内では未使用＝現状すべての401は
  真の失効ケースのため opt-out 不要）。
  `auth.ts` に `session.maxAge`/`updateAge` を backend JWT と同じ7日（`60*60*24*7`）に設定（補助対策。
  verify-user.md の指摘通り updateAge のスライドを止めるため maxAge と同値にした）。
- 変更ファイル:行:
  - `web/src/lib/katadzuke-api.ts:8`（import signOut）、`:495-556`（SESSION_EXPIRED_MESSAGE/handleSessionExpired/throwHttpError）、
    `:559-588`（request 本体に skipAuthRedirect 追加・throwHttpError 呼び出しへ統一）、
    ほか6箇所の raw-fetch関数を `await throwHttpError(res)` に置換（uploadOperatorLicenseImage/uploadIdentityDocument/
    fetchMyIdentityDocumentBlob/fetchIdentityDocumentBlobAdmin/adminGetOperatorLicenseImage/uploadCasePhoto）。
  - `web/src/auth.ts:147-159`（session.maxAge/updateAge = 7日）。
- 隣接・複製伝播チェック: `web/src/lib/api.ts` はトークンを一切使わない公開APIのみ（analyze/estimate等）のため
  401対応は不要と確認（grep で token/Authorization 参照なしを確認済み）。`web/src/lib/line-link.ts:162` は
  本ファイルの `request()` を使わず独自 fetch で 401 を `reauth_required`（正常系）として扱っており、
  今回の自動リダイレクトの影響を受けない＝**opt-out のための変更は不要**（コード変更なし）。
- 未対応・理由: backend側の英語 detail 自体の日本語化は編集除外（`backend/app/config.py`等）のため対象外
  （フロント側の防御で日本語表示は達成済み）。

## 2. /create の保護（H3・A1）

- 対応内容:
  - **beforeunload**: 写真1枚以上で `preventDefault()+returnValue=""`（ブラウザ標準ダイアログ。文言はブラウザ固定のためカスタム不可）。
  - **ブラウザバック**: 写真が0→1枚になった時点で履歴に番兵エントリを1つ push。`popstate` 検知時に即座に
    再pushして離脱を一旦キャンセルし、ブランドの確認モーダル（「入力中の内容が失われます」/「ページを離れる」/
    「入力を続ける」）を表示。「ページを離れる」選択時は `history.go(-2)`（番兵1つ＋元の/createエントリ分）で
    実際に離脱。window.confirm は不使用。
  - **送信中バナー**: `submitting` 中に「AI解析には最大2分ほどかかることがあります。この画面を閉じないでください。」を
    既存 `.hint-banner` 語彙で表示。
  - **タイムアウト**: `createCase()` に `signal?: AbortSignal` を追加し、呼び出し側で `AbortSignal.timeout(180_000)` を付与。
    `AbortSignal.timeout` による中断は `KdzNetworkError.cause` が `DOMException("TimeoutError")` になることを利用して
    通常のネットワーク断と区別し、専用バナー「解析に時間がかかっています。しばらくしてからマイページで案件をご確認ください
    （案件は作成されている場合があります）」+ フッターを `/mypage` リンクのみに差し替え（再送信不可・戻る/次へも非表示）。
- 変更ファイル:行:
  - `web/src/lib/katadzuke-api.ts:1106-1120`付近（`createCase` に signal 引数追加、docstring 追記）。
  - `web/src/app/create/page.tsx:18`（KdzNetworkError import）、`:118-130`（timedOut/leaveConfirmOpen/allowLeaveRef/guardArmedRef）、
    `:154-204`（beforeunload・popstateガード・cancelLeave/confirmLeave）、`:397-431`（createCase呼び出しにtimeout付与・
    isTimeout分岐）、`:477-491`（error/timedOutバナー）、`:819-826`（送信中ヒントバナー）、`:834-841`（footer timedOut分岐）、
    `:882-905`（離脱確認モーダルJSX）。
  - `web/src/app/create/create.css`（末尾に `.leave-modal-overlay`/`.leave-modal` 追加。既存 `.btn-flow-back`/`.btn-flow-next`
    を流用してブランドと統一）。
- 未対応・理由: 「撮影時に presign アップロードして storage_key を保持する」設計変更（真の永続化・復元）は
  verify-user.md が明記する通り File を sessionStorage に直列化できず、かつ大きな設計変更のため今回のスコープ外
  （最小・安全な beforeunload/バックガードのみ対応）。

## 3. 入札409

- 対応内容: `operator/cases/[id]/page.tsx` の `submitBid` と `operator/page.tsx` の `confirmBid` の catch 節で
  `err instanceof KdzApiError && err.status === 409` の場合に `reload()` を追加実行。
  - `operator/cases/[id]/page.tsx`: reload後 `caseData.status` が更新され、`canBid` が自動的に false になり
    フォームが「この案件は入札を受け付けていません。」に切り替わる（backend `GET /cases/{id}` は operator に
    ステータス制限なしで常に最新状態を返すことを確認済み）。
  - `operator/page.tsx`: reload（`listOpenCases`）は backend 側で `status IN (open,bidding)` のみ返す実装のため、
    409で締め切られた案件は一覧から自然に消え、古い入札フォームが残らないことを確認済み。
  - いずれもエラー文言（backendの日本語detail、例:「この案件は入札を受け付けていません。」）は
    `toDisplayMessage` 経由でそのまま表示。
- 変更ファイル:行:
  - `web/src/app/operator/cases/[id]/page.tsx:24-38`（KdzApiError import）、`:87-111`（submitBid catch に reload 追加）。
  - `web/src/app/operator/page.tsx:35-47`（KdzApiError import）、`:380-403`（confirmBid catch に reload 追加）。

## 4. /contact の配線

- 対応内容: `katadzuke-api.ts` に `submitContactMessage()`（`POST /contact`、token不要、`{name,email,category,message}` →
  `{ok:true}`）を追加。`contact/page.tsx` の `onSubmit` を async 化し、成功時のみ `setSent(true)`。
  422→「入力内容をご確認のうえ、もう一度お試しください。」、429→「送信が集中しています。しばらく時間をおいて
  再度お試しください。」、5xx・その他→`toDisplayMessage` フォールバック「送信できませんでした。しばらくしてから
  もう一度お試しください。」を `.auth-error` バナーで表示（偽の完了表示は出さない）。送信中は `sending` フラグで
  ボタン `disabled` + 「送信中…」表示、関数冒頭 `if (sending) return;` で二重送信防止。完了画面の文言から
  「（デモ）」を削除し「送信を受け付けました。3営業日以内に登録メールアドレスへご連絡します」に統一。
- 変更ファイル:行:
  - `web/src/lib/katadzuke-api.ts:1036-1055`付近（`ContactMessagePayload`/`submitContactMessage`）。
  - `web/src/app/contact/page.tsx:1-90`（import・state・onSubmit の async化とエラー分岐）、
    `:150-172`（エラーバナー追加）、`:270-290`（送信ボタン disabled/文言）、`:320-330`（完了画面文言修正）。
- 未対応・理由: backend `POST /contact` エンドポイント自体の新設は `backend/` 編集除外のため対象外
  （r3-operator.md H1 の指摘どおりバックエンド未実装。並行セッションでの実装を前提にフロントは契約に
  合わせて配線済み。未実装のままなら 404 等の実エラーとして表示され、少なくとも「偽の完了表示」は解消済み）。

## 5. 手数料β注記

- 対応内容: `operator/page.tsx` の入札フォーム内「成約時のみ買取額の8%が手数料」の直後に
  「※サービス開始当初（β期間）は手数料を請求しません。請求開始の際は事前にメールでお知らせします。」を追加（文言担当と同一文）。
- 変更ファイル:行: `web/src/app/operator/page.tsx:254-264`。

---

## tsc・eslint結果

- `npx tsc --noEmit`: エラー0（出力なし）。
- `npx eslint src`: エラー0、警告3（いずれも編集除外ファイル: `notifications/page.tsx`・
  `operator/transactions/[id]/page.tsx`・`signup/page.tsx` の既存警告で本タスクと無関係、未変更）。

## サマリ

✅ 401共通処理・/create保護（beforeunload+ブラウザバック+送信中バナー+180秒タイムアウト）・入札409再取得・
/contact配線（FE側）・手数料β注記のFE実装を完了、tsc/eslintとも0エラー。
⚠️ /contact はbackend `POST /contact` 新設（編集除外）が未完了の間は実際には失敗扱いになる＝偽完了は解消済みだが機能未完成。
⚠️ /create の真の永続化（撮影時アップロード等の設計変更）は今回スコープ外、beforeunload/バックガードのみ。
