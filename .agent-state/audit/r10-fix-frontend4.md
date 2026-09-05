# r10-fix-frontend4（2026-09-05）

対象: r10-review.md の H1・H2・M2〜M5・L2 を修正。

## 修正内容
- H1: admin/page.tsx の reload() 本体を try/finally で包み、identityResult.value?.counts?.pending ?? null に修正（旧応答形式でも例外にならず必ず setInitialLoadDone(true) が呼ばれる）。
- H2: katadzuke-api.ts に reduction_request_count/limit を `?:` 化し、共通ヘルパー getReductionQuota()（既定上限2・count/limit未定義時は残り不明=null）を追加。operator/transactions/[id]/page.tsx を置き換え、remaining===0 のときのみフォーム非表示（nullでは表示維持）。
- M2: cases/[id]/page.tsx に減額履歴直前で「業者の申請は1つの取引につき{limit}回まで（残り{remaining}回）」を表示（getReductionQuota流用、active時のみ）。
- M3: operator/page.tsx の「今月の落札」→「今月の成約（落札日基準・キャンセル除く）」。operator/transactions/[id]/page.tsx の「成約額」→「成約金額」。
- M4: admin/identity-documents/page.tsx のステータスボタンラベルに「（全体 N）」を明記（例: 審査待ち（全体 37））。絞り込み結果は既存の AdminPagination の data.total 表示のまま。
- M5: KdzApiError に code（detail.code）を追加、throwHttpError で伝播。create/page.tsx に accountSuspended state を追加し、403+account_suspendedのみ /contact リンク付き停止案内、それ以外の401/403はセッション切れ文言。
- L2: signup/page.tsx の未使用 router(useRouter) を削除。加えて eslint 警告0化のため operator/transactions/[id]/page.tsx・notifications/page.tsx の不要な eslint-disable-next-line react-hooks/exhaustive-deps（Unused directive警告）も除去。

## 検証結果
- `npx tsc --noEmit`: エラー0
- `npx eslint src`: エラー0・警告0

## 変更ファイル
- web/src/lib/katadzuke-api.ts
- web/src/app/admin/page.tsx
- web/src/app/operator/transactions/[id]/page.tsx
- web/src/app/cases/[id]/page.tsx
- web/src/app/operator/page.tsx
- web/src/app/admin/identity-documents/page.tsx
- web/src/app/create/page.tsx
- web/src/app/signup/page.tsx
- web/src/app/notifications/page.tsx
