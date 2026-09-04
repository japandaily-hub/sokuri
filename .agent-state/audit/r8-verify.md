# r8-verify — 独立検証（2026-09-05）

対象: `.agent-state/audit/r8-abnormal.md`（High 4 / Medium 7）。立案者と無関係に該当行を再読して判定。読み取りのみ。

判定集計: CONFIRMED 8 / PARTIAL 3 / REJECTED 0（ただし H1・M2 は重大度を下方修正、H4 は根拠の誤記あり）

---

## High

### R8-H1 — PARTIAL（事実は成立・重大度 High → **Medium**）
**事実（成立）**: `web/src/auth.ts:86` は `if (!res.ok) return null;`。403 の `account_suspended` のみ `AccountSuspendedError`（`:55-57,83`）へ分岐し、429・5xx は一律 `null`。`authorize` は `null` を返すと NextAuth 既定の `CredentialsSignin` になり、`web/src/app/login/page.tsx:92-94` は `res?.error` を無条件に「メールアドレスまたはパスワードが正しくありません」へ写像する。`/operator/login` も同型（`web/src/app/operator/login/page.tsx:72,76`）。backend の 429 detail は `backend/app/api/rate_limit_deps.py:199`、送出は `:330-334`。**→ 429 でもバックエンド全断（502/5xx）でも「パスワードが違います」と出るのは事実。**

**却下する部分（再現手順の因果が誤り）**: 台帳の「失敗カウントが積まれて窓が伸び続ける（自己増幅ロックアウト）」は成立しない。login スコープは account 軸の事前判定に `limiter.check()`＝peek を使い（`rate_limit_deps.py:479`、`check` は `backend/app/core/rate_limit.py:347-352` で非カウント）、`count_all=False`（`rate_limit_deps.py:373`）のためカウントは失敗時の `record()`（`:526`）のみ。429 で弾かれたリクエストは加算されず、窓は延びない。成功時は `reset()`（`:510`）。したがって症状は「窓が切れるまで誤メッセージ」で自己回復する。

**重大度**: 自己増幅が無く状態も自己回復するため High → **Medium**。ただし修正は数行で、5xx（全断）時に「パスワードが違う」と誤診させる害は残るので着手は優先。

**最小修正**: `backendLogin` を `Promise<BackendAuthResponse | null>` から捨てずに、`res.status === 429` → `class RateLimitedError extends CredentialsSignin { code = "rate_limited" }`、`res.status >= 500` → `code = "backend_unavailable"` を throw。login / operator/login の `res?.code` 分岐に2件追加。副作用: NextAuth は `code` をクエリ経由で返すだけで、既存の `account_suspended` 経路と同一機構のため回帰リスクは実質なし。`Retry-After` の秒数表示は任意（別件・M7 と同時に）。

### R8-H2 — CONFIRMED（High 妥当）
`Cancellation.cancelled_by`（`backend/app/db/models/transaction.py:174`）への書き込みは 3 経路（`transactions.py:402`, `cases.py:789`, `users.py:565`）のみで、**リポジトリ全体で読み出し 0 件**（`grep -rn "cancelled_by\|cancel_reason\|cancelled_at" backend/app web/src` が上記書き込みと model 定義しかヒットしない）。`admin.py` に `Cancellation` の参照なし（router 一覧 `admin.py:196-1401` に該当なし）。業者側は理由必須入力を課されるのに、依頼者にも運営にも届かない。
**最小修正**: `TransactionDetailOut`（`schemas_katadzuke.py` 687 近傍）に `cancelled_by` / `cancel_reason` / `cancelled_at` を追加し、`transactions.py:309` の `operator_suspended` 代入と同じ場所で埋める（`Transaction.cancellation` の relationship 追加が前提）。`AdminTransactionListItem`（`admin.py:672`）にも同項目。副作用: 一覧側は N+1 回避のため `selectinload` 追加が必須（`admin.py:646-647` に併記）。

### R8-H3 — CONFIRMED（High 妥当。今回の最重要）
backend に status ガードが無いことを確認: `create_message`（`transactions.py:500-518`、`_assert_party` のみ）、`propose_schedule`（`:582-604`、party 判定のみ）、`mark_messages_read`（`:555-568`）。対照的に `complete`（`:351`）・`cancel`（`:389`）・`confirm_schedule`（`:634`）・`create_reduction`（`reductions.py:71`）には全て status ガードがある＝**チャット系だけ抜けている**。
UI 側も確認: `web/src/app/chat/[id]/page.tsx` は `detail?.status` の参照が 410・412 の 2 箇所のみで、ステータス表示なし・送信欄は `disabled={sending}` のみ（`:452-458`）。候補日ボタンは `status !== "pending"` で一律「日程確定済み」（`:410-413`）＝**キャンセル済み取引で「日程確定済み」と虚偽表示**が出るのは事実。業者側 `operator/chat/[id]/page.tsx:527` にはステータス表示があるが、提案ボタン（`:533`）は無条件。
**最小修正**: 3 エンドポイント冒頭に `if txn.status not in ("pending", "visiting"): raise HTTPException(409, "この取引は終了しているため操作できません。")`。ただし `mark_messages_read` を 409 にするとチャット画面を「読むだけ」で赤エラーが出るので、既読更新は 409 にせず no-op で 200 を返すのが安全（副作用の回避）。web は両チャットに status バナー＋送信欄 disable、ボタン文言を `cancelled`→「キャンセル済み」/`completed`→「取引完了」へ分岐。

