# r12 web Medium/Low 修正（frontend2）

対象: `.agent-state/audit/r12-review.md` の web 側 M-1〜M-4・L-4。

## 実施内容
- M-1: `OPERATOR_CASE_VIEW_STATUSES = ["active","limited"]` を `lib/katadzuke-api.ts` に定数化（backend `api/deps.py` と対称）。`operator/cases/page.tsx`・`operator/page.tsx` の `awaitingApproval` をこれで判定し直し、`limited` は一覧を描画するよう是正（`operator/cases/[id]/page.tsx` の `awaitingApproval` は入札フォーム専用ゲートで `limited` も入札不可のため据え置き）。
- M-2: `ApprovalPendingNotice` に `vendorStatus` prop を追加し `rejected` 分岐（「審査の結果、ご登録を承認できませんでした」＋`/contact`導線）を実装。3画面の呼び出し箇所すべてに `vendorStatus` を渡すよう更新。
- M-3: `operator/cases/page.tsx`・`operator/page.tsx` に `approvalRequired` state を追加し、`listOpenCases` の 403 `approval_required` 捕捉時に立てる。`awaitingApproval = approvalRequired || (...)` とし、profile 取得の成否に関わらず Notice を出す。
- M-4: `operator/chat/[id]/page.tsx` のラベルを「手数料予定額（買取額の8%・税別）」に変更。
- L-4: `e2e/08-operator-visibility-regression.spec.ts` を新設。(a) pending 業者は API 403 approval_required・`/operator/cases` で承認待ち案内のみ・`.lot-card` 0件。(b) vendor の自社入札済み案件詳細に「自社の入札」のみ表示され「最高入札」「首位」が無いこと、および他社のみ入札した別案件の一覧カードに集計件数（`入札 n 件|社`）はあるが「最高入札」「首位」は無いことを検証。

## 判断メモ（[推測]ではなく実装上の裁量）
- 依頼原文の L-4(b) は「『最高入札』『首位』『他社』の文言が無く」としていたが、現行の安全な実装は一覧カードで「入札 n 件（**他社**）」・入札フォーム注記で「**他社**の入札額は表示されません」と、非開示を明示するために意図的に「他社」という語を使っている（過去の禁止対象は金額・順位の開示であり、語そのものではない）。実際に金額・順位を開示していた旧モック実装（コミット `ae7336f`、実API配線前）は「現在の最高入札」「入札首位」「n社が入札中」だった。よってテストは「最高入札」「首位」の不在（真の回帰ガード）と「入札 n 件/社」という集計件数のみの開示を検証し、「他社」という語自体の不在は安全な既存文言と矛盾するため対象外とした。

## 検証結果
- `npx tsc --noEmit`: エラー 0
- `npx eslint src e2e`: エラー 0
- `npx playwright test --list`: 34 tests in 8 files（新規2件を含む）

## 変更ファイル
- `web/src/lib/katadzuke-api.ts`
- `web/src/components/kdz/ApprovalPendingNotice.tsx`
- `web/src/app/operator/cases/page.tsx`
- `web/src/app/operator/page.tsx`
- `web/src/app/operator/cases/[id]/page.tsx`（`vendorStatus` prop 受け渡しのみ）
- `web/src/app/operator/chat/[id]/page.tsx`
- `web/e2e/08-operator-visibility-regression.spec.ts`（新規）
