# frontend・P3 実装報告（評価の2択化＋ワンタップ入力）

担当: frontend（DESIGN.md の (2) web の型・(4) frontend・P3・(5)・(6) E2E 04 / web 検証）

## 結論（3行）
- DESIGN.md (5) の共通部品 `ReviewComposer`＋`review-verdict.ts` を新設し、入力3画面（/review・/cases/[id]・/operator/transactions/[id]）と表示4画面（入札一覧・/vendors・/vendors/[id]・/operator/profile）を good/improve の2択＋ワンタップ候補文へ置き換えた。
- `web` の型（katadzuke-api.ts）から `rating` を全廃し `verdict`/`good_count`/`improve_count` に統一。星・タグ関連の CSS（review.css・vendors.css・vendor.css・profile.css・operator-shared.css）を削除した。
- 検証4種（単体テスト・tsc・lint・next build）はすべて緑。E2E 04 は新フローに書き換えたが実行はしていない（backend 未反映の P3 段階のため、DESIGN.md の運用ルールどおり）。

## 検証コマンドごとの結果
- `node --test src/lib/review-verdict.test.mts src/lib/safe-path.test.mts` → **成功**（tests 50, pass 50, fail 0。既存 safe-path.test.mts も無傷）。
- `npx tsc --noEmit` → **成功**（エラー0件）。
- `npm run lint` → **成功**（エラー・警告0件）。
- `npx next build` → **成功**（57/57 ページ生成。`.next/static/css/*.css` に `kdz-review-composer__*` と `:has(:checked)` セレクタの残存を確認済み＝ `@import layer()` を使わず CSS が正しく処理されていることを確認）。
- E2E 04 (`04-schedule-reduction-complete.spec.ts`) は backend が P2 未反映のためこのセッションでは**未実行**（DESIGN.md の3段階反映ルールに従う）。

## 変更ファイル一覧
新規:
- `web/src/lib/review-verdict.ts`（純関数＋候補文の唯一の置き場所）
- `web/src/lib/review-verdict.test.mts`（safe-path.test.mts と同方式の node --test）
- `web/src/components/kdz/ReviewComposer.tsx`
- `web/src/components/kdz/review-composer.css`

編集:
- `web/src/lib/katadzuke-api.ts`（`ReviewVerdict` 型追加／全型から `rating` 削除／`good_count`・`improve_count` 追加／`createReview` payload を `verdict` に変更）
- `web/src/app/review/page.tsx` / `review.css`
- `web/src/app/cases/[id]/page.tsx`（入札一覧の評価表示・インライン評価フォームの両方）
- `web/src/app/operator/transactions/[id]/page.tsx`
- `web/src/app/operator/operator-shared.css`（`.review-stars-input` 削除。DESIGN.md (4) の該当行注記どおり）
- `web/src/app/vendors/page.tsx` / `vendors.css`
- `web/src/app/vendors/[id]/page.tsx` / `vendor.css`
- `web/src/app/operator/profile/page.tsx` / `profile.css`
- `web/e2e/04-schedule-reduction-complete.spec.ts`
- `web/e2e/helpers/api.ts`（下記「設計から逸れた点」参照）

## 設計から逸れた点・補足（理由つき）
1. **`web/e2e/helpers/api.ts` を追加で編集**（DESIGN.md (4) の一覧に明記なし）。この E2E 専用の `TransactionDetail` 型に `reviews` フィールドが無く、(6) が要求する「API で reviews[].verdict === "good"」を型安全に検証できなかったため、`reviews: { id; reviewer_type; verdict; comment }[]` を追加した。backend は元々 `reviews` を返しており、型の後追い追加のみで実行時の挙動は変えていない。
2. `operator/transactions/[id]` の投稿済み文言を「レビュー投稿済み（★N）」→「**評価**投稿済み（よかった）」に変更した（「レビュー」→「評価」）。DESIGN.md の例示文言「評価投稿済み（よかった）」に3画面とも合わせるための整合であり、見出し「ユーザーを評価する」等の保護対象には含めていない。
3. 送信不可時の `aria-describedby` 文言「評価を選択すると送信できます」は DESIGN.md に文言指定が無いため **[推測]** で補った。
4. `vendors/page.tsx` の静的説明文「評価（成約したユーザーの5段階評価と口コミ件数）」は2択化後は事実と異なるため「『よかった／伸びしろ』の件数と口コミ」に更新した（同ファイル内・スコープ内の追随修正）。
5. `.rating-num`（vendor.css 28px→18px）・`.rating-summary-num`（profile.css 22px→16px）はフォントサイズを縮小した。従来は「4.2」等の短い数値表示用だったため、「よかった 3・伸びしろ 1」という長めの文字列に合わせた調整（[推測]、指定なし）。
6. `.rating-bars`／`.rating-bar-*`／`.biz-stats`／`.promise-list`（vendor.css）は現行 JSX から既に参照されていない既存デッドコードだが、本タスクの範囲外のため未着手（対象外の確認のみ実施）。

