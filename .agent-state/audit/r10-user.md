# 依頼者導線 QA監査台帳（第10周・r10-user・2026-09-05）

対象: 初回利用者が LP → 出品 → 入札 → 選定 → 成約 → 日程 → 完了 → 評価 → 次の出品 まで迷わず進めるか。
除外: `docs/TODO.md` 03（既知・意図的未対応）と 01（ユーザー確認待ちの仮定）。過去台帳 r3〜r9 の是正項目は回帰確認のみ。
編集は本ファイルのみ（読み取り専用監査）。

## 結論

- **エリアの入口と出口が一致していない**（対応4都県に対し登録画面は8択）。初回利用者は登録を完了してから出品段階で詰まる。
- **スマホでギャラリー写真を選べない**（`capture="environment"`）。写真が主データの製品で、事前に撮った写真を持つ利用者が最初のSTEPで止まる。
- 成約以降の導線は繋がっている。残りは**用語の揺れ・集計の意味・disabled の理由非表示**という「分かりにくい」層。

---

## High

### R10-H1. 対応エリア外（大阪・愛知・福岡・その他）のまま登録が完了でき、出品STEP3で初めて選べないと分かる

- 画面: `/signup` STEP2 → `/create` STEP3
- 事象: `/signup` の「お住まいのエリア」は**必須**（`web/src/app/signup/page.tsx:204`、`:98`）で、選択肢に大阪府・愛知県・福岡県・その他を含む8件を提示する（`web/src/app/signup/page.tsx:17-26`）。一方、実サービスの対応エリアは東京・千葉・埼玉・神奈川の4都県で（`web/src/app/business/page.tsx:79`、`web/src/app/faq/page.tsx:123`、`web/src/app/legal/page.tsx:97`）、出品の都道府県セレクトも4件しかない（`web/src/app/create/page.tsx:25`）。LP（`web/src/app/page.tsx`）には対応エリアの記載が無い。
- 根拠: `web/src/app/signup/page.tsx:17-26` / `web/src/app/create/page.tsx:25` / `web/src/app/business/page.tsx:79`
- 再現: 未ログインで LP →「LINEではじめる」（`web/src/app/page.tsx:85`）→ /login → 新規登録 → STEP2 で「大阪府」を選択 → 登録完了 →「さっそく出品してみる」→ /create STEP3 の都道府県に大阪府が無い。既定値が「東京都」（`create/page.tsx:113`）のため、気づかず誤ったエリアで出品しうる。
- 修正案: `AREAS` を対応4都県＋「その他（対応エリア外）」に絞り、その他を選んだ時点で「現在の対応エリアは1都3県です」と明示して待機リスト等へ分岐する。あわせて LP・/signup STEP1 に対応エリアを1行表示する。

### R10-H2. `capture="environment"` によりスマホでは既存の写真を選べず、ラベルの「選択」が成立しない

- 画面: `/create` STEP1（アルバム撮影・まとめ撮影の両方）
- 事象: ファイル入力に `capture="environment"` を付けている（`web/src/app/create/page.tsx:578`、`:664`）。Android Chrome / iOS Safari はこの属性を尊重してカメラを直接起動するため、カメラロールからの選択ができない。しかしラベルは「写真を撮影・選択」（`web/src/app/create/page.tsx:574`、`:660`）で選択可能と案内し、`/photo-guide` は「床・机に並べて全体写真を撮る」等、**事前撮影**を前提にした手順書になっている（`web/src/app/photo-guide/page.tsx:30-31`）。
- 根拠: `web/src/app/create/page.tsx:578` / `web/src/app/create/page.tsx:664` / `web/src/app/create/page.tsx:574`
- 再現: スマホで /create STEP1 →「写真を撮影・選択」をタップ → カメラが直接起動し、ギャラリー選択の選択肢が出ない。撮影ガイドを読んで先に撮っておいた利用者はここで手が止まる。
- 修正案: `capture` を外す（既定の「カメラで撮影／ライブラリから選択」ダイアログに戻す）。撮影を促したい場合は `capture` 付きの「今すぐ撮る」ボタンと、無しの「写真を選ぶ」ボタンを併置する。

### R10-H3. 登録STEP2で必須入力させた「エリア」「利用目的」が送信されず破棄される（説明と実装の不一致）

