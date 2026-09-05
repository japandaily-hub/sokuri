# r10 引き渡し事項の解消（r10-fix-frontend3）2026-09-05

## 結論
- M9: `katadzuke-api.ts` の `uploadCasePhoto`/`createCase` に `skipAuthRedirect` オプションを追加し公開。
  `create/page.tsx` の該当2箇所の呼び出しに `{ skipAuthRedirect: true }` を渡し、catch 側で
  `KdzApiError` の 401/403 を検知して指定文言（画面遷移なし・写真/入力保持・再送信ボタン有効のまま）を表示するよう変更。
- backend 側の `AdminUserListItem.deleted_at` / `TransactionListItem.visit_time_slot` は、
  本リポジトリ・全 worktree（`adoring-easley-379443`/`eloquent-pike-7b4b0e`/`trusting-elbakyan-088911`）の
  `schemas_katadzuke.py` を確認したが未実装（「同時実装中」の前提と現状が不一致）。
  `deleted_at` は既に `AdminUserListItem` に任意フィールドとして実装済みだったためそのまま活用（admin/users の
  退会済みバッジ・操作非表示も既存実装のまま）。`visit_time_slot` は `TransactionListItem` に **任意フィールド**
  として追加し、backend 未対応の間は `formatVisitSchedule()` が `visit_date` のみの表示にフォールバックする
  形にして、mypage/operator-transactions の表示側を先行実装した（backend 実装後は無変更で時間帯が出る）。

## tsc・eslint 結果
- `npx tsc --noEmit`: エラー 0
- `npx eslint src`: エラー 0（警告3件、いずれも既存・本タスク無関係: `notifications/page.tsx:196`
  `operator/transactions/[id]/page.tsx:90` の stale disable directive、`signup/page.tsx:47` の未使用 `router`）

## 変更ファイル
- `web/src/lib/katadzuke-api.ts`
  - `uploadCasePhoto(file, token, opts?: { skipAuthRedirect })` / `createCase(payload, token, signal?, opts?: { skipAuthRedirect })` を追加（末尾に任意引数として追加、既存呼び出し元は無影響）。
  - `TransactionListItem.visit_time_slot?: string | null` を追加（[推測] backend 未実装、既存の optional フィールドパターンを踏襲）。
- `web/src/app/create/page.tsx`
  - `KdzApiError` を import。`uploadCasePhoto` 2箇所・`createCase` 1箇所に `skipAuthRedirect: true` を付与。
  - catch 内で 401/403（`KdzApiError` かつ `status===401||403`）を検知し、指定の日本語文言を表示（`setSubmitting(false)` により再送信ボタンは有効のまま。写真アップロード済みキャッシュ・フォーム state は既存どおり保持）。
- `web/src/app/operator/transactions/page.tsx`: 一覧の `formatVisitSchedule(t.visit_date, null)` を `t.visit_time_slot` を渡す形に変更。
- `web/src/app/mypage/page.tsx`: `visitInfoByCaseId`（status===pending/visiting の取引のみ）を追加し、`LotCard` に `visitInfo` prop を新設して出品カードに「訪問日 …」を併記。

## 未対応・要確認
- backend の `AdminUserListItem.deleted_at`（既存）以外は据え置き。`TransactionListItem.visit_time_slot` は
  backend 実装が入るまで常に `undefined` として届き、mypage/operator-transactions ともに「訪問日 …（時間帯なし）」
  または「未確定」表示のまま。backend 側の追加が完了次第、フロント側の追加変更は不要（契約変更なし）。