## 375px 幅で気になる点
- ReviewComposer の評価選択肢（`.kdz-review-composer__option`）は480px以下で `flex:1 1 100%` にして縦積みにしたが、実機での折り返し・タップ領域は未確認（ブラウザ確認はリーダー側で実施予定）。
- `/vendors/[id]` のヒーロー評価行（`.biz-rating-row`）は「よかった 3・伸びしろ 1」＋「（口コミ4件）」が並ぶため、375px では2行に折り返る可能性がある（`flex-wrap` 済みでレイアウト崩れはしない想定）。
- to_operator 方向のみ出る公開注意文（コメント欄下）は3〜4行になり、フォーム全体が縦に伸びる。文言短縮の要否はリーダー判断待ち。

## 未解決
- backend（P2）未反映のため、実際の API 応答（`good_count`/`improve_count`/`verdict`）を使った実機・E2E 実行での確認はできていない。P2 反映後に E2E 04 の実行を推奨。
- ブラウザでの a11y 実機確認（`:has()` 未対応環境でのフォールバック見え方、スクリーンリーダーでの読み上げ順）は未実施。

---

## 追記: 実機検証・security/QA レビュー対応（Critical/High 0件・以下修正済み）

0. review-composer.css の `.kdz-review-composer__option-input`（枠全体に透明重ね＋z-index方式）は**リーダー修正済みのまま維持**。触っていない。
1. **[Medium]** `review/page.tsx`: `submittedVerdict` state を追加し、`createReview` 成功直後に送信した verdict を保持。表示は `myReview?.verdict ?? submittedVerdict` に変更し、reload 完了前（失敗時含む）でも「評価投稿済み（）」の空括弧が出ないようにした。`cases/[id]`・`operator/transactions/[id]` は `myReview`（reload 後の txn.reviews 由来）のみで表示を切り替えており、reload 前に先出しする状態を持たないため同型の不具合が無いことをコード確認済み（修正不要）。
2. **[Low]** `ReviewComposer.tsx`: radio の `aria-describedby={hintId}` を削除。補助文 span は label 内で既にアクセシブルネームに含まれるため重複読み上げを解消。参照されなくなった `hintId` 変数・`id` 属性も削除。
3. **[実機で発見]** `cases/[id]/page.tsx` の入札一覧: `formatVerdictCounts()` の出力を `inline-block + whitespace-nowrap` の内側 span で包み、単語途中の折り返し（CJK は既定でどの文字間でも折り返せるため）を防止。同じリスクが `/vendors`（`.vendor-rating-value` を新設）・`/operator/profile`（`.rating-summary-num` に `white-space:nowrap`）・`/vendors/[id]`（`.rating-num` に同様）にもあったため横展開して修正。
4. **[Low]** `review-composer.css`: `#fff` を4箇所すべて `var(--white)`（katazuke.css で `#fff` と定義済みのトークン、実在確認済み）に置換。placeholder の `#bcc3d4` は指示どおり据え置き。
5. `review-verdict.test.mts` に8件追加（計25テスト）: 候補文が2回含まれる場合の removePhrase の単発性、末尾「！」削除後の再タップ＝全文重複追記（現状仕様の固定）、利用者自身の無関係な半角スペースの保持、候補文直前に利用者が偶然同じ形の半角スペースを打っていた場合にそのスペースごと消える仕様の固定、末尾が全角スペースの場合の appendPhrase、canAppend の空文字＋300字ちょうど／301字の境界。全て緑。
6. `web/e2e/04-schedule-reduction-complete.spec.ts` を拡張: 完了確定直後に `/cases/{case_id}` のインライン評価フォームで「評価を投稿する」ボタンが評価未選択の間 disabled であることを確認（投稿はしない＝取引を追加消費しない）→ 既存どおり `/review` で依頼者評価を投稿・API 確認 → 新規 `browser.newContext()` を作り `loginAsOperator(ACCOUNTS.vendor)` で `/operator/transactions/{id}` に入り、radio「よかった」→ チップ「事前の写真と説明が正確で助かりました！」→「レビューを投稿」→「評価投稿済み（よかった）」を確認 → API で `reviewer_type==="operator"` の `verdict==="good"` を確認。`helpers/api.ts` の `TransactionDetail.reviews` 型を利用（前回追記済み）。実行は backend P2 未反映のためこのセッションでは未実施。