### R8-H4 — CONFIRMED（High 妥当。ただし根拠に誤記 1 件）
`web/src/lib/katadzuke-api.ts:1425-1428` は 401 のみ `throwHttpError`、それ以外は `new KdzApiError(res.status, "写真のアップロードに失敗しました")` で detail を破棄。事実。
**誤記**: 台帳の「413 ファイルサイズが上限（10MB）を超えています。」は誤り。実際は **422**（`backend/app/api/v1/endpoints/case_photos.py:28-31` の `_TOO_LARGE`、送出は `:76,85`）。415（`:99-103`）・422 空ファイル（`:91-93`）は記載どおり。
**再現の増幅要因（台帳未記載）**: 同ファイル `:1397-1401` が jpeg/png/webp 以外の `file.type` を無条件に `"image/jpeg"` と申告して PUT するため、HEIC は必ずマジックバイト判定（`backend/app/services/storage.py:152-164`）で 415 に落ちる。
**最小修正**: `if (!res.ok) await throwHttpError(res);` に一本化（1 行）。副作用: 5xx の detail は `toDisplayMessage`（`:2013`）が既に握り潰すため、サーバ内部文字列の露出リスクは増えない。事前検証（`file.type` / `file.size`）の追加は任意だが効果大。

---

## Medium

### R8-M1 — CONFIRMED（Medium 妥当）
`Operator.cancel_count` は定義（`backend/app/db/models/operator.py:26`）と加算（`transactions.py:410-414`）のみで読み出し 0 件。`operator/transactions/[id]/page.tsx` の「アカウント評価に影響します」は実装と不一致。**最小修正は文言側**（「キャンセルは記録されます」）。`cancel_count` の露出は運営に有用だが、公開プロフィールへ出すと業者評判に直結するため管理画面限定にとどめるのが安全。

### R8-M2 — PARTIAL（Medium → **Low**。台帳の中心的主張が事実誤認）
**却下**: 「案内が一切ない」は誤り。`web/src/app/cases/[id]/page.tsx:435-439` に `caseData.status === "cancelled"` のバナーがあり、本文に「再度依頼する場合は『出品する』から新しく出品してください」が含まれる。成約キャンセルでも `txn.case.status = "cancelled"`（`transactions.py:397`）なので**このバナーは表示される**。
**成立**: (a) 文言が「この出品は**取り下げ済み**です。届いていた入札はすべて自動でお断りになりました。」で、業者都合の成約キャンセルには事実に反する（取り下げていないし、入札は落札済みだった）。(b) 確認ダイアログ（`:934-935`）は「本当にキャンセルしますか？」のみで案件終了の警告なし（取り下げ側 `:750` には「元に戻せません」がある）。
**最小修正**: バナーを `txn` の有無で分岐して成約キャンセル用の文言を出す＋`:935` の message に「案件ごと終了し、入札は戻せません。」を追記。

### R8-M3 — CONFIRMED（Medium 妥当）
`reductions.py:76-80` の制約は「pending 1 件のみ」で、却下後の再申請に回数・間隔制限なし（`create_reduction` 全体 `:59-111` に該当ロジック無し）。一方 `complete_transaction` は pending 減額があると 409（`transactions.py:358-362`）。依頼者側の完了ボタンも `disabled={busy || Boolean(pendingReduction)}`（`cases/[id]/page.tsx:912`）。**業者が却下のたびに再申請すれば依頼者は完了確定に到達できない**は成立。
**最小修正**: `create_reduction` に `rejected` 件数のカウントを追加し `>= 2` で 409。時間制限（24h）より回数制限のほうが実装・説明ともに単純で副作用が小さい。

### R8-M4 — CONFIRMED（Medium 妥当）
`operator_suspended` は `schemas_katadzuke.py:687,729` と `transactions.py:309`・`bids.py:70` に存在するが、`user_suspended` 相当は**リポジトリ全体で 0 件**。停止された依頼者は 403 でログイン不可、完了確定（`transactions.py:346-350`）・日程確定（`:629-633`）はユーザー専用のため取引は `pending` で固定。業者側に表示なし。
**最小修正**: `TransactionDetailOut` に `user_suspended` を追加し、`transactions.py:309` の隣で `txn.case.user.is_suspended` を代入（`case.user` の eager load 追加が必要＝`_TXN_LOAD` の変更が副作用点）。業者画面に注意バナー。

