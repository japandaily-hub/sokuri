# r5 運営・管理画面 最終回帰監査（2026-09-04 / 対象コミット 3da71de）

検証実績: `pytest -q` → **748 passed, 0 failed**（208s）。`npx tsc --noEmit` → **エラー0**。
対象外ファイル（config.py / main.py / core/alert_middleware.py / services/alerts.py）は読み取りのみ・無編集。

総合判定: **条件付き合格（Critical 0 / High 1 / Medium 5）**。r4 の High 2 は実コードで塞がった。
残る穴は「事前申込一覧だけを直し、同じ欠陥が残る業者一覧に波及させていない」点に集中している。

---

## 1. r4-review.md の前回指摘 判定

| ID | 判定 | 根拠 |
|----|------|------|
| H1 アラート配送テスト | **塞がった** | `backend/tests/test_notify.py:75` で `alerts.httpx.AsyncClient` をスタブ化し、`:94-97` で LINE Push API への実POST（to / messages 本文の "BREVO_API_KEY"）まで検証。send_alert 自体のモックは廃止済み。 |
| H2 認可負テスト30件 | **塞がった** | `backend/tests/test_admin_authz_negative.py:157/169/183/195` が GET /{id}・reveal-bank-account・approve・reject の4ルート×`principal=["user","operator","none"]`＝12件。残18件は cases/transactions/users GET 9 + suspend/promote/demote 9。合計30件が748 passed に含まれる。 |
| M1 allSettled | **塞がった** | `web/src/app/admin/page.tsx:139-177` で4本を `Promise.allSettled`、区画別 error state（inviteError / operatorListError / cellDensityError / pendingApplicationsError）に分離。 |
| M2 モーダル失敗表示・却下理由必須 | **一部** | 却下理由必須は有効（`ConfirmModal.tsx:105,153` reasonMissing → disabled）。ただし `error` prop（`ConfirmModal.tsx:99,123-127`）は**全呼び出し元で未使用**で「モーダル内の失敗表示」は実装されていない。加えて下記 M-2 のスクロール欠落あり。 |
| M3 callbackUrl 制限 | **塞がった** | `web/src/app/operator/login/page.tsx:33-36` で `/operator` 配下以外を既定へ丸め、`:47-55` で同一種別ログイン時の自動 replace を廃止しバナー＋サインアウト導線に置換。 |
| M4 {items,total}＋received 優先 | **一部** | 事前申込は `backend/app/api/v1/endpoints/admin.py:824-877`（status/q/limit/offset、`received_first` ソート、total）＋`web/.../operator-applications/page.tsx:100-111` で完全に塞がった。しかし同じ欠陥が残る**業者一覧には未適用**（下記 H-1）。 |
| M5 ページング境界 | **塞がった** | `web/src/app/admin/_components/AdminPagination.tsx:24-27` で `to = itemCount===0 ? 0 : offset+itemCount`、0件時表示も分岐済み。 |

---

## 2. 新規指摘（High 1 / Medium 5）

### H-1 業者一覧の検索・ステータス絞り込み・件数バッジが「現在ページの50件」だけを見ている（承認漏れ）
- 箇所: `web/src/app/admin/page.tsx:309-330`（`matchesOperatorSearch` / `operatorStatusCounts` / `filteredOperators`）、`:142`（`adminListOperators({limit: ADMIN_LIST_DEFAULT_LIMIT=50, offset})`）、`backend/app/api/v1/endpoints/admin.py:215-227`（`list_operators` は limit/offset のみ・status 絞込も total も返さない）
- 事象: r4 は事前申込一覧だけを backend 絞込（M4）に移行し、業者一覧はクライアント絞込のまま `limit` を 100（backend 既定）→ 50（明示）へ**縮小**した。ステータスバッジの数値（`:317-321`）も検索結果も現在ページ内の集計であり、全件数ではない。
- 再現: 業者が51件以上（active が新しい順に50件並ぶ状態）で /admin を開き「審査待ち」フィルタを押す → `filteredOperators.length===0` により `:622` の「該当なし」が出て、バッジも「審査待ち 0」と表示される。2ページ目に pending 業者が存在しても運営は気付けない。
- 影響: 業者承認はオンボーディングのクリティカルパス。誤った 0 件表示は承認漏れ＝売上機会の直接損失。
- 修正案: `GET /admin/operators` に `status` / `q` / `total` を追加（`list_operator_applications` と同型）し、`admin/page.tsx` の絞込・件数をサーバ委譲へ。暫定回避は困難（クライアント集計が全件でないため）。

### M-1 検索プレースホルダが「許可番号」を謳うが backend は company_name / contact_email しか検索しない
- 箇所: `web/src/app/admin/operator-applications/page.tsx:253`（`placeholder="会社名・メール・許可番号で検索"`） vs `backend/app/api/v1/endpoints/admin.py:848-856`（`or_(company_name.ilike, contact_email.ilike)` のみ）
- 再現: 申込の古物商許可番号（例 `第123456789012号`）を検索欄に入れて「検索」→ 常に `total=0`・「該当する申込はありません」。
- 影響: 運営が許可番号で照合する運用（TODO 01-4 の許可証確認フロー）で「申込が存在しない」と誤判断する。
- 修正案: backend の q に `OperatorApplication.license_number.ilike` を追加する（1行）。追加しないならプレースホルダから「許可番号」を削る。