### 検証コマンド結果（今回分）
- `node --test src/lib/review-verdict.test.mts` → 成功（tests 25, pass 25, fail 0）
- `npx tsc --noEmit` → 成功（エラー0件）
- `npm run lint` → 成功（エラー・警告0件）
- `npx next build` は今回未実行（リーダーが後で実施）

### 未解決（追記分）
- E2E 04（拡張版）は backend P2 未反映のため未実行。P2 反映後、デスクトップ・スマホ双方での実行を推奨。
- next build による本番 CSS 出力（`var(--white)` 置換後・nowrap 追加後）の再確認はリーダー側で実施予定。

---

## 追記2: QA再レビュー差分（Critical/High/Medium 0件）対応 — Low テスト補強のみ

作業場所: `C:\Users\ko13h\Claude\Projects\ソクウリ\.claude\worktrees\review-verdict\web`（リーダー用隔離 worktree。以後の実装ファイル本体はここに既に反映済みで、今回は `src/lib/review-verdict.test.mts` のみ編集）。

1. 「候補文どうしが部分文字列にならない」不変条件を、direction ごとに good/improve を `[...good, ...improve]` でまとめた全ペア判定に変更（従来は verdict ごとに別々のチェックだった）。理由: 評価を切り替えてもコメント本文は消えない仕様のため、good 側の文が improve 側の部分文字列（またはその逆）だと `hasPhrase` によるチップ選択判定を誤らせるため。手動確認・テスト実行の両方で to_operator/to_user とも現行の候補文に該当する重なりは無いことを確認。未使用になった `VERDICTS` 定数と `ReviewVerdict` 型 import は削除。
2. `appendPhrase` の文末判定に未テストだった全角「？」・半角「?」で終わる本文への追記（区切りスペースを入れない）を2件追加。

### 検証コマンド結果
- `node --test src/lib/review-verdict.test.mts` → 成功（tests 25, pass 25, fail 0）
- `npx tsc --noEmit` → 成功（エラー0件）

---

## 追記3: セキュリティ差分レビュー予防対応（transaction_id 切替時の状態残留）

`web/src/app/review/page.tsx`: `ReviewPageInner` は `busy`/`justSubmitted`/`submittedVerdict` 等を内部 state で持つため、同一ページ内でクライアント側遷移により `transaction_id` だけが変わった場合、key が無いとインスタンスが使い回され前の取引の送信済み状態が新しい取引側に残り得る（例: A を送信済み→B（未送信）に遷移しても「送信済み」表示が残る等）。
対応: `useSearchParams` を呼ぶ薄いラッパー `ReviewPageKeyed` を新設し、`<ReviewPageInner key={transactionId ?? ""} />` で transaction_id ごとに強制再マウントするようにした。`ReviewPageInner` 自身が呼ぶ `useSearchParams` はそのまま維持（重複呼び出しになるが副作用なし）、Suspense 構造（`<Suspense><ReviewPageKeyed /></Suspense>`）も維持。

### 検証コマンド結果（worktree: `.claude\worktrees\review-verdict\web`）
- `npx tsc --noEmit` → 成功（エラー0件）
- `npm run lint` → 成功（エラー・警告0件）
- `node --test src/lib/review-verdict.test.mts src/lib/safe-path.test.mts` → 成功（tests 57, pass 57, fail 0）

✅達成
