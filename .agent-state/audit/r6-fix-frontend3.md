# r6-verify web 残課題の修正（第6周・フロントエンド）— 2026-09-05

## 結論
N2（交渉中/成約済みタブの追加読み込み共有）・③（AI解析ポーリングの2段階化+10分打ち切り）・L5（未読関連6箇所の limit 200化）・N3（4画面の重複排除）を全て実装した。
`npx tsc --noEmit` 0 エラー、`npx eslint src` 0 エラー（既存の warning 3件は本修正と無関係な別ファイル）。
`next build` は指示通り未実行。

## tsc・eslint 結果
- `npx tsc --noEmit`: 出力なし（0 エラー）。
- `npx eslint src`: 0 errors, 2 warnings（`notifications/page.tsx:196` unused eslint-disable、`operator/transactions/[id]/page.tsx:87` unused eslint-disable、`signup/page.tsx:59` unused var）。いずれも本修正の変更箇所と無関係な既存の warning（git diff で該当行が今回の diff に含まれないことを確認済み）。

## 変更ファイル
- `web/src/lib/katadzuke-api.ts` — `dedupeById()` を新設（id で最初の出現を残す重複排除ヘルパー）。
- `web/src/app/operator/page.tsx` — N2: `loadingMoreTxns`/`hasMoreTxns` 共有を `loadingMoreNegTxns`/`loadingMoreDoneTxns` に分離。`loadMoreTxns(kind)` は押したタブに該当する取引が1件増えるか生データが尽きるまで最大5ページ自動追跡し、`dedupeById` で結合（N3も同時に解消）。
- `web/src/app/operator/cases/page.tsx`, `web/src/app/operator/transactions/page.tsx` — N3: `loadMore` の結合を `dedupeById` 経由に変更。
- `web/src/app/cases/[id]/page.tsx` — ③: ポーリングを `setInterval` から `setTimeout` 再帰に変更。3分までは3秒間隔、以降10分まで15秒間隔（backend `_AI_STALE_PENDING_WINDOW` と一致）。10分超過で `aiPollTimedOut` を立て、「解析に時間がかかっています。ページを再読み込みしてください」+ 再読み込みボタンを表示。cleanup で `clearTimeout`（unmount 時のタイマー解除も担保）。
- `web/src/components/kdz/AppHeaderBell.tsx` — L5: `limit=LIST_MAX_LIMIT(200)`。1ページ目の非キャンセル取引が0件かつ満杯（200件）だった場合のみ2ページ目まで読む。
- `web/src/app/chat/[id]/page.tsx`, `web/src/app/operator/chat/[id]/page.tsx`, `web/src/app/notifications/page.tsx`, `web/src/app/schedule/page.tsx`, `web/src/app/mypage/withdraw/page.tsx` — L5: `listTransactions(token)` を `listTransactions(token, { limit: LIST_MAX_LIMIT, offset: 0 })` に変更。`mypage/withdraw` は表示用途のみである旨をコメントで明記（退会ガード自体は backend の COUNT が担保、監査通り変更不要と確認）。

## 未対応
なし（依頼範囲4件は全て実装済み）。`next build` の実行と、operator/page.tsx の自動追いページ（最大5ページ）による API 呼び出し増加のブラウザ実機確認は本ミッション範囲外のため未実施。

## サマリ
✅ N2・③・L5・N3 実装完了、tsc 0 エラー・eslint 0 エラー（新規 warning なし）。
