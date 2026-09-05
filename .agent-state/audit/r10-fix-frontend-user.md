# r10 依頼者導線 修正実施記録（frontend-user）2026-09-05

## 結論
- H2/H3/M1〜M3/M5〜M8/ADD-H1/O-H-1 は実装完了。tsc・eslint とも 0 エラー。
- M9（401/403 時に画面遷移させず入力保持）は実装不能: `uploadCasePhoto`/`createCase`（`src/lib/katadzuke-api.ts`、担当外）が
  `skipAuthRedirect` を呼び出し側に公開しておらず、その拡張には当該ファイルの編集が必須のため見送り。API 担当への申し送りが必要。
- M4 はタブ実装が `/cases` ではなく `/mypage` 内クライアント state だったため、サマリー3枚を `/mypage?tab=` へ変更し `useSearchParams` 監視で反映。

## tsc・eslint 結果
- `npx tsc --noEmit`: エラー 0
- `npx eslint src`: エラー 0（警告5件、いずれも本タスクと無関係な既存warning。`signup/page.tsx:47` の未使用 `router` も既存=HEAD時点で存在）

## 変更ファイル
- `web/src/app/create/page.tsx`（H2 capture削除／ADD-H1 STEP3冒頭注記／M3 送信ボタン文言／M6 市区町村未入力の理由表示）
- `web/src/app/signup/page.tsx`（H3 エリア/利用目的をフォーム・確認画面・説明文から削除、完了画面に対応4都県を1行追記）
- `web/src/app/mypage/profile/page.tsx`（ADD-H1 都道府県直下に対応4都県の注記）
- `web/src/app/mypage/page.tsx`（M4 サマリー3枚を`/mypage?tab=`へ・`useSearchParams`監視／M5 入札受付中をstatus==="open"基準に統一）
- `web/src/app/cases/page.tsx`（M3 「依頼」→「出品」統一）
- `web/src/app/cases/[id]/page.tsx`（M1 取り下げ案内をflex行外へ／M2 「成約金額」統一／M7 評価後導線追加／M8 window.prompt2箇所をConfirmModal reasonRequiredへ）
- `web/src/app/chat/[id]/page.tsx`（M2 「成約金額」統一／O-H-1 取引終了時にcancellation表示）
- `web/src/app/schedule/page.tsx`（M2 「成約金額」統一・2箇所）

## 未対応
- M9: `skipAuthRedirect` を `uploadCasePhoto`/`createCase` に通す拡張が `katadzuke-api.ts`（担当外ファイル）側で必要。フロント側（create/page.tsx）の受け皿実装のみでは完結しない。

## 末尾サマリ
✅ H2・H3・ADD-H1・M1・M2・M3・M5・M6・M7・M8・O-H-1 実装済み、tsc/eslint 0エラー
⚠️ M4 は `/cases` フィルタ非対応のため `/mypage` 内タブ絞り込みに変更（設計判断・要確認なら差し戻し可）
❌ M9 未対応（katadzuke-api.ts 拡張が別担当スコープのため）