### M-2 事前申込の承認/却下が失敗しても画面上見た目が変わらない（Notice が視界外）
- 箇所: `web/src/app/admin/operator-applications/page.tsx:167-168, 190-191`（`setError(...)` のみ） vs `web/src/app/admin/page.tsx:131-134`（`showError` が `window.scrollTo({top:0})` を伴う）
- 事象: M2 是正で「失敗時はモーダルを閉じてページ上部 Notice を出す」方式に統一したが、このページだけスクロール追従が無く、`ConfirmModal.error` も渡していない。一覧が50行あるため下部の行を操作すると Notice（`:220-224`、PageShell 最上部）が画面外に出る。
- 再現: 申込を51件投入 → 下部の行で「詳細を確認」→「承認する」→ backend を 409（既に審査済み）にする → モーダルが閉じるだけで、その場には何の表示も出ない。
- 修正案: `confirmApprove` / `confirmReject` の catch を admin/page.tsx と同じ `showError`（scrollTo 付き）に揃えるか、`ConfirmModal` の `error` prop を実際に配線してモーダルを閉じない。

### M-3 承認が既存 Operator の重複を検査せず、使用不能な招待コードを発行・送信する
- 箇所: `backend/app/api/v1/endpoints/admin.py:946-975`（`_issue_unique_invite_code` → `Invite(code, email=contact_email)` → `notify.send_operator_application_approved`）／衝突する検査は `backend/app/api/v1/endpoints/auth.py:340-345`（`Operator.contact_email == email` で 409）
- 再現: ある業者が /operator/signup のオープン登録（pending）で既に登録済み。同じメールで /business に事前申込 → 運営が承認 → 「承認しました。招待コード：XXXX」と表示され承認メールも届くが、申込者が本登録すると必ず 409「このメールアドレスは既に登録されています。」で詰む。
- 影響: 運営側は成功として処理を終えるため、問い合わせが来るまで気付けない。
- 修正案: approve の冒頭で `select(Operator).where(Operator.contact_email == application.contact_email)` を確認し、存在時は 409（＋「既存アカウントを承認してください」の導線）にする。

### M-4 `OperatorApplication.operator_id` が全経路で書き込まれず常に null
- 箇所: `backend/app/api/v1/endpoints/admin.py:153`（`operator_id=application.operator_id` を返す）、`web/src/lib/katadzuke-api.ts:1237`（TS で `operator_id: string | null` を公開）。書き込みは repo 全体で 0 件（`auth.py:364` は `invite.operator_id` であり別テーブル）。
- 事象: 承認済み申込が実際に業者登録まで到達したかを運営が判別できない。招待コードに有効期限も再送導線も無いため、未使用のまま放置された申込を検出する手段が存在しない。
- 再現: 申込を承認 → 申込者が本登録しない → /admin/operator-applications は「承認済み」としか表示せず、詳細モーダル（`:471-477`）も審査日時のみ。
- 修正案: `auth.py` の operator_signup で `invite.email` に一致する `OperatorApplication` を引き当てて `operator_id` を設定する。最低限、一覧に「招待コード未使用」バッジを出す。

### M-5 一覧 API の `status` が Literal でなく、不正値で 422 ではなく空一覧を返す
- 箇所: `backend/app/api/v1/endpoints/admin.py:824-826`（`status_filter: str | None = Query(alias="status", max_length=32)`）。対照: 同ファイル `:1051-1053` の identity-documents は `Literal["pending","approved","rejected","all"]`。
- 事象: `?status=pending`（received の誤り）等の綴り違いが 422 にならず `{"items":[],"total":0}` を返す。承認待ちキューが「0件」に見える無言の失敗になる。web 側（`page.tsx:58-63` の STATUS_OPTIONS）は現状正しい値のみを送るが、文言変更や外部ツール利用で即座に事故になる。
- 修正案: `Literal["received","approved","rejected"] | None` に狭める。

---

## 3. 未解決リスク（前回から継続・再指摘ではない）

1. `next build`（本番ビルド）は本監査でも未実行。CSS @layer 事故の既往あり。
2. web の自動テスト 0 件（TODO 03 の意図的未対応）。H-1 / M-2 のような画面挙動は静的検査では捕捉できない。
3. 本番 `BREVO_API_KEY` / `ALERT_LINE_CHANNEL_ACCESS_TOKEN` の実値未確認。両方未設定ならキー未設定アラート自体が無音（TODO 01-10 に記載済み・コード側は正しい）。
4. 業者規約版数 `2026-09-04`（`schemas_katadzuke.py:43`）への改定に対し既存業者の再同意ゲートは無い（意図的・TODO 01-9 で法務確認待ち）。
5. 口座全桁開示・停止・昇格の監査ログが標準出力のみ（TODO 03 の意図的未対応につき再指摘せず）。

## 4. サマリ

- ✅ H1（アラート配送テスト）・H2（認可負テスト30件）・M1・M3・M5 は実コードで塞がったことを確認。pytest 748 passed / tsc 0。
- ⚠️ M2・M4 は「一部」。M4 の是正が業者一覧に及んでおらず H-1（承認漏れ）として残存。Medium 5 件はいずれも運営オペレーションの穴。
- ❌ リリース阻害は H-1 のみ。業者一覧の絞込をサーバ委譲するまで、運営は「審査待ち 0」表示を信用してはならない。
