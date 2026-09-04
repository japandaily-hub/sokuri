# r7 web 回帰監査 是正（フロントエンド）

- H1（冪等キー使い回し）: 送信ペイロード（purpose/prefecture/city/address_detail/housing_type/floor_plan/floor_number/has_elevator/items/photos）の安定なJSON文字列を `lastSubmitSignatureRef` に保持し、送信時に前回と異なれば `crypto.randomUUID()` で再発行、同じなら使い回す方式に変更。「戻る」で編集後の再送信でも新しいキーが発行され、backendの冪等一致（同一キー10分以内は既存案件を200で返す）で旧内容が無言採用される事故を防止。送信成功後はキーを破棄。
- M1（タイムアウト保護）: デッドコード化していた `createTimeoutSignal` を再利用し、`createCase()` に60秒の `AbortSignal` を付与。タイムアウト時（`KdzNetworkError.cause?.name === "TimeoutError"`）は指定文言を表示し、`submitting=false` により送信ボタンは自動的に再活性化（冪等キーは内容不変なら同一値のため安全に再試行可）。

## tsc・eslint 結果
- `npx tsc --noEmit`: エラー 0
- `npx eslint src`: エラー 0（既存の無関係な warning 3件のみ、対象ファイルの変更起因なし）

## 変更ファイル
- `web/src/app/create/page.tsx`
- 変更なし: `web/src/lib/katadzuke-api.ts`（既存の `createTimeoutSignal`/`createCase(signal)` をそのまま再利用、追加実装不要と判断）

## 未対応
- なし（Block2記載のH1/M1は両方対応）

## サマリ
✅ H1（冪等キー再発行）実装完了
✅ M1（60秒タイムアウト + 案内文言）実装完了
✅ tsc/eslint エラー 0
