# r4 敵対的検証（運営・業者視点）— 独立品質保証

検証日: 2026-09-04 / 方式: 静的読解のみ（Read/Grep/Bash 読み取り専用）/ 対象台帳: `.agent-state/audit/r4-operator.md`・`.agent-state/audit/r4-vendor.md`
方針: 立案者の主張を額面で受けず、file:line で再確認。`backend/app/config.py`・`main.py`・`services/alerts.py` への修正提案は対象外。

判定集計: CONFIRMED 3 / PARTIAL 1 / REJECTED 0 / 追加High 2

---

## 1. r4-operator H1 — 業者事前申込の審査UI・APIクライアント欠落

**判定: PARTIAL（欠落の事実は CONFIRMED、「運営が気づく手段が無い」の断定は不正確）／重大度 High は妥当**

- 欠落は実コードで確認。`web/src/lib/katadzuke-api.ts` の operator-applications 関連は `submitOperatorApplication`（`:1185-1201`、公開POST `/operator-applications`）の 1 件のみで、admin 側 4 関数（list/get/approve/reject/reveal-bank-account）は 1 つも存在しない（grep ヒット 2 行のみ）。
- 画面も無い。`web/src/app/admin/` 配下は `_components / cases / identity-documents / layout.tsx / page.tsx / transactions / users` の 7 エントリのみ（`ls -R` 実測）。`web/src/app/admin/page.tsx:299-315` のトップナビも 4 リンク（案件／取引／依頼者／本人確認書類）で申込審査への導線なし。
- バックエンドは健全。`backend/app/api/v1/endpoints/admin.py:825`（一覧・limit/offset 対応）・`:844`（詳細）・`:856`（口座復号＋監査ログ `:882-887`）・`:900`（承認＝招待コード発行、`status != "received"` で 409 `:908-912`）・`:947`（却下、同じく 409 ガード）の 5 本が `Depends(get_current_admin)` 付きで実装済み。二重承認による招待コード重複発行も 409 で塞がれている。
- **台帳の誤り**: 「運営が気づく手段が画面上に無い」は正しいが、通知経路自体は存在する。`backend/app/api/v1/endpoints/operator_applications.py:161-165` が `get_settings().admin_emails` 全宛先へ `notify.send_operator_application_admin_alert` を background 送信し、本文は「管理画面から確認してください」（`backend/app/services/notify.py:191-200`）。`ADMIN_EMAILS` は `render.yaml:57-58` に実値が入っている。
- 重大度: それでも High は妥当。メールは「届いたこと」しか伝えず、承認・却下・口座開示は curl/Postman でしか実行できない（画面上のアクション経路がゼロ）。加えて本文が案内する「管理画面」が実在しないため、通知が誤誘導になっている。
- 最小修正: `katadzuke-api.ts` に 4 関数を追加 → `web/src/app/admin/operator-applications/page.tsx` を新設（`AdminPagination`／`ConfirmModal`／`CopyableId` を流用）→ `admin/page.tsx:299-315` に 5 本目の Link を追加。合わせて通知本文（`notify.py:196-198`）に該当 URL を入れる。

## 2. r4-operator M1 — ID検索プレースホルダ「前方一致」と実装（UUID完全一致）の不一致

**判定: CONFIRMED／重大度 Medium は妥当（Low 寄り）**

- 文言: `web/src/app/admin/cases/page.tsx:120`「案件ID（前方一致）…」、`web/src/app/admin/transactions/page.tsx:120`「取引ID・案件ID（前方一致）…」。`grep -rn 前方一致 web/src/app` のヒットはこの 2 行のみで、`users/page.tsx` は既に語を落としている。
- 実装: `backend/app/api/v1/endpoints/admin.py:88-98` `_try_parse_uuid` は `uuid.UUID(value)` の成否のみ。`admin_list_cases`（`:396-398`）は `Case.id == parsed_case_id`、`admin_list_transactions`（`:497-500`）は `Transaction.id == parsed_id` / `Transaction.case_id == parsed_id` の等価比較のみで、ilike 前方一致は存在しない。`_escape_ilike_value`（`:78-85`）はメール・会社名側だけに適用。
- なお `admin.py:497-499` のコメントは自ら「前方一致だった従来動作の意味的等価物」と述べており、バックエンド側は意図的な仕様変更。**直すべきはフロント文言のみ**という台帳の修正案は正しい。
- 最小修正: 2 行の placeholder から「前方一致」を削り「案件ID（完全一致）」等に統一。バックエンド変更不要。

## 3. r4-operator M2 — 確認ダイアログが依頼者一覧のみ ConfirmModal

**判定: CONFIRMED／重大度 Medium は過大（Low 相当）**

- `web/src/app/admin/page.tsx:216-221`（業者停止／解除）・`:237`（業者承認）、`web/src/app/admin/identity-documents/page.tsx:127`（本人確認承認）が `window.confirm`。`web/src/app/admin/users/page.tsx:271,293` のみ `ConfirmModal`。設計意図のコメントは `web/src/app/admin/_components/ConfirmModal.tsx:5` に明記。
- ただし機能欠損はなく、誤操作防止という本質（確認を挟む）は全経路で成立している。承認取消（`vendor_status === "active"` 側）だけ確認なしで即時実行される点（`admin/page.tsx:234-241`）の方が実害としては上だが、これも復帰可能操作。リリース阻害性は無く Low が妥当。
- 最小修正: `admin/page.tsx` の 2 箇所と `identity-documents/page.tsx:127` を `ConfirmModal` に置換（部品は既存）。

