# r8 — 異常系・中断系 監査（2026-09-05）

対象コミット: 01c53f8（ローカル）。読み取りのみ。既知・意図的未対応（docs/TODO.md 03、PROJECT_STATE 冒頭）は再指摘していない。
判定基準: リリース阻害になりうる High / Medium のみ。実在確認（該当行の読み取り）済み。

## 台帳

### High

**R8-H1 / High / (6) レート制限・ログイン**
箇所: `web/src/auth.ts:86`（`if (!res.ok) return null;`）、`web/src/app/login/page.tsx:92-94`
事象: `backendLogin` は 403 `account_suspended` だけを個別処理し、それ以外の非 2xx を全部 `null`（＝資格情報エラー）に潰す。backend は 429 で `ログインの試行回数が上限に達しました…`（`backend/app/api/rate_limit_deps.py:199,330`）を返すが、画面には **「メールアドレスまたはパスワードが正しくありません」** が出る。backend 停止中（5xx / 502）も同じ表示。
再現: 同一アカウントでログイン失敗を上限回数（sensitive_account）繰り返す → 以後の正しいパスワードでも同じ「パスワードが違います」。ユーザーは再試行を続け、失敗カウントが積まれて窓が伸び続ける（自己増幅ロックアウト）。`/operator/login` も同じ関数を通るため業者側も同一。
修正案: `backendLogin` で `res.status === 429` と `>= 500` を別クラス（`CredentialsSignin` 継承・`code: "rate_limited"` / `"backend_unavailable"`）に分け、login / operator/login で「試行が集中しています。しばらく時間をおいて…」「ただいま混み合っています」を出す。`Retry-After` ヘッダを読んで残り秒数を添える。

**R8-H2 / High / (1)(2) キャンセル全般・運営の把握手段**
箇所: `backend/app/schemas_katadzuke.py`（`cancel` を含むフィールド 0 件）、`backend/app/api/v1/endpoints/admin.py`（`Cancellation` の参照 0 件）、書き込みは `transactions.py:397-403` と `cases.py:786-793`、`users.py:562-569`
事象: `Cancellation`（`cancelled_by` / `reason`）は3経路で必ず記録されるが、**どの API からも読み出されない**。相手方は「誰が・なぜ」キャンセルしたかを画面でも通知でも知れず（通知本文は `notify.py:309` の「相手方によりキャンセルされました」のみで理由なし）、運営も管理画面から辿れない（`/admin/transactions` は status のみ・`web/src/app/admin/transactions/page.tsx:150`）。業者に理由必須入力（`operator/transactions/[id]/page.tsx:413`）をさせておいて誰にも届かない。
再現: 業者が理由を書いてキャンセル → 依頼者の `/cases/{id}` はバッジ「キャンセル」のみ、運営は DB 直参照以外に理由を知る手段なし。
修正案: `TransactionDetailOut` に `cancelled_by` / `cancel_reason` / `cancelled_at` を追加して当事者双方の画面に出す。`GET /admin/transactions` の行にも同項目を含める（運営がキャンセル常習を検知する唯一の材料）。

**R8-H3 / High / (1)(5) 中断後のチャット・日程**
箇所: `web/src/app/chat/[id]/page.tsx:410-413`（`disabled={… || detail?.status !== "pending"}` / ラベル `"日程確定済み"`）、送信欄 `:452-458`（status 非依存）、backend `transactions.py:500-508`（`create_message` に status ガード無し）・`:582-590`（`propose_schedule` に status ガード無し）
事象: 依頼者の `/chat/{id}` は取引ステータスを一切表示しない。キャンセル済み・完了済みでも送信欄が有効で、backend も受け付ける。さらに候補日カードの確定ボタンが `status !== "pending"` で一律 **「日程確定済み」** になるため、**キャンセル済み取引で「日程確定済み」と事実に反する表示**が出る。キャンセル通知メールのリンク先が `/chat/{transaction_id}`（`notify.py:300`）なので、通知を踏んだ依頼者はまさにこの画面に着地する。業者側も `/operator/chat/{id}` から候補日提案が送れ（`operator/chat/[id]/page.tsx:533`）、backend が 201 を返す。
再現: 業者がキャンセル → 依頼者が通知メールのリンクを開く → 平常のチャット画面。メッセージを送っても相手には「キャンセル済み案件への発言」として届き続ける。
修正案: backend の `create_message` / `propose_schedule` / `mark_messages_read` に `txn.status in ("pending","visiting")` ガード（409）。web は両チャットに status バナー（キャンセル済み／完了済み）を出し、送信欄と候補日カードを無効化。ボタン文言を `cancelled` → 「キャンセル済み」、`completed` → 「取引完了」に分岐。