- 画面: `/signup` STEP2・STEP3
- 事象: STEP2 の説明は「あなたのエリアと利用目的を教えてください。適切な業者をマッチングするために使用します。」（`web/src/app/signup/page.tsx:195`）で、両項目とも必須（`:204`、`:218`、検証は `:95-101`）。だが送信は `signupUser({ email, password, name })` のみで、area/role は破棄される（`web/src/app/signup/page.tsx:112` とその直前のコメント `:111`）。確認画面（`:264-265`）には登録内容として表示されるため、利用者は保存されたと誤認する。
- 根拠: `web/src/app/signup/page.tsx:111-112` / `web/src/app/signup/page.tsx:195`
- 再現: 登録後に `/mypage/profile` を開いても、登録時に選んだエリアはどこにも反映されていない（住所は改めて入力し直しになる）。
- 修正案: (a) backend の signup にプロフィール初期値として渡し `/create` STEP3 の都道府県既定値に使う、または (b) 必須を解除して「マッチングに使用します」の文言を削除する。どちらかに寄せ、確認画面の表示も実態に合わせる。

---

## Medium

### R10-M1. 取り下げ済み案内が横並び flex の中に置かれ、375px で細い1列に潰れる

- 画面: `/cases/[id]`（status=cancelled）
- 事象: 案内ブロックが `flex items-start justify-between` の行（`web/src/app/cases/[id]/page.tsx:423`）の3番目の子として置かれ、`w-full` を当てている（`:438`）。flex 行の子なので `w-full` は効かず、タイトル塊とステータスバッジに挟まれて縮む。取り下げ後に最も読ませたい「入札はすべて自動でお断りになりました／再度出品してください」が読みづらい。
- 根拠: `web/src/app/cases/[id]/page.tsx:423` / `web/src/app/cases/[id]/page.tsx:437-444`
- 再現: 出品を取り下げた案件の詳細を 375px で開く。
- 修正案: 案内ブロックを `:423` の flex 行の外（`</div>` の直後）へ移す。

### R10-M2. 同じ金額に4つの呼び名が付いていて、依頼者が別々の金額だと誤解する

- 画面: `/cases/[id]` → `/chat/[id]` → `/schedule` → `/mypage`
- 事象: 成約金額の表示ラベルが画面ごとに異なる。「落札額」（`web/src/app/cases/[id]/page.tsx:787`）／「成約額」（`web/src/app/chat/[id]/page.tsx:364`）／「成約買取額」（`web/src/app/schedule/page.tsx:343`）／「買取額」（`web/src/app/schedule/page.tsx:482`）／「総買取額」（`web/src/app/mypage/page.tsx:328`）。さらに `/cases/[id]` の同じカード内で見出しは「成約:」（`:783-784`）なのに金額だけ「落札額」で、業者側の表記統一（TODO 完了欄「落札管理→取引」）が依頼者側に及んでいない。
- 根拠: `web/src/app/cases/[id]/page.tsx:787` / `web/src/app/chat/[id]/page.tsx:364` / `web/src/app/schedule/page.tsx:343,482`
- 再現: 成約→チャット→日程調整と辿ると、同一金額が3画面で3つの名前で出る。
- 修正案: 依頼者向けは「成約額」（減額後は「確定額」）に統一し、「落札」は依頼者画面から排除する。

### R10-M3. 同じ行為が「出品」と「依頼」の2語で案内され、空状態のCTAですら不一致

- 画面: `/mypage` ↔ `/cases` ↔ `/create`
- 事象: `/mypage` の空状態CTAは「出品をはじめる」（`web/src/app/mypage/page.tsx:155`）、サマリーは「次の出品／出品する」（`:360,365`）。同じ一覧である `/cases` は見出し「マイ案件」・CTA「新しく依頼する」（`web/src/app/cases/page.tsx:52,56`）・空状態「最初の依頼をつくる」（`:65`）。`/create` は見出し「この内容で出品します」（`web/src/app/create/page.tsx:790` 付近の step-desc）に対し送信ボタンは「この内容で依頼する」（`:890`）。
- 根拠: `web/src/app/mypage/page.tsx:155` / `web/src/app/cases/page.tsx:56,65` / `web/src/app/create/page.tsx:890`
- 再現: マイページ→マイ案件と移動すると、同じ操作を指す一次CTAの語が変わる。
- 修正案: 依頼者向けの一次動詞を「出品」に統一（案件＝出品した1件、依頼＝業者への行為、として使い分けを定義）。`/cases` の3箇所と `/create` の送信ボタンを合わせる。

### R10-M4. マイページのサマリー3枚が全て絞り込みなしの同一 `/cases` へ飛び、押した数字の中身に辿り着けない

