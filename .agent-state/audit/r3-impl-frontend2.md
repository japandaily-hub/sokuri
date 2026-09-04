# R3 フロントエンド実装2 — 管理画面 案件/取引/依頼者一覧 + 文言是正

対象根拠: `.agent-state/audit/r3-operator.md` H2 / `r3-verify-operator.md` ADD-2
バックエンド契約: `.agent-state/audit/r3-impl-backend.md`（/admin/cases, /admin/transactions 実装済み。/admin/users は別担当と並行のため契約のみで実装）

## 変更ファイル:行

- `web/src/lib/katadzuke-api.ts`
  - `:1440-1560`付近（旧 `adminGetCellDensity` 直後）: `AdminCaseListItem/Response`, `AdminTransactionListItem/Response`, `AdminListParams`, `buildAdminListQuery`, `adminListCases`, `adminListTransactions`, `AdminUserListItem/Response`, `adminListUsers`, `AdminUserSuspendResponse`, `adminSuspendUser` を追加
  - `:768`付近: 振込口座セクションコメントを「振込口座（お振込みを希望する場合に業者へ伝える口座情報。業者へ自動開示はしない）」に是正
  - `:827`付近: 本人確認セクションコメントを「本人確認（なりすまし・不正出品の防止のため。任意提出）」に是正
- `web/src/app/admin/page.tsx:301-315`付近: actions を複数リンク（案件一覧／取引一覧／依頼者一覧／本人確認書類の審査）に拡張
- `web/src/app/admin/cases/page.tsx`（新規）: 案件一覧（検索・ステータス絞込・50件ページング・`/cases/{id}`への「依頼者画面で開く」リンク）
- `web/src/app/admin/transactions/page.tsx`（新規）: 取引一覧（同上・`/chat/{id}`への「依頼者画面で開く」リンク）
- `web/src/app/admin/users/page.tsx`（新規）: 依頼者一覧・停止/解除（ConfirmModal使用、role=adminは操作ボタン非表示）
- `web/src/app/admin/_components/ConfirmModal.tsx`（新規）: window.confirmを使わない共通確認ダイアログ（理由入力可）
- `web/src/app/admin/_components/StatusFilterBar.tsx`（新規）: ステータス絞込ボタン列（既存admin/page.tsxのパターンを汎用化）
- `web/src/app/admin/_components/AdminPagination.tsx`（新規）: 前へ/次へ + 総件数表示
- `web/src/app/admin/_components/CopyableId.tsx`（新規）: ID省略表示＋クリックコピー

## 追加ルート

- `/admin/cases`, `/admin/transactions`, `/admin/users`（いずれも `_components` は Next.js private folder規約でルート化されない）

## 追加API関数名

`adminListCases`, `adminListTransactions`, `adminListUsers`, `adminSuspendUser`（型: `AdminCaseListItem/Response`, `AdminTransactionListItem/Response`, `AdminUserListItem/Response`, `AdminUserSuspendResponse`, `AdminListParams`, 定数 `ADMIN_LIST_DEFAULT_LIMIT`）

## tsc / eslint

- `npx tsc --noEmit`: 0 エラー
- `npx eslint src`: 0 エラー（既存の無関係warning 3件のみ: notifications/page.tsx, operator/transactions/[id]/page.tsx, signup/page.tsx — 本タスクでは未編集）

## 未対応

- `/admin/users` バックエンドが別セッションで並行実装中のため、実機での動作確認は未実施（契約書通りに実装。フィールド名・型は`r3-impl-backend.md`記載契約と一致させた）
- モバイル375px実機スクショ確認は未実施（既存テーブルと同じ`overflow-x-auto`パターンを踏襲した設計上の担保のみ）
- `next build`は指示によりスコープ外のため未実行

## サマリ

✅ 管理画面の案件・取引・依頼者一覧UIを追加し、tsc/eslintともにエラー0で完了。