**R8-H4 / High / (9) 写真アップロード失敗**
箇所: `web/src/lib/katadzuke-api.ts:1426-1427`
事象: `uploadCasePhoto` は 401 以外の全 HTTP エラーを `"写真のアップロードに失敗しました"` に置き換える。backend は 413 `ファイルサイズが上限（10MB）を超えています。`、415 `画像ファイルのみアップロードできます。`、422 `ファイルが空です。` を返している（`case_photos.py:30,91,98`）のに、原因が一切表示されない。
再現: HEIC を「すべてのファイル」で選択（`accept` は回避可能）→ `create/page.tsx:57-78` の縮小はデコード失敗で catch し原本を送る → マジックバイト判定（`storage.py:153-163` は jpeg/png/webp のみ）で 415 → 画面は汎用文言。ユーザーは何度も同じファイルで再試行する。10MB 超も同様。
修正案: `if (!res.ok) await throwHttpError(res);` に統一し detail を通す。加えて選択時に `file.type` と `file.size` を事前検証して「HEIC は対応していません」「10MB を超えています」を即時表示する。

### Medium

**R8-M1 / Medium / (1) 業者キャンセルの評価影響**
箇所: `web/src/app/operator/transactions/[id]/page.tsx:304` と `:411`（「業者都合のキャンセルは記録され、アカウント評価に影響します」）／`backend/app/api/v1/endpoints/transactions.py:411-414`（加算）
事象: `Operator.cancel_count` は加算されるだけで、**読み出しが全コードベースで 0 件**（models 定義と加算箇所以外に出現しない）。`rating` は reviews のみから再計算（`services/review_stats.py`）、業者一覧・公開プロフィール・管理画面のいずれにも出ない。UI の断言が実装と食い違う。
再現: 業者が10回キャンセル → `cancel_count=10` だが `/vendors/{id}`・`/admin/users`・入札一覧のどこにも影響なし。
修正案: 文言を実装に合わせる（「キャンセルは記録されます」）か、`cancel_count` を管理画面の業者行と `OperatorPublicOut` に出して実際に効かせる。運営がキャンセル常習業者を止められる材料が現状ゼロ。

**R8-M2 / Medium / (1) キャンセル後の再出品**
箇所: `backend/app/api/v1/endpoints/transactions.py:396`（`txn.case.status = "cancelled"`）、`web/src/app/cases/[id]/page.tsx:625`（`!txn && caseData.status !== "cancelled"` で入札一覧ごと非表示）
事象: 成約キャンセルで案件も `cancelled` に落ち、同じ案件を再募集する手段が無い（backend に復活 API 無し）。にもかかわらず画面には「新しく出品し直してください」の案内が一切なく、依頼者は写真・商品情報を最初から入れ直す必要があることに気づけない。取り下げ側（`:686-698`）には「元に戻せません」の警告があるのに、成約キャンセル側（`:872-885`）の確認は「本当にキャンセルしますか？」のみ。
再現: 訪問前日に業者がキャンセル → 依頼者の案件詳細はキャンセルバッジのみ。次の行動が示されない。
修正案: キャンセル済み成約パネルに「この案件は終了しました。同じ内容で募集し直すには新しく出品してください」＋`/create` 導線。確認文言にも「案件ごと終了し、入札は戻せません」を明記。

