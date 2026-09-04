# r8-fix-frontend5

- 課題: `GET /transactions/{id}` の `operator_deleted`（業者退会）をフロントに反映
- 実装: `TransactionDetail.operator_deleted: boolean` を追加。`cases/[id]/page.tsx` と
  `chat/[id]/page.tsx` に operator_suspended バナーと同部品・同語彙で
  「この業者は退会したため、この取引は進められません。キャンセルして新しく出品してください」を表示。
  チャット送信・日程調整導線・完了確定を非表示にし、キャンセルボタンのみ残した
  （chat 側は日程確定ボタンを disabled + ラベル変更、入力欄をキャンセル不可の案内に置換）。
- tsc --noEmit: エラー0
- eslint src: エラー0（既存warning3件のみ、対象外ファイル）
