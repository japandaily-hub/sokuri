# r12-fix-frontend 結果（2026-09-06）

## 結論
- 決定1: 審査中(pending/rejected)業者への 403 approval_required を `/operator`・`/operator/cases`・`/operator/cases/[id]` で ApprovalPendingNotice に差し替え（raw エラー非表示化・spinner無限化を回避）。
- 決定2: `top_bid_amount`/首位/他社金額の表示を撤去し「入札 n 社」＋自社状況のみに統一、入札フォームに非開示注記を追加。
- 決定4: 「8%」全表示を「買取金額の8%（税別・消費税を別途加算）」に統一、docs 3件を更新。

## tsc・eslint 結果
- `npx tsc --noEmit`: エラー 0
- `npx eslint src`: エラー・警告 0
- `npx playwright test --list`: 30 tests / 7 files 検出、実行時エラーなし

## 変更ファイル
web/src/lib/katadzuke-api.ts（CaseMasked.top_bid_amount 削除）／
web/src/components/kdz/ApprovalPendingNotice.tsx（文言修正）／
web/src/app/operator/page.tsx（LotStatus簡素化・首位判定/現在の最高入札/うち首位削除・403吸収・写真onError・8%税別・非開示注記）／
web/src/app/operator/cases/page.tsx（403時ApprovalPendingNoticeへ全面差替・写真onError）／
web/src/app/operator/cases/[id]/page.tsx（errorCode追加・403でNotice表示・写真onError・8%税別・非開示注記）／
web/src/app/operator/profile/page.tsx, business/page.tsx, faq/page.tsx, page.tsx, legal/page.tsx, terms/TermsTabs.tsx（8%→税別表記）／
docs/beta-operator-onboarding.md, docs/ops/admin-operations.md, docs/TODO.md

## 未対応
- listBids の他社非開示は業者向け画面から未消費（web に業者用「入札一覧」画面が無い＝該当UIなし、対応不要と判断）。
- CSS `.lot-tag`/`.op-dash .lot-card.outbid` 等の未使用スタイルは削除せず残置（動作に影響なし、次回整理候補）。

## サマリー
✅ tsc/eslint/playwright list すべて合格。決定1・2・4を反映し3文書を更新。
