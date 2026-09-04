# r8-fix-frontend3

H-2/H-3/H-4（web側）と表示側の空欄・折り返しを修正。ConfirmModal に withPassword を追加し
operator/profile の退会モーダルへ配線（DELETE /operator/me に {password} 送信、403/409/429 を区別表示）。

## tsc・eslint 結果
- `npx tsc --noEmit`: exit 0 / エラー 0
- `npx eslint src`: 0 errors, 3 warnings（すべて差分外の既存: notifications/page.tsx:196・operator/transactions/[id]/page.tsx:89・signup/page.tsx:59）

## 変更ファイル
- web/src/components/kdz/ConfirmModal.tsx（withPassword/passwordLabel 追加、onConfirm に password 引数追加）
- web/src/lib/katadzuke-api.ts（deleteMyOperatorAccount(password, token) に変更、body 送信）
- web/src/app/operator/profile/page.tsx（退会モーダルにパスワード欄、403/409/429 分岐表示）
- web/src/app/operator/transactions/[id]/page.tsx（H-2: キャンセルモーダルに開示告知／表示側: 理由の記載なし+折り返し）
- web/src/app/admin/transactions/page.tsx（H-3: 強制終了モーダルに双方開示の告知）
- web/src/app/cases/[id]/page.tsx（表示側: 理由の記載なし+break-words）

## 未対応
- H-1（backend: 退会と落札選定の競合直列化）・M-1〜M-6・L-1〜L-5 は本ミッションのスコープ外（backend/他担当）

サマリ: ✅ H-2/H-3/H-4（web側）修正完了・tsc 0 エラー・eslint 0 エラー
