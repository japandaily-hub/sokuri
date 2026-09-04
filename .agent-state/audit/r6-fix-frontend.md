# r6-fix-frontend — web側7項目の実装

結論: 7項目すべて実装した。backendは並走セッションが契約どおり実装済み（ai_status/idempotency_key/operator_suspended/unread_count/REDUCTION系すべて実在）で、web型を実測に合わせて追従させた。tsc/eslintともに新規エラー0。

## tsc・eslint結果
- `npx tsc --noEmit`: エラー0
- `npx eslint src`: エラー0（warning 3件は既存・本タスク無関係: notifications/page.tsx:195, operator/transactions/[id]/page.tsx:87 の未使用eslint-disable、signup/page.tsx:59 の未使用router）

## 変更ファイル
- 型・共通定義: `web/src/lib/katadzuke-api.ts`（CaseOut.ai_status、CaseCreatePayload.idempotency_key、BidOut/TransactionListItem/TransactionDetail に operator_suspended・unread_count、REDUCTION_STATUS_LABEL/REDUCTION_CHIP_CLASS新設）
- 案件作成〜解析: `web/src/app/create/page.tsx`（idempotency_key発行・180秒タイムアウト撤去・文言整理）、`web/src/app/cases/[id]/page.tsx`（ai_status pending/failedポーリングUI、停止業者バナー、減額履歴、REDUCTION_STATUS_LABEL利用）
- 未読バッジ: `web/src/app/mypage/page.tsx`+`mypage.css`、`web/src/app/operator/transactions/page.tsx`+`operator-shared.css`
- ラベル共通化: `web/src/app/operator/transactions/[id]/page.tsx`（ローカル定義を削除しlib importに統一）
- canonical(H4): `layout.tsx`未変更（root継承のまま）、`faq/business/examples/contact/vendors/unsubscribe/condition/login/signup/password-reset/verify-email/operator/login/operator/signup` の各layout.tsxに`alternates.canonical`追加、`company/legal/privacy/terms/page.tsx`に追加、`vendors/[id]/layout.tsx`は`generateMetadata`化してid別canonical対応
- sitemap(M3): `sitemap.ts`に公開10ページ追加（vendors/[id]は動的につき除外、password-reset/verify-email/unsubscribeは意図的に含めず）
- ConfirmModal(M1/Low): `admin/_components/ConfirmModal.tsx`に初期フォーカス・Esc・Tabフォーカストラップ追加
- M4画像: 対象箇所（operator/cases/[id]:204）は`operator-shared.css`の`.op-photo-grid img{aspect-ratio:1}`が既に適用済みと確認、追加修正不要

## backendに依存する未確認点
- POST /cases が実際にai_status=pendingで即応答するかは実機/結合テスト未実施（型契約のみ整合確認）。list_bidsは「除外」でなく「operator_suspendedフラグを立てる」実装（Block2の想定と相違、schemas_katadzuke.pyコメントで確認）と分かり、フロントは選択ボタン無効化＋警告表示で対応した。

## 未対応（意図的・スコープ外）
- login/signup等をsitemapへ追加するかは指示になく見送り（r6-verify-web M3注記どおり据え置き）
- REDUCTION労ベルの配置先は指示文の`lib/case-labels.ts`でなく既存の`*_LABEL`群と同じ`katadzuke-api.ts`に統一（既存スタイル優先、case-labels.tsは別用途の関数のみで用途が異なるため）

## サマリー
✅ 7項目実装完了・tsc/eslintエラー0。backend契約とのフィールド名・型不一致なし（bids.py/transactions.py実測で確認済み）。