### R8-M5 — CONFIRMED（Medium 妥当）
`admin.py` の router 定義を全列挙して確認: invites / operators(verify,suspend) / reviews hide / cell-density / cases(GET) / **transactions(GET のみ `:594-687`)** / users(GET,suspend,promote,demote) / operator-applications / identity-documents。**取引を更新する endpoint は 0 件**。M4 と合わせて「固まった取引を運営が動かせない」は成立。
**最小修正**: `POST /admin/transactions/{id}/cancel`。`cancel_transaction` のロック・`Cancellation` 記録手順を再利用し、`cancelled_by="admin"` かつ `cancel_count` 非加算。副作用点は `uq_cancellations_transaction_id`（0028）との整合と、両当事者への通知（`notify_dispatch` の宛先決定が現状 party ベースなので admin 経路は双方送信に分岐が要る）。

### R8-M6 — CONFIRMED（Medium 妥当）
`operator_profile.py` の変更系は PUT `:123` / POST `:289` / DELETE `:329`（LINE 連携解除）のみで、退会相当なし。web の `grep 退会` は全て依頼者向け（`mypage/withdraw/*`, `unsubscribe`）＋管理画面の説明文のみ。`privacy/page.tsx:113` は「退会された場合…遅滞なく削除します」と主体を限定せず記載しており、業者にはその手段が存在しない＝記載と実装の不整合は成立。
**最小修正**: 業者プロフィール画面に `/contact` 経由の退会案内を明記（実装コスト最小・表記の整合が回復する）。恒久対応（匿名化退会 API）は別スコープ。

### R8-M7 — PARTIAL（Medium → **Low**）
事実は成立: `toDisplayMessage` は `err.status >= 500` で detail を破棄（`katadzuke-api.ts:2013`）、`contact/page.tsx:78-84` は 422/429 のみ分岐、backend は 503 に `Retry-After` を付与（`contact.py:82-87`）。`Retry-After` は backend の 2 箇所（`rate_limit_deps.py:332`, `contact.py:86`）で付与されるのみで、**web 側の読み取りは 0 件**。
**重大度**: 発火条件がプロセス内キャップ（1 時間 30 件超）の枯渇時に限られ、汎用文言でも再送は促される。リリース阻害ではないため Low。
**最小修正**: contact ページに `err.status === 503` 分岐を 1 つ追加。`KdzApiError.retryAfter` の導入は 429/503 全経路に波及するため後回し可。

---

## 追加発見（同観点で台帳が拾えていないもの）

**新規 High は無い。** 30 回のツール上限内で `transactions.py` / `reductions.py` / `cases.py` / `admin.py` / `case_photos.py` の全遷移エンドポイントの status ガードを確認した結果、抜けは H3 の 3 本のみで、`confirm_schedule`（`transactions.py:634-638`）・`complete`（`:351`）・`cancel`（`:389`）・`create_reduction`（`reductions.py:71`）は全て正しくガードされている。以下は Medium 相当の追加 2 件。

- **ADD-1 / Medium**: `web/src/app/cases/[id]/page.tsx:435-439` のキャンセル済みバナーが、業者都合の成約キャンセルに対しても「この出品は**取り下げ済み**です。届いていた入札はすべて自動でお断りになりました。」と表示する。依頼者は自分が取り下げたと誤解し、かつ「入札を断られた」という誤った経緯を読む。H2（理由が届かない）と同じ画面で複合するため、H2 の修正と同時に文言分岐すべき。
- **ADD-2 / Low**: `web/src/lib/katadzuke-api.ts:1397-1401` が非対応 MIME を無条件に `"image/jpeg"` と申告して PUT する。backend のマジックバイト判定で必ず弾かれるため実害は「原因不明の 415」に限られるが、Content-Type を偽って送る設計自体が H4 の再現条件を作っている。H4 の修正時に、対応外形式は送信前に弾く形へ直すのが自然。

---

## 着手すべき順

**H3（backend 3 本の status ガード＋チャット2画面のバナー・送信欄無効化）→ H4（`throwHttpError` 一本化の 1 行）→ H1（`backendLogin` の 429/5xx エラークラス分離）→ H2＋ADD-1（`cancelled_by`/`reason` を両当事者と `/admin/transactions` に出し、キャンセル済みバナーを取り下げ／成約キャンセルで文言分岐）→ M4 → M1（文言修正）→ M3 → M6（案内文）→ M5 → M2 → M7。**
