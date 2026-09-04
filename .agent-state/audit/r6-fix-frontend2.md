# r6 High-1 修正（web ページング追随）— 2026-09-05

r6-review.md の High 1（`GET /cases`/`GET /transactions` の backend limit 既定100に web が追随せず101件目以降が不可視）を修正した。`listOpenCases`/`listTransactions` に `{limit, offset}` を通し、業者の案件一覧（/operator/cases・/operator）と取引一覧（/operator/transactions・/operator の交渉中/成約済みタブ）に既定100件・「さらに読み込む」（読込中disabled・終端で非表示）を実装した。依頼者の `/mypage` は取引を一覧表示せず集計にのみ使うため、上限200件でページングし切り終端まで全件取得して集計の過小計上を防いだ（UIボタンでなく内部ループ）。依頼者の自分の案件一覧（listMyCases）は backend が limit を適用しない仕様（cases.py:list_cases）を確認済みのため未変更。

## tsc・eslint 結果

- `npx tsc --noEmit`: エラー 0
- `npx eslint src`: エラー 0 / warning 3（notifications/page.tsx:195・operator/transactions/[id]/page.tsx:87 の未使用 eslint-disable、signup/page.tsx:59 の未使用 router。いずれも本差分と無関係な既存分＝r6-review.md 記載のものと同一）

## 変更ファイル

- web/src/lib/katadzuke-api.ts（`ListPageParams`/`LIST_DEFAULT_LIMIT=100`/`LIST_MAX_LIMIT=200` 追加、listOpenCases/listTransactions に反映）
- web/src/app/operator/cases/page.tsx（さらに読み込む＋絞り込みは読込済み範囲が対象である旨の注記）
- web/src/app/operator/page.tsx（案件一覧タブ・交渉中/成約済みタブそれぞれに さらに読み込む）
- web/src/app/operator/transactions/page.tsx（さらに読み込む）
- web/src/app/mypage/page.tsx（transactions を上限200件で終端までページングし集計に使用）

## 未対応（本ミッション範囲外・r6-review 記載の既存箇所）

- chat/[id]・operator/chat/[id]・notifications・schedule・mypage/withdraw・AppHeaderBell（未読ベル）は依然 limit 未指定（既定100）のまま。Block2 指定の対象（業者案件/取引一覧・依頼者取引タブ）には含まれていないため今回は変更していない。101件超の成約がある場合、未読バッジ・通知一覧・スケジュール一覧が過小になる余地は残る。

## サマリー

✅ 対象4画面（operator/cases・operator・operator/transactions・mypage集計）で101件目以降の不可視化を解消
✅ tsc 0 / eslint 0 errors
⚠️ chat/notifications/schedule/AppHeaderBell 等の周辺箇所は未対応（範囲外・既知）
