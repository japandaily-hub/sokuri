# QAレビュー: web フロント未コミット差分（依頼者/業者/運営）

対象: `git diff -- web/`（web/src/app/cases/[id]/page.tsx, web/src/app/operator/cases/[id]/page.tsx,
web/src/app/operator/operator-shared.css, web/src/lib/katadzuke-api.ts, backend/** は別作業者担当のため対象外）+
新規 `web/src/components/kdz/AppHeaderBell.tsx`。

検証コマンド: `npx tsc --noEmit -p .`（web/）→ **エラー0件（合格）**。
`npx eslint src`（web/）→ **0 errors / 4 warnings（合格。warningsは本diffと無関係の既存債務）**。
- `src/app/signup/page.tsx:59` `router` 未使用（本diffの変更行外、既存）
- `src/app/notifications/page.tsx:191`, `src/app/operator/transactions/[id]/page.tsx:92` 無効なeslint-disable（既存）
- `src/app/unsubscribe/page.tsx:21` `submitted` 未使用（既存）

「問題ゼロ」は不合格の基準に従い、以下の残存リスクを報告する。総合判定: **条件付き合格（High 2件を要修正）**。

---

## High（2件）

### H1. `/verify-email` は「偽の成功表示」の是正が未完了（文言のみ修正、実体は虚偽のまま）
- **file:line**: `web/src/app/verify-email/page.tsx:1-6`, `26-45`, `77-90`
- **再現条件**: 未ログイン・未認証の状態でも `/verify-email?email=anything@example.com` に直接アクセスするだけで到達する。ページ内に検証APIコール・`fetch`・`useEffect`によるバックエンド問い合わせは一切ない（`grep`で確認済み、ヒットは confetti 生成の `useEffect` のみ）。
- **問題**: 依頼のBlock2 ①は「verify-email/password-reset/create/complete の偽の成功表示の是正」を求めているが、`password-reset`（準備中表示へ差し替え）と`create/complete`（`/mypage`へredirect）は実体を伴う修正がされている一方、`verify-email`は文言を「メールアドレスを確認しました。」→「ご登録ありがとうございます。」に和らげただけで、「カタヅケのすべての機能がご利用いただけます」という断定は残存し、依然として実際のメール確認結果と無関係に常に成功画面を表示する。誰でもURLを叩けば「確認済み」相当の体験を見られ、①の是正意図に対して本質的に未達。
- **修正案**: このルートへの遷移をトークン検証済みの場合のみに限定する（例: 確認トークンをクエリで受け取りバックエンドの確認APIを呼び、失敗時はエラー表示 or `/login` へ誘導）。バックエンド未配線なら、`password-reset`と同様に「準備中」or「登録受付のみ（未検証)」である旨を明示し、"すべての機能がご利用いただけます"という断定表現を削除する。

### H2. `AppHeaderBell` の未読キャッシュがユーザーをまたいで漏れる（ログアウト→別アカウントログインで残存）
- **file:line**: `web/src/components/kdz/AppHeaderBell.tsx:22`（`CACHE_KEY = "kdz.headerBell.unread"`、トークン/ユーザーIDを含まない固定キー）, `:24-42`（`readCache`/`writeCache`）, `:48-54`（`useEffect`内で`token`変更時も無条件に`readCache()`を先に参照）。
- **裏付け**: `web/src/components/kdz/AppHeaderLogout.tsx:9` の `signOut({ callbackUrl: "/" })` は `sessionStorage` を一切クリアしない。`OperatorHeader.tsx`の`signOut`呼び出しも同様（`web/src/components/kdz/OperatorHeader.tsx:71,109`）。
- **再現条件**: 同一タブ・同一ブラウザセッションで (1) ユーザーAでログインし未読ありでベルにドット表示（`sessionStorage`にキャッシュ書込 `CACHE_TTL_MS=60_000`）→ (2) ログアウト → (3) 60秒以内にユーザーBでログイン。
- **問題**: `AppHeaderBell`の`useEffect`は`[token]`が変わっても、まず`readCache()`でユーザー非依存のグローバルキーを参照し、有効期限内ならAPIを叩かずそのまま`setUnread(cached)`する。ユーザーAの未読状態がユーザーBの画面に最大60秒間誤表示される（逆に本来未読があるBに「未読なし」を誤表示するケースも起きうる）。同一デバイスを複数アカウントで使う運用（同一端末でのアカウント切替）がある限り、他者の通知有無という情報が漏れる实害あり。
- **修正案**: キャッシュキーにトークンのハッシュ or ユーザーIDを含める（例: ``kdz.headerBell.unread.${tokenHash}``）。または`signOut`実行時に`sessionStorage.removeItem(CACHE_KEY)`（該当キー全消去）を呼ぶ。両対応が望ましい。

---

## Medium（3件）

### M1. `operator/page.tsx` / `operator/cases/page.tsx`: `getOperatorProfile` 失敗時に "unknown" へフォールバックし、入札可否がフェイルオープンする
- **file:line**: `web/src/app/operator/page.tsx:315-317`（`statusLoading` / `awaitingApproval` / `canBid = !statusLoading && (vendorStatus === "active" || vendorStatus === "unknown")`）, `web/src/app/operator/cases/page.tsx:135-136`
- **再現条件**: `getOperatorProfile(token)` がネットワークエラー・5xx等で失敗（`.catch(() => setVendorStatus("unknown"))`）。
- **問題**: プロフィール取得に失敗した業者は`canBid`が`true`になり、未承認(`pending`)業者でも入札フォームが表示されうる（フロント側のガードのみで見た場合）。要求(a)の「取得失敗時に入札できなくなる回帰」は無い（フェイルクローズではない）ことは確認できたが、逆にフェイルオープンでガード自体が無力化するケースがある。バックエンドの`createBid`が`vendor_status`を最終的に検証していれば実害は限定的だが、当該バックエンドAPI（`backend/app/api/v1/endpoints/bids.py`）は本レビュー対象外のため実装未確認。[推測] バックエンドが同等のサーバー側検証をしていない場合、フロントのみの防御は突破可能。
- **修正案**: バックエンド側で`vendor_status !== "active"`の場合に`createBid`を403で拒否することを別レビューで確認・保証する。フロント側は最低限、プロフィール取得失敗時は`canBid=false`（フェイルクローズ）にし、代わりに「状態を確認できません。再読み込みしてください」等のリトライ導線を出す方が安全側に倒せる。

### M2. 管理画面の業者一覧: ステータス件数バッジが検索語でフィルタされず、「0件」表示と数値が矛盾しうる
- **file:line**: `web/src/app/admin/page.tsx:403`（`operatorStatusCounts[s]`は検索前の総数）, `:471-473`（`filteredOperators.length === 0` → "該当業者はいません。"）
- **再現条件**: 例えば `pending` ステータスの業者が3件存在する状態で、フィルタを`pending`に切替え、検索欄に一致しない文字列を入力する。
- **問題**: バッジは「pending 3」を表示したまま、リストは「該当業者はいません。」（空状態メッセージ自体は実装済みで確認できた＝当初懸念していた「空リストで無表示」という重大なリスクは無し）。ただしバッジの数字と直下の空状態文言が矛盾して見え、運営担当者が「検索が壊れているのでは」と誤解する可能性がある。
- **修正案**: バッジを「総数」ではなく現在の検索条件を反映した件数にする、または検索中は「検索結果 N件（全M件）」のような補助表示を追加する。

### M3. `admin/page.tsx` 業者承認ボタンの `disabled` 条件が「許可証未提出」時のみ承認をブロックし、`busy`中の視覚的ちらつきに注意が必要
- **file:line**: `web/src/app/admin/page.tsx:456,461-465`
- **問題（軽微だが確認事項として記載）**: `disabled={busy || (op.vendor_status !== "active" && !op.has_license_image)}` は承認ボタンを止めるが、`toggleVerify`自体は`if (!token || busy) return;`で二重送信ガード済み（`admin/page.tsx:195`）であり、実害は無い。ただし`handleVerifyClick`（`:207-215`）は`window.confirm`をボタンの`disabled`判定より先に評価するため、`disabled`状態でクリックイベントがそもそも発火しないブラウザ標準動作に依存している。React合成イベントでも`disabled`要素は`onClick`が発火しないため実質安全だが、将来ボタンを`<div role=button>`等に置換すると同ガードが失われるリスクがある点のみ留意。
- **修正案**: 現状のままで機能上の問題はない。将来のリファクタで要素をbutton以外に変更する場合は`handleVerifyClick`冒頭に`if (busy) return;`を明示的に追加すること。

---

## Low（4件）

### L1. `/create` STEP1: `currentItem` が undefined のとき、次へボタンは disabled のまま理由表示が出ない
- **file:line**: `web/src/app/create/page.tsx:104-105`（`currentItem`導出）, `:712-720`（新設のエラーメッセージ分岐）
- **再現条件**: `mode.itemId`が`items`配列中に存在しない状態（撮影対象アイテムが削除された直後など）で`step===0 && mode.kind==="shoot"`に居続けた場合。
- **問題**: ボタンの`disabled`条件は`!currentItem || ...`で`currentItem`未定義でも真になるが、新設の案内メッセージは`currentItem && ...`を前提にした2分岐のみで、`currentItem`が`undefined`のケースは`null`（無表示）に落ちる。ユーザーは「なぜ進めないか」が分からないまま操作不能になる。
- **修正案**: `currentItem`が`undefined`の場合の第3分岐（例:「対象の商品が見つかりません。前の画面からやり直してください」）を追加する。

### L2. `web/src/app/create/complete/complete.css` が孤立（未import）のまま残存
- **file:line**: `web/src/app/create/complete/page.tsx:1-11`（`"use client"`・`import "./complete.css"`とも削除済み。CSSファイル自体は未削除）
- **問題**: 機能上の実害はないが、デッドコード。次回クリーンアップで削除対象。

### L3. `AppHeaderBell` は直近5件の非キャンセル成約のみ未読判定（`MAX_CHECK=5`）
- **file:line**: `web/src/components/kdz/AppHeaderBell.tsx:19,60`
- **問題**: コメントで意図的な制限と明記されているが、6件目以降の成約に未読メッセージがある場合はドットが出ない。件数が多いヘビーユーザーで見落としが起きうる仕様上の限界。
- **修正案**: 可能ならバックエンドに「未読合計」を返す軽量エンドポイントを用意し、N+1の`getTransaction`ループを廃止するのが本質的な解決。当面は許容範囲として記録のみ。

### L4. 入札額入力: `parseInt`による小数切り捨てで非整数入力が意図せず通過する
- **file:line**: `web/src/app/operator/page.tsx:246-253`（実ファイル行は変動するため diff 内 `parseInt(draft, 10)` 周辺を参照。バリデーションは `val % BID_STEP !== 0` でstep外れは弾くが、`"1000.9"`のように小数第1位以下を持つ入力は`parseInt`で`1000`に切り捨てられ数値としては有効扱いになる）
- **問題**: 実害（不正な金額が送信される）はない（送信値は常に有効な整数）が、ユーザーが入力した値と実際に送信される値が無言で異なる（打鍵ミスに気づけない）。
- **修正案**: `Number(draft)`で小数点の有無を判定し、`Number.isInteger(Number(draft))`でない場合も`validationError`を出す。

---

## 隣接・複製伝播チェック（見落とし確認）
- `AppHeader unread` prop 呼び出し元は `mypage/page.tsx`, `mypage/profile/page.tsx`, `mypage/withdraw/page.tsx`, `notifications/page.tsx`, `review/page.tsx`, `schedule/page.tsx`, `vendors/[id]/page.tsx` の全7ファイルで確認し、いずれも`unread`プロップ渡しを削除済み（`AppHeaderBell`への統一が一貫している）。見落としなし。
- LINE通知文言の統一（メール既定・LINEは連携時のみ）は `chat/[id]/page.tsx`, `mypage/page.tsx`, `schedule/page.tsx` の3箇所で確認、表現も概ね統一（「メールでお知らせします。LINE連携済みの場合はLINEにも届きます。」）。表記ゆれなし。
- `OperatorHeader`のモバイルメニュー内ログアウト追加は`OperatorHeader.tsx`のみで、`operator/chat/[id]/page.tsx`のヘッダーは別実装（自前ヘッダー）のため個別にログアウトボタンを追加しており（`:809-815`）、両方確認済みで漏れなし。

## まとめ
- 依頼(a) ちらつき: 未検出（`statusLoading`ゲートで初期null描画、フリッカーなし）。ただし取得失敗時のフェイルオープン(M1)は別リスクとして残る。
- 依頼(b) 件数整合: バッジと空状態文言が矛盾しうる(M2)。重大な不整合（全件非表示等）はなし。
- 依頼(c) AppHeaderBellのキャッシュ: **バグを検出（H2）**。ユーザー間で未読状態が漏れる。
- 依頼(d) create/complete のredirect: 正しく実装、"use client"・css importとも残存なし（問題なし）。
- 依頼(e) signupのwarnバナー: `role === "buyer"`のみで発火、buyer以外では出ない（問題なし）。
- 依頼(f) 文言統一: 概ね統一済み、verify-emailのみ実体面の是正が不足(H1)。
- 依頼(g) tsc/eslint: tsc 0エラー、eslint 0エラー/4警告（本diffと無関係の既存債務）。