**R8-M3 / Medium / (7) 減額の却下後**
箇所: `backend/app/api/v1/endpoints/reductions.py:76-80`（pending 1件のみを禁止）、`web/src/app/operator/transactions/[id]/page.tsx:252`（`active && !pendingReduction` でフォーム再表示）、`web/src/app/cases/[id]/page.tsx:860`（`disabled={busy || Boolean(pendingReduction)}`）
事象: 却下後の再申請に回数制限も間隔制限も無い。一方で依頼者の「作業完了を確定する」は pending 減額があると無効（backend も 409・`transactions.py:357-361`）。業者が却下されるたびに再申請すれば、依頼者は完了確定に到達できない。
再現: 依頼者が却下 → 業者が即再申請（同一秒でも可）→ 依頼者の完了ボタンが再び無効。ループ可能。
修正案: 同一取引の減額申請を N 回（例: 2回）または「却下から24時間」で制限し、超過は 409。UI に「残り申請回数」を表示。

**R8-M4 / Medium / (4) 依頼者停止時の業者側画面**
箇所: `backend/app/schemas_katadzuke.py:687,729`（`operator_suspended` のみ・`user_suspended` 相当なし）、`transactions.py:309`
事象: 業者停止は依頼者側に赤バナーで出る（`cases/[id]/page.tsx` 成約パネル）が、逆方向が無い。運営が依頼者を停止すると当人はログインできず（403 `account_suspended`）、完了確定・日程確定はユーザー専用操作（`transactions.py:346-350`・`:629-633`）なので取引は `pending` のまま固定される。業者には理由が一切表示されず、返信の来ないチャットを待ち続ける。
※ TODO 03 の「停止した依頼者の進行中案件は open のまま業者に見える」は募集中案件の話で、成約後の取引はこれに含まれない。
再現: 成約後に `/admin/users/{id}/suspend` → 業者の取引詳細は通常表示のまま、日程確定も完了も永久に来ない。
修正案: `TransactionDetailOut` に `user_suspended` を追加し、業者画面に「お客様が現在ご利用いただけない状態です。運営にお問い合わせください」を出す。

**R8-M5 / Medium / (1)(4) 運営の介入手段**
箇所: `backend/app/api/v1/endpoints/admin.py`（transaction を更新する endpoint 0 件。存在するのは invites / operators verify・suspend / reviews hide / users suspend・promote・demote / operator-applications / identity-documents のみ）
事象: 固まった取引を運営が終わらせる手段が無い。R8-M4 の停止・退会不可（進行中取引ありは 409）・当事者失踪のいずれでも、運営は状態を動かせず、業者にキャンセル（＝R8-M1 の「評価に影響」表示付き）を依頼するしかない。
再現: 依頼者を停止 → 取引は pending で固定。運営は `/admin/transactions` から status を見るだけ。
修正案: `POST /admin/transactions/{id}/cancel`（理由必須・`cancelled_by="admin"` で Cancellation 記録・cancel_count は加算しない）を追加し、管理画面にボタンを置く。

**R8-M6 / Medium / (3) 業者の退会手段**
箇所: backend に `DELETE /operators/me` 相当が無い（`operator_profile.py` の DELETE は `:329` の LINE 連携解除のみ）。web にも業者向け退会導線が無い（`grep 退会 web/src` は依頼者向けのみ）。
事象: 業者は自分でアカウントを閉じられない。`web/src/app/privacy/page.tsx:113` は「ご本人からの削除のお申し出があった場合、または退会された場合…遅滞なく削除します」と書いており、業者にはその「退会」が存在しない。運営側にも業者削除 API は無く、`suspend` で止めるのみ（`admin.py:382`）。
修正案: 最低限、業者プロフィール画面に「退会をご希望の場合は /contact からご連絡ください」を明記する（実装コスト小）。恒久対応は依頼者と同型の匿名化退会（進行中取引ありは 409）。