- 画面: `/mypage` → `/cases`
- 事象: 「入札受付中」「交渉中」「成約済み」の3カードが全て `href="/cases"`（`web/src/app/mypage/page.tsx:335,343,351`）。`/cases` にはタブもフィルタも無く全件を並べるだけ（`web/src/app/cases/page.tsx:69-` の単一 grid）。「交渉中 2件」を押しても、どの2件かは分からない。
- 根拠: `web/src/app/mypage/page.tsx:335,343,351` / `web/src/app/cases/page.tsx:69`
- 再現: 案件が3件以上ある状態でサマリーカードを押す。
- 修正案: 同一ページ内のタブ（`/mypage` に既にある「すべて/進行中/成約・終了」）へアンカーで飛ばすか、`/cases?status=` を受けて絞り込む。

### R10-M5. 「入札受付中」の集計が「入札が1件以上ある案件数」で、同じ画面のステータスチップと矛盾する

- 画面: `/mypage`
- 事象: サマリー「入札受付中」の母数は `isBiddingCase`＝`(open|bidding) かつ bid_count>0`（`web/src/app/mypage/page.tsx:56-57`、集計 `:217-220`）。一方、案件カードのチップは `status==="open"` をそのまま「入札受付中」と表示する（`:63`）。結果、出品直後（入札0件）の利用者は、カードに「入札受付中」と出ているのにサマリーは「入札受付中 0件」となる。補助文も「入札が届いています」（`:341`）で、ラベルと中身がずれている。
- 根拠: `web/src/app/mypage/page.tsx:56-57` / `web/src/app/mypage/page.tsx:63` / `web/src/app/mypage/page.tsx:336,341`
- 再現: 出品1件・入札0件の状態でマイページを開く。
- 修正案: サマリーのラベルを「入札あり」に変更する（チップ側の語と入れ替える）か、母数を `bid_count>0` 条件なしにして補助文を「うち入札あり N件」にする。

### R10-M6. 出品STEP3で必須の市区町村が空だと「次へ」が無言で押せない（理由表示なし）

- 画面: `/create` STEP3
- 事象: `canNext()` は step===2 で `city.trim().length > 0` を要求する（`web/src/app/create/page.tsx:364-368`）が、フッターの「次へ」は `disabled={!canNext()}` にするだけで理由を出さない（`:882`）。ラベル横の「必須」バッジ（`:755`）以外に手がかりが無い。同じ画面群の STEP1 撮影モードには「写真を1枚以上追加してください」等のインライン理由表示がある（`:906-913`）ため、実装内でも扱いが不揃い。
- 根拠: `web/src/app/create/page.tsx:364-368` / `web/src/app/create/page.tsx:882` / `web/src/app/create/page.tsx:906-913`
- 再現: 375px で STEP3 に進み、市区町村を空のまま画面下の「次へ」を押す（固定フッターは常時表示のため、入力欄まで戻る動機が生まれない）。
- 修正案: STEP1 と同じ形式で、フッター下に「市区町村を入力してください」を `role="status"` で出す。

### R10-M7. 案件詳細で評価を投稿し終わると導線が途切れる（次の出品への誘導が無い）

- 画面: `/cases/[id]`（status=completed・投稿後）
- 事象: 投稿後は成功メッセージのみで、次の行動が「← マイ案件一覧へ」（`web/src/app/cases/[id]/page.tsx:1049-1051`）しか無い（`:992-995`）。同じ評価を `/review` から出した場合は「次のアクション」に `/create` への導線がある（`web/src/app/review/page.tsx:338`）ため、主導線（案件詳細内のインラインフォーム）だけが行き止まりになっている。
- 根拠: `web/src/app/cases/[id]/page.tsx:992-995` / `web/src/app/review/page.tsx:338`
- 再現: 案件詳細のインラインフォームから★を投稿する。
- 修正案: 投稿済み Notice の直下に「新しく出品する」ボタン（`/create`）を置く。

### R10-M8. 取り下げ・キャンセルで `window.prompt` → 自前モーダルの二段になり、しかも prompt の扱いが2箇所で非対称

- 画面: `/cases/[id]`
- 事象: 出品取り下げは `window.prompt("取り下げ理由（任意）")` を出してからブランドモーダルを開く（`web/src/app/cases/[id]/page.tsx:753-765`）。取引キャンセルも同様（`:966-977`）。前者は prompt で「キャンセル」を押すと処理を中止する（`:754`）が、後者は `?? null` で握りつぶしてそのまま確認モーダルへ進む（`:966`）ため、prompt を閉じたつもりの利用者に次のダイアログが出る。iOS Safari の「このページでの追加ダイアログを表示しない」を選ぶと prompt 以降が進まなくなる点も残る。
  ※ TODO 03 の「window.confirm のまま」は `confirm` を指しており、r8 で `confirm` は ConfirmModal 化済み。ここで指摘するのは残存した `prompt` と、その分岐の非対称。
