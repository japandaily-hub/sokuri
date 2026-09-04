# r8-fix-frontend 結果

1. cases/[id] の4つの window.confirm を ConfirmModal（confirmState + setConfirmState パターン）へ置換し、減額却下にも新規確認を追加した。
2. bank-account・operator/transactions/[id] は既に window.confirm 非依存（独自インライン確認/モーダル実装済み）で対応不要だった。
3. purpose を CASE_PURPOSES（Literal）+ formatPurposeLabel で一元化し、未知値は「その他」にフォールバックする。

## tsc・eslint
- `npx tsc --noEmit`: エラー0
- `npx eslint src`: エラー0（既存の警告3件のみ、未変更ファイル由来）
- `grep -rn "window\.confirm(" src`: 0件

## 変更ファイル
- 新規: `web/src/components/kdz/ConfirmModal.tsx`（admin/_components/ConfirmModal.tsx から移動）
- `web/src/app/admin/_components/ConfirmModal.tsx`（再エクスポートのみの互換シムに変更）
- `web/src/app/cases/[id]/page.tsx`（4箇所の confirm を ConfirmModal 化、reduction reject に確認追加）
- `web/src/app/operator/cases/[id]/page.tsx`（LINE/メール文言修正 + purpose 表示）
- `web/src/lib/case-labels.ts`（CASE_PURPOSES・formatPurposeLabel 追加）
- `web/src/app/create/page.tsx`（PURPOSES を case-labels からimport）
- `web/src/app/{mypage,cases,cases/[id],operator/page,operator/cases,operator/cases/[id],operator/transactions,operator/transactions/[id],admin,admin/cases,review}/page.tsx`（purpose表示をformatPurposeLabel化）

## 未対応
- backend の purpose Literal化は対象外（別途）
- bank-account/page.tsx のコメントに古い「window.confirm」表記が残存（実装は既に非依存、コメントのみ stale。動作に影響なし）

## サマリ
✅ tsc 0 / eslint 0 / window.confirm 残存 0 を全て達成
