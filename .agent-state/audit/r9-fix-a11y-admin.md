# r9-fix-a11y-admin

- 対象: web/src/app/admin/{page.tsx, cases, transactions, users, operator-applications, identity-documents}/page.tsx
- text-slate-400 の本文テキスト（招待コード/業者メタ情報・dt項目名・読み込み中・退会済み注記・画像プレースホルダ等）を text-slate-600 に変更。装飾アイコン（✕閉じるボタン、hover:text-slate-600 併用の3箇所）は据え置き。
- admin/page.tsx: 発行件数・ロット名の label/input を htmlFor/id で関連付け（admin-bulk-count / admin-bulk-lot-name）。
- 6ファイル全ての overflow-x-auto ラッパーに tabIndex={0} role="region" aria-label（内容に即した文言: セル密度一覧/案件一覧/取引一覧/依頼者一覧/事前申込一覧/本人確認書類一覧）を付与。
- src/components/kdz/Ui.tsx の StatusBadge（rejected/withdrawn が bg-slate-200 text-slate-500 のまま=3.86:1）は指示通り未変更。指示原文と矛盾（「既に600へ変更済み」は誤認、実際は cancelled のみ600・rejected/withdrawn は500のまま）。次回 r10 で対応要否をユーザーに確認。
- tsc --noEmit: エラー0。eslint src: エラー0（既存警告3件は本タスク対象外・変更ファイルに影響なし）。