- 根拠: `web/src/app/cases/[id]/page.tsx:753-754` / `web/src/app/cases/[id]/page.tsx:966`
- 再現: 取引キャンセルを押し、理由の prompt で「キャンセル」を選ぶ → 確認モーダルが開く。
- 修正案: 理由入力を ConfirmModal 内のテキストエリアに統合する（業者側・運営側と同じ形）。少なくとも `:966` を `:754` と同じく null で中止に揃える。

### R10-M9. 出品送信中に 401／停止403 が起きると、撮影済みの写真と入力が無警告で全消失する

- 画面: `/create`
- 事象: 401（および 403 `account_suspended`）は共通処理で `signOut` 後に `window.location.href` で強制遷移する（`web/src/lib/katadzuke-api.ts:693-707`）。`beforeunload` の標準ダイアログで「留まる」を選んでも、既に token が消えているため `/create` の未ログインガード `router.replace("/login?callbackUrl=%2Fcreate")`（`web/src/app/create/page.tsx:93-95`）が走る。`router.replace` は `beforeunload` も popstate ガード（`:186-201`）も通らないため、離脱確認モーダルは出ない。再ログイン後の `/create` は空。
- 根拠: `web/src/lib/katadzuke-api.ts:693-707` / `web/src/app/create/page.tsx:93-95`
- 再現: 写真を数枚追加した状態で運営がそのアカウントを停止する（または token 失効）→ STEP4 の送信で 403/401 → 何の説明もなくログイン画面。
- 修正案: `uploadCasePhoto` / `createCase` の呼び出しに `skipAuthRedirect` を渡し、`/create` 内では画面遷移せずインラインで「セッションが切れました。別タブでログインし直してからもう一度送信してください」と出す（写真の state を保持する）。

---

## 通しで追った結果（STEPごと）