## 4. r4-vendor R4-M1 — `/operator/login` に業者ログイン済み時の自動遷移が無い

**判定: CONFIRMED／重大度 Medium は妥当（Low 寄り）**

- `web/src/app/operator/login/page.tsx:33` は `otherAccountSignedIn = status === "authenticated" && session?.accountType !== "operator"` の 1 分岐のみ。同ファイルに `useEffect` は存在せず（`:14` の import も `Suspense, useState` のみ、`router` の用途は `:65` の成功後 push だけ）、`accountType === "operator"` の一致ケースは何も起きない。
- 対比は台帳どおり成立。`web/src/app/login/page.tsx:37-48` に `status/accountType==="user"` を条件とした `router.replace` の useEffect が存在し、`:52` にバナー分岐が併存している。
- ミドルウェア救済も無い。`web/src/middleware.ts:31` の `OPERATOR_PUBLIC` に `/operator/login` が含まれ、`:50-55` で `needsOperator=false` → 即 `NextResponse.next()`。セッション種別を一切見ない。
- 重大度: 空フォームが出るだけで再ログインすれば通るため「行き止まり」は言い過ぎ。ただし `/login` と対称であるべき箇所の片肺実装であり、Medium 上限として許容。
- 最小修正: `login/page.tsx:37-48` と同型の useEffect を追加（`session?.accountType === "operator"` のときのみ `clearRedirectLoopStorage()` → `router.replace(callbackUrl)`。`callbackUrl` は `:27` で `safeInternalPath` 済み）。

---

## 追加発見（同一観点で見落とされた High）

### ADD-H1. `/admin` トップと `/admin/identity-documents` が server 側 limit=100 の無言 truncate を受け、ページングも limit 指定も無い

- バックエンドは全て `limit: int = Query(default=_DEFAULT_LIST_LIMIT ...)`＝**100**（`backend/app/api/v1/endpoints/admin.py:70`）。該当: `/admin/operators`（`:214-226`）・`/admin/invites`（`:199-204`）・`/admin/identity-documents`（`:1009-1022`）。
- フロントは limit/offset を一切送らない: `web/src/lib/katadzuke-api.ts:1478-1479` `adminListOperators(token)` はクエリなし、`:1066` `listIdentityDocumentsAdmin` は `status` のみ。`web/src/app/admin/page.tsx:116-117` はこの 2 本を素で呼び、同ファイルに `AdminPagination` の import も offset 状態も存在しない（grep ヒット 0）。`identity-documents/page.tsx` も同様（`AdminPagination|offset|limit` grep ヒット 0）。
- 実害: 101 件目以降の業者・招待コード・未審査書類が管理画面から**恒久的に不可視**。`admin/page.tsx:250-257` の「承認待ち（pending）が埋もれないよう pending→limited→active に並べる」配慮は先頭 100 件内でしか働かず、`:444-458` のステータス別バッジ件数も truncate 後の母数で表示されるため運営に誤った「pending 0 件」を示す。件数超過の警告表示も無い（fail-silent）。招待コードはバルク発行機能があるため 100 到達が最も早い。
- 重大度 High（新規業者の承認漏れ＝H1 と同じ「業者が稼働開始できない」帰結を、より静かに引き起こす）。
- 最小修正: `adminListOperators`／`adminListInvites`／`listIdentityDocumentsAdmin` に `limit`/`offset` 引数を追加し、cases/transactions/users と同じ `AdminPagination` を 2 画面へ適用する（バックエンドは既に offset 対応済みで変更不要）。

### ADD-H2. H1 の唯一の代替検知経路である admin アラートメールが、鍵未設定時に無言スキップされる

- `backend/app/services/notify.py:51-55` — `if not settings.brevo_api_key:` で `logger.info` を出して `return False`。呼び出し側 `operator_applications.py:161-165` は `background.add_task` で戻り値を捨てるため、送信されなくても API は 201 を返し、運営側にも申込者側にも痕跡が残らない。
- `BREVO_API_KEY` は `render.yaml:62` で `sync: false`（dashboard 手動入力）であり、既存サービスへ自動反映されないことは既知（`render-envvars-not-synced.md`）。**未設定なら「画面なし（H1）＋通知なし（本項）」で `/business` からの申込は完全に不可視**になる。
- 重大度 High（H1 の実害上限を決める要因。H1 の修正案に「メールが届いている前提」を置いてはいけない）。
- 最小構成: 本番 Render dashboard で `BREVO_API_KEY` の設定有無をログ（`notify: BREVO_API_KEY 未設定のため送信スキップ`）で実証確認する。恒久策は ADD-H1／H1 の画面実装（画面があれば鍵に依存せず申込を発見できる）。`config.py`/`alerts.py` への変更は本タスクの禁止事項につき提案しない。

---

## サマリ

✅ 台帳 4 件はいずれも実コードで再現条件まで確認でき、捏造・誤読による起票は 0 件。バックエンド側（5 エンドポイントの認可・409 二重審査ガード・口座復号の監査ログ・UUID 等価検索）は健全。
⚠️ H1 は「通知経路が皆無」という前提が不正確（admin アラートメールは実装済み）。M2 の Medium は過大で Low 相当。運営導線の最大の穴は H1 単独ではなく、H1＋ADD-H1（100 件無言 truncate）＋ADD-H2（鍵未設定で通知消失）の重畳。
❌ ブロッカーなし。ただし ADD-H1 は既存機能の静かな機能不全であり、H1 と同一バッチでの修正を推奨。

保存パス: `C:\Users\ko13h\Claude\Projects\ソクウリ\.agent-state\audit\r4-verify-ops.md`
