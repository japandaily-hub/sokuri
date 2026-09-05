# r10 修正の統合レビュー（2026-09-05・opus・レビュアーは Write 不可のためリーダー転記）

総合判定: 条件付き合格（Critical 0 / High 2 / Medium 6 / Low 4）。pytest 851・tsc 0・eslint 0 error・単一ヘッド 0032。

## High
- H1 admin/page.tsx:213 `identityResult.value.counts.pending` が旧応答（配列）で TypeError → reload reject → initialLoadDone 未設定で /admin が永久スピナー。→ optional chaining＋finally。
- H2 operator/transactions/[id]/page.tsx:151 `Math.max(0, NaN)` で減額フォームと上限説明が両方消える（backend 未反映時）。→ `?? MAX` フォールバックと型の `?:` 化。
## Medium
- M1 contact_messages に保持期間・削除 API が無く privacy:110 の削除請求に応えられない。
- M2 reduction_request_limit の依頼者側表示が未実装（自己申告と乖離）。
- M3 文言: 「今月の落札」新設が統一方針と逆行、成約金額／成約額の揺れ。
- M4 identity counts が q/status 非反映で誤読 → 「全体」明記。
- M5 create/page.tsx:459 が 403 を一律セッション切れ扱い（account_suspended を誤案内）。
- M6 admin.py:319-329 pending_with_license が is_suspended を除外していない。
## Low
- L1 schemas コメントの順序記述／L2 signup 未使用 router／L3 /admin/contacts に q 無し／L4 uptime の exit 1 は通知必要時のみ。
## 未解決リスク
next build 未実行／0032 の PG 実適用未実証／/admin/contacts の実機未カバー／backend 先行デプロイの運用ルール未記載／contact キャップはプロセス内。
