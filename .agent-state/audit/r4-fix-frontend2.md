# r4 レビュー残指摘（web）修正報告

結論: M1〜M5・L1の6項目を全て実装した。M1はPromise.allSettledで4区画（招待/業者/セル密度/事前申込バッジ）を独立エラー化。M2はadmin/page.tsx・operator-applications・users・identity-documentsの全ConfirmModal系フローで失敗時にTargetをクリアしてモーダルを閉じNoticeを出す形に統一し、ConfirmModalへerror/reasonRequiredを追加（却下理由必須はUIレベルでボタンdisabled化）。
結論: M3は/operator/loginのcallbackUrlを/operator配下限定にし、同一アカウント種別（業者）ログイン中でも自動遷移せずバナー＋サインアウト導線を表示する形に変更。M4はadminListOperatorApplicationsをbackend契約（status/q/limit/offset→{items,total}）に合わせて刷新し、admin/page.tsxのバッジとoperator-applications一覧の検索・フィルタ・ページングをbackend側委譲に切替。M5はAdminPagination.tsxのto計算・0件表示を是正。L1は口座種別に「不明」フォールバックを追加。

tsc（npx tsc --noEmit）: エラー0。
eslint（npx eslint src）: エラー0（警告3件は本タスク対象外の既存警告=signup/page.tsx未使用router、notifications/page.tsx・operator/transactions/[id]/page.tsxの既存eslint-disable未使用。r4-review.md記載のベースラインと一致）。

変更ファイル:
- web/src/lib/katadzuke-api.ts（OperatorApplicationListResponse追加、adminListOperatorApplicationsをAdminListParams/buildAdminListQueryに切替）
- web/src/app/admin/_components/ConfirmModal.tsx（error/reasonRequired追加、Notice表示、却下理由空欄でボタンdisabled+ヒント表示）
- web/src/app/admin/_components/AdminPagination.tsx（to計算・0件時表示の是正）
- web/src/app/admin/page.tsx（reload()をPromise.allSettled化・区画別error state、事前申込バッジをtotalベースに変更、suspend/verify失敗時にTargetクリア）
- web/src/app/admin/operator-applications/page.tsx（一覧をbackend側status/q/limit/offset+total化、検索ボタン化、approve/reject失敗時にTargetクリア、reject ConfirmModalにreasonRequired、account_typeに不明フォールバック）
- web/src/app/admin/users/page.tsx・admin/identity-documents/page.tsx（ConfirmModal失敗時のTargetクリアを波及適用）
- web/src/app/operator/login/page.tsx（callbackUrlを/operator配下限定、同一アカウント種別ログイン中の自動遷移useEffect廃止しバナー＋サインアウト導線を追加）

未対応:
- operator-applications一覧のステータス別フィルタボタンの件数表示は撤去（backendが単一絞り込み結果のtotalしか返さない契約のため、全ステータス内訳を出すには別途集計APIが要る。範囲外）。
- login/page.tsx側は「同一アカウント種別ログイン中でも自動遷移せずバナーを出す」機能を追加していない（M3はoperator/login/page.tsxのみが対象。既存の他アカウント種別バナーのみ確認・対称性ありと判断）。
- backend側のGET /admin/operator-applications拡張（status/q/total対応）は本ミッション範囲外（backend担当が並行実装中）。本実装はその契約を前提に配線済みで、backend未対応の間は404/422になる可能性がある。

サマリ: ✅ 6項目実装完了・tsc/eslintエラー0。⚠️ backend側のGET /admin/operator-applications拡張が未マージの間はoperator-applications一覧・事前申込バッジが動作しない（契約前提の配線）。❌ ブロッカーなし。