| # | STEP | 判定 | 備考 |
|---|---|---|---|
| 1 | LP → 出品CTA | ⚠️ 分かりにくい | CTAは `/login?callbackUrl=%2Fcreate`（`page.tsx:85,170,407`）で機能するが、対応エリアの記載がLPに無い（H1の入口）。カテゴリカードは `/create` 直リンク（`:345`）で未ログインなら弾かれる |
| 2 | 未ログインで /create | ✅ 通る | 撮影前に `/login?callbackUrl=%2Fcreate` へ即リダイレクト（`create/page.tsx:93-95`）。撮影が無駄にならない設計。復帰後は空でよい（この時点で入力は無い） |
| 3 | 会員登録（メール） | ❌ 詰まる | 必須3項目のうち2つが破棄（H3）。対応エリア外でも完了（H1） |
| 4 | 会員登録（LINE） | ✅ 通る | `LineAuthButton callbackUrl="/create"`（`signup/page.tsx:158`）。未構成時は専用文言（`notifications/page.tsx:160`） |
| 5 | 登録直後の案内 | ⚠️ 分かりにくい | 完了画面は「さっそく出品してみる」のみ（`signup/page.tsx:297`）。通知設定（LINE連携）の案内はマイページまで出てこない |
| 6 | /create STEP1 写真 | ❌ 詰まる | ギャラリー選択不可（H2）。撮影完了チェックの理由表示は r8 で是正済み・回帰なし（`:906-913`） |
| 7 | /create STEP2 目的 | ✅ 通る | 既定値あり・`CASE_PURPOSES` 一元化（`:24`） |
| 8 | /create STEP3 住居 | ⚠️ 分かりにくい | 必須の理由が無言（M6）。都道府県4件のみ（H1） |
| 9 | /create STEP4 送信 | ✅ 通る | 冪等キー再発行・60秒タイムアウト・離脱ガードとも回帰なし（`:433-447`, `:186-201`）。ただし401時は保護が抜ける（M9） |
| 10 | 解析中 → 案件詳細 | ✅ 通る | `?created=1` の受付メッセージ（`cases/[id]:414-418`）、pending の自動ポーリング＋10分で再読込導線（`:624-639`） |
| 11 | 入札受領 → 比較 | ✅ 通る | 最高額バッジ・評価・口コミ・業者プロフィール導線あり（`:686-704`） |
| 12 | 選定（成約） | ✅ 通る | 確認モーダルに「住所詳細が開示されます」明示（`:728`）。停止業者は選択不可（`:723`） |
| 13 | 成約後の案内 | ⚠️ 分かりにくい | チャット・日程・業者連絡先は揃う（`:837-850`）が金額の呼称が画面ごとに変わる（M2） |
| 14 | 日程確定 → 当日 | ✅ 通る | 業者候補が無くても任意日を選べる（`schedule/page.tsx:27-28`）。確定後の通知文言と backend 実装は一致（r3-H2 の回帰なし・`schedule/page.tsx:508,536`） |
| 15 | 完了確定 → 評価 | ⚠️ 分かりにくい | 減額 pending 中は完了不可の理由を明示（`:984-988`）。投稿後が行き止まり（M7） |
| 16 | 次の出品 | ⚠️ 分かりにくい | `/review` からは誘導あり（`review:338`）、案件詳細からは無し（M7） |
| 17 | マイページの集計 | ⚠️ 分かりにくい | 「入札受付中」の定義ずれ（M5）、サマリーの飛び先が全て同じ（M4） |
| 18 | 任意項目（本人確認/口座/LINE） | ⚠️ 分かりにくい | 遷移先には「任意です」と明記（`mypage/identity:351,375`、`bank-account:387`）だが、マイページの一覧は「未提出／未登録／未連携」バッジのみで任意と読めない（`mypage:392-412`）。`/notifications` へのリンク文言「（本人確認のためパスワード入力があります）」（`:375`）は閲覧に必要と誤読させる（実際は LINE 連携操作時のみ） |
| 19 | 通知のリンク先とログイン状態 | ✅ 通る | メール/LINE とも `/cases/{id}`・`/chat/{txn}`・`/mypage/identity` を指し（`notify.py:133,300,452`）、未ログインなら middleware が `callbackUrl` 付きで `/login` へ（`middleware.ts:47-52`）。オープンリダイレクトは `safeInternalPath` で遮断（`safe-path.ts:9`） |
| 20 | 取り下げ・キャンセル | ⚠️ 分かりにくい | 案内文の表示崩れ（M1）、prompt 二段（M8） |
| 21 | モバイル375px | ✅ 通る | 固定フッター 74px 前後に対し `.flow-wrap` は `padding-bottom:90px`（`katazuke-pages.css:189`）で被らない。`confirm-row` は縦積み化（`:195-196`）、360px 未満はステップラベル非表示（`:198-200`）。例外は M1 の1箇所 |

## 回帰確認（過去台帳の是正項目・いずれも回帰なし）

- r3-H1（セッション期限の非同期）: NextAuth `maxAge` を backend JWT と同じ7日に固定（`web/src/auth.ts:195-208`）。
- r3-H2（日程確定の通知文言）: 「業者へ通知」に是正済み（`schedule/page.tsx:508,536`）。
- r3-H3（/create の離脱で全消失）: `beforeunload` + popstate 二重ガード維持（`create/page.tsx:169-201`）。※401経路の抜けは M9。
- r6（解析中ポーリング・未読数）・r7（冪等キー再発行）・r8（終了取引ガード・退会業者・ConfirmModal 共通化）・r9（コントラスト）: いずれも該当コードが残存し、破壊されていないことを確認。

## 確認したが問題なし

- 二重送信ガード: `submitting`（`create:882,888`）・`busy`（`cases/[id]:723,749,945,964`）・`busyOps` の商品単位排他（`cases/[id]:88-121`）。
- 写真の再送重複防止: `uploadedKey` 保持で再試行時に再アップロードしない（`create:395-408`）。
- 端末側の縮小（長辺2000px・JPEG 0.85）で 150 枚上限でも現実的（`create:52-79`）。
- 停止業者・退会業者の可視化と操作抑止（`cases/[id]:713-717,801-813,835`）。
- `/analyzing`・`/condition`・`/result` は現行導線から一切リンクされておらず（grep 0件）、robots でも disallow（`robots.ts:22`）。

## 末尾サマリ

- ❌ High 3件（対応エリアの入口/出口不一致・ギャラリー選択不可・必須入力の破棄）
- ⚠️ Medium 9件（表示崩れ1・用語の揺れ2・集計の意味2・理由非表示1・行き止まり1・ダイアログ2）
- ✅ 成約〜評価の本流、通知リンクとログイン復帰、375px のレイアウトは通る
