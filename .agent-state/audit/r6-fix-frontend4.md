# r6-fix-frontend4: 公開ページでの誤検知強制ログアウト是正

- 結論: パス一覧を `lib/protected-routes.ts` に一元化し、401共通処理を「保護ルートか」で分岐、装飾的呼び出し（AppHeaderBell）は常に静穏処理に固定した。
- 結論: `/vendors`・`/`・`/faq` 等の公開ページでは、backend JWT失効時も画面遷移・文言表示をせずヘッダーのみログアウト表示に切り替わる。
- 結論: `/mypage`・`/chat`等の保護ルートでの主要データ取得401は従来どおり案内文言＋役割別ログインへ遷移する（既存挙動を維持）。

## tsc / eslint
- `npx tsc --noEmit`: エラー0
- `npx eslint src`: エラー0（警告3件は本タスク対象外の既存ファイル: notifications/page.tsx, operator/transactions/[id]/page.tsx, signup/page.tsx）

## 変更ファイル
- `web/src/lib/protected-routes.ts`（新規）: USER_PROTECTED_PATHS / OPERATOR_PUBLIC_PATHS / isProtectedRoutePath を単一情報源化（next/server非依存）
- `web/src/middleware.ts`: ローカル定義を撤去し上記を import
- `web/src/lib/katadzuke-api.ts`: handleSessionExpired/throwHttpError/request に decorative・パス判定を追加、listTransactions/getTransaction に opts.decorative を追加
- `web/src/components/kdz/AppHeaderBell.tsx`: 2箇所の呼び出しに `{ decorative: true }` を付与

## 確認（コードリーディング）
`/vendors` の一覧取得（getVendors）はトークン不要で401対象外。ページ上で唯一401しうるのはヘッダーの AppHeaderBell（decorative:true固定）のみのため、backend JWT失効時もリスト表示中の画面は再読み込み・遷移されず、ヘッダー表示のみログアウト状態に切り替わる。ミドルウェアの初回ログインゲート（`/vendors`はUSER_PROTECTED_PATHS）自体は本タスクの変更対象外（既存仕様として維持）。

## 未対応
- `/vendors` がミドルウェアでログイン必須ルートである点自体は今回変更していない（初回アクセス時に未ログイン訪問者はmiddlewareで/loginへ誘導される既存仕様。今回のバグは「セッション保持中だがbackend JWT失効」のケースへの対処）。

## サマリ
✅ tsc/eslintエラー0で実装完了
