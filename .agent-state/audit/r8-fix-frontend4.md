# r8-fix-frontend4

結論: L-1（ConfirmModal busy中の閉じ操作無効化・パスワード欄maxLength/Enter確定・理由欄maxLength=500と残り文字数）を実装。
admin一覧に「退会済みを含める」トグルとdeleted_atバッジ・操作ボタン非表示を追加、katadzuke-api.tsのOperatorOutにdeleted_atを追加。
mypage/withdraw・operator/profileの誤パスワード表示を400/403両対応に統一、cancel理由欄に注記+maxLength=2000を追加。

## tsc / eslint
- `npx tsc --noEmit`: エラー0
- `npx eslint src`: エラー0（既存の警告3件のみ、本変更起因の新規警告0）

## 変更ファイル
- src/components/kdz/ConfirmModal.tsx
- src/app/admin/page.tsx
- src/lib/katadzuke-api.ts
- src/app/mypage/withdraw/page.tsx
- src/app/operator/profile/page.tsx
- src/app/operator/transactions/[id]/page.tsx
- src/app/operator/operator-shared.css

## 未対応
- Medium 6件（M-1〜M-6）・H-1残窓はbackend側担当スコープにつき本ミッション対象外。

サマリ: ✅ tsc 0 / eslint 0 / L-1・admin退会トグル・400/403統一・理由注記を実装完了
