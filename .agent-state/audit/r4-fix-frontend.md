# r4 回帰是正（web フロントエンド）実装報告

結論: r4監査で確定した8項目（事前申込審査UI新設・3一覧の無言truncate是正・検索文言・確認モーダル統一・operator/login自動遷移・本人確認文言統一・SLA/文言統一・改定日更新）を全て実装した。
結論: 新規 `/admin/operator-applications` を含め admin 全画面で `window.confirm` を撤廃し `ConfirmModal` に統一、業者承認取消にも確認を追加した。
結論: `AdminPagination` を `total: number | null` 対応に拡張し、backendがtotalを返さない3一覧（業者・招待コード・本人確認書類）は「表示中N件」表示に変更した。

tsc: `npx tsc --noEmit` エラー0。
eslint: `npx eslint src` エラー0（警告3件はいずれも本タスク対象外ファイルの既存警告 = signup/page.tsx未使用router、notifications/page.tsx・operator/transactions/[id]/page.tsxの既存eslint-disable未使用）。

変更ファイル:
- web/src/lib/katadzuke-api.ts（operator-applications admin用5関数・型追加／adminListOperators・adminListInvites・listIdentityDocumentsAdminにlimit/offset追加／本人確認法令コメント2箇所是正）
- web/src/app/admin/_components/AdminPagination.tsx（total: number|null対応）
- web/src/app/admin/page.tsx（事前申込ナビ+pendingバッジ・業者/招待コードのlimit/offset+ページング・ConfirmModal化・承認取消の確認追加）
- web/src/app/admin/identity-documents/page.tsx（limit/offset+ページング・承認をConfirmModal化）
- web/src/app/admin/cases/page.tsx・transactions/page.tsx（検索プレースホルダ「前方一致」→「完全一致」）
- web/src/app/operator/login/page.tsx（業者ログイン済み時の自動replace useEffect追加）
- web/src/app/mypage/profile/page.tsx・notifications/page.tsx・faq/page.tsx・contact/page.tsx・privacy/page.tsx・terms/page.tsx（文言・改定日・収集項目表の是正）

新規ルート:
- web/src/app/admin/operator-applications/page.tsx（一覧・状態フィルタ・検索・ページング・詳細モーダル・承認/却下ConfirmModal・口座情報開示ボタン）

未対応:
- pending件数バッジ・operator-applications一覧の検索/絞り込みは「表示中ページのみ」対象（backendがtotal/statusフィルタを提供しないための制約。UI上に明記済み）。
- r4-crosscut R4-H3（招待業者向け運用文書の「許可番号任意」表記）・ADD-H1（業者規約同意バージョン定数の不一致）はbackend/docs対象のため本ミッション範囲外・未着手。

サマリ: ✅ tsc/eslint エラー0で8項目実装完了。⚠️ pending件数等は「backendにtotalが無い」制約下の近似表示（UIに明記）。❌ ブロッカーなし。