**R8-M7 / Medium / (6) `/contact` 503 と Retry-After**
箇所: `web/src/lib/katadzuke-api.ts:2013`（`err.status >= 500` は detail を捨てて fallback）、`web/src/app/contact/page.tsx:79-84`（429 のみ個別分岐）、backend `contact.py:79-86`（503 + `Retry-After`）
事象: `/contact` のプロセス内キャップ枯渇時、backend は 503 に `Retry-After` を付けて「時間をおいて」の意図を返すが、画面は 5xx 一括の汎用文言になる。`Retry-After` ヘッダはコードベース全体で一度も読まれていない（429 も含む）。「今は混んでいる（後で通る）」と「壊れている」がユーザーに区別できない。
修正案: contact ページに 503 分岐を足し「ただいま混み合っています。数分後に再度お送りください」を出す。`KdzApiError` に `retryAfter?: number` を持たせ、429/503 で秒数を文言に反映する。

## シナリオ別 一覧

| # | シナリオ | 判定 | 根拠 |
|---|---|---|---|
| 1a | 依頼者の取引キャンセル（成約後/日程確定後/当日） | ⚠️ 通るが詰まる | 遷移・行ロック・通知は正常（`transactions.py:376-461`）。理由が相手に出ない（H2）、再出品不可の案内なし（M2） |
| 1b | 業者のキャンセル（cancel_count・評価影響） | ⚠️ 文言と実装が不一致 | 加算のみで読み出し 0 件（M1） |
| 2 | 出品の取り下げ（入札あり／成約後は不可） | ✅ 通る | `cases.py:722-741` で draft/closed/cancelled を個別文言で 409。pending 入札の一括却下と落選通知あり（`:757-777`） |
| 3a | 依頼者の退会（進行中取引 409／暗黙キャンセル） | ✅ 通る | `users.py:606-612` で 409、`_cancel_open_case_on_withdrawal` が入札却下・監査・通知まで実施 |
| 3b | 業者の退会 | ❌ 未実装 | API・UI とも無し（M6） |
| 4a | 取引中の業者停止（相手側画面・解除後復帰） | ✅ 通る | `operator_suspended` を成約パネル・入札一覧に表示。停止業者の入札は選定不可 |
| 4b | 取引中の依頼者停止 | ❌ 業者側は無表示で固定 | `user_suspended` 相当なし（M4）＋運営の介入 API なし（M5） |
| 5 | セッション失効（保護ルート／チャット送信中／写真アップロード中） | ✅ 通る | `katadzuke-api.ts:672-676` で日本語文言＋signOut＋ループ検知、`/chat` `/create` は保護ルート（`protected-routes.ts:21-31`）。下書きは失われる（軽微） |
| 6 | 429（出品・contact）／`/contact` 503 | ⚠️ 部分的 | 出品・取り下げ・contact は日本語 detail が出る。ログインは誤表示（H1）、503 は汎用文言（M7）、`Retry-After` は全経路未使用 |
| 7 | 減額の却下後／承認後のキャンセル | ⚠️ 却下後が無制限 | 承認後キャンセル・完了時の pending ガードは正常（`transactions.py:355-361`, `reductions.py:156-160`）。再申請の回数制限なし（M3） |
| 8 | 評価の重複投稿・完了前の評価・業者側の表示 | ✅ 通る | `reviews.py:65-73` + `uq_reviews_transaction_reviewer` の二重防御。`/review` も completed のみフォーム活性（`review/page.tsx:162-165`）。`myReview` は双方 reviewer_type 一致で正しい |
| 9 | 写真アップロード失敗・サイズ超過・非対応形式 | ❌ 原因が出ない | detail を捨てて汎用文言（H4） |
| 10 | 二重送信（入札・選定・完了） | ✅ 通る | UI は `busy` ガード（`operator/cases/[id]:290`, `cases/[id]:311-313`）、backend は Case 行ロック＋条件付き UPDATE＋一意制約（0028/0029） |
| 追加 | キャンセル済み取引でのチャット・日程 | ❌ ガードなし・虚偽表示 | H3 |
