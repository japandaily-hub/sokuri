# カタヅケ 運営導線 x 横断UI 監査台帳
最終更新: 2026-09-03 / 対象: web/src (dev server http://localhost:3103) / 監査方式: 静的読解 + curl SSR確認(ログイン操作なし)

---

## A. 運営導線(/admin) - High以上 最大8件

### A1. limited/pending の区別なく一発でactive化でき、許可証未提出でも止まらない [High]
- 該当: web/src/app/admin/page.tsx:389-396
- 事象: toggleVerify は op.vendor_status !== "active" を判定に使い、vendor_status が limited(暫定稼働)でも pending(未承認)でも同一ボタン「承認する(active化)」を押すだけで一発 active 化される。ボタンの disabled 条件は busy のみで、op.has_license_image === false (許可証未提出、L375-377で別バッジ表示されている)でも disabled にならない(disabled 制御があるのは openLicenseModal 側の L384 のみ)。
- 再現条件: pending かつ has_license_image=false の業者を一覧表示して「承認する(active化)」を押す。APIが拒否しない限り active 化される。
- リスク: 古物商許可証未確認のまま業者をフル稼働にできる誤操作導線。古物営業法上の審査抜けに直結。
- 修正案: has_license_image=false のとき承認ボタンを disabled にし理由を表示。limited->active と pending->active を別ボタン・別確認モーダルに分離。

### A2. is_suspended(停止中)業者の停止解除導線が存在しない [High]
- 該当: web/src/app/admin/page.tsx:373,391-396 / web/src/lib/katadzuke-api.ts:973
- 事象: is_suspended な業者には StatusBadge value="cancelled" label="停止中" が付くのみで、停止解除に対応するAPI呼び出し・ボタンがない。操作できるのは toggleVerify(active<->非active)のみ。suspend/unsuspend系の関数は katadzuke-api.ts に存在しない。
- リスク: 運営者が「停止中」業者を見ても何をすればよいか画面上わからず、対応漏れ・API直叩き等の非正規運用を誘発。
- 修正案: 停止解除専用ボタン/APIをUIに追加。

### A3. 新着承認待ちを知らせるバッジ・ソート順の保証がない [High]
- 該当: web/src/app/admin/page.tsx:192-195,338-351 / 参考(編集対象外・読み取りのみ): backend/app/services/notify.py:169-179 (send_operator_application_admin_alert = 業者新規申込のadmin宛メール通知)
- 事象: バックエンドは新規業者申込をメールでadminに通知するが、管理画面側は開いた瞬間の初期状態が statusFilter="all" で、新着 pending を強調するバッジや並び順の保証がコード上ない(adminListOperators の返却順に依存、フロントで独自ソートしていない)。
- リスク: メールを見落とすと画面側にも気づく手がかりがなく、承認待ち業者が放置される。
- 修正案: pending件数バッジをフィルタボタンに表示。初期表示をpending優先ソートに変更。

### A4. バルク発行の件数入力にクライアント側バリデーションが効いていない [High]
- 該当: web/src/app/admin/page.tsx:137-155,282-289
- 事象: input type="number" min={1} max={500} を使うが、発行ボタンは type="button"(formでsubmitしていない)ため、ブラウザのネイティブ制約検証(reportValidity)は発火しない。issueBulk() は Number(bulkCount) をそのままAPIへ渡すのみでJS側の範囲チェックもない。
- 再現条件: 発行件数欄に 0 / -5 / 9999 / 空欄(NaN化)を入力し「発行」を押すと、クライアントは無条件でAPIを叩く。
- リスク: 誤入力に気付くのがAPIエラー文言頼みになり、運営の操作ミスを助長。
- 修正案: issueBulk() 冒頭で範囲チェックしNGならNoticeで即時エラー表示。

### A5. 承認/取消操作のエラーが画面最上部固定表示のみで見落としやすい [Medium/High境界]
- 該当: web/src/app/admin/page.tsx:212-216,355-405
- 事象: error ステートは単一の場所(PageShell直下)にしか表示されない。業者一覧を下までスクロールして操作失敗した場合、エラーバナーは画面上部に出るため視認されない可能性がある。
- 修正案: 操作対象の行付近にインラインエラー、またはトースト通知(.kdz-toast は katazuke-pages.css:110-114 に既存定義)に切り替える。

### A6. 業者一覧・招待コード一覧に検索/ページネーションがなく件数増加時に承認待ちを発見しづらい [High]
- 該当: web/src/app/admin/page.tsx:192-195,239,354-404
- 事象: 招待コード一覧は max-h-64 overflow-y-auto でスクロール窓があるが検索がない。業者一覧はスクロール制限すら無くページが際限なく縦に伸びる。両者とも会社名/メール検索・登録日ソートがない。
- リスク: 業者数・招待コード数が増えるほど目的の1件を探す運営コストが線形に悪化する。
- 修正案: 会社名/メール検索ボックス、登録日時(新しい順)ソートを追加。

### A7. CSVダウンロードにCSVインジェクション対策がない [Medium/推測含みHigh候補]
- 該当: web/src/app/admin/page.tsx:157-169
- 事象: downloadBulkCsv は code,lot_name,created_at をBOM付与のみでエスケープせず連結。lot_name は運営者が自由入力(L293-299)でき、= や + などで始まる文字列を入れるとExcel等で数式として解釈されるCSVインジェクションの一般的な型に該当する。
- 再現条件: ロット名欄に =1+1 等を入力してバルク発行しCSVをExcelで開く。
- 修正案: セル値が =,+,-,@ で始まる場合は先頭にシングルクォートを付与するサニタイズを追加。

### A8. セル密度の「1.5超」閾値がUI文言のみでフロントに根拠がなく、バックエンド側の閾値変更時に表示と実挙動がズレるリスク [Medium]
- 該当: web/src/app/admin/page.tsx:412-413,432
- 事象: 「1.5超は赤表示」という説明文はハードコードされたテキストで、実際の判定は row.status === "dense"(バックエンド計算、編集対象外)に完全依存。
- 修正案: 閾値をAPIレスポンスに含め、文言をテンプレート化する。

---

## B1. ヘッダー3種の切替条件・出現ルート一覧表

SiteChrome.tsx の BARE_PREFIXES 判定(完全一致 or 前方一致):

| ルート prefix | SiteChrome判定 | 実際に描かれるヘッダー | 根拠 |
|---|---|---|---|
| / , /faq , /examples , /photo-guide , /company , /legal , /privacy , /terms , /contact 等(BARE_PREFIXES外全て) | bare=false | SiteHeader (+Footer+Dock) | SiteChrome.tsx:39-56 |
| /login , /signup , /create , /password-reset , /verify-email | bare=true | 各ページ自前の最小ヘッダー(.auth-bar/.flow-header 等、未確認範囲あり) | SiteChrome.tsx:12-17 |
| /mypage , /applications , /notifications , /business , /vendors , /chat , /schedule , /review , /result , /cases | bare=true | AppHeader(コメントで明記) | SiteChrome.tsx:19-31 |
| /admin | bare=true | AppHeader(実装確認済み: admin/page.tsx:7,200,210) | SiteChrome.tsx:32-34 |
| /operator 配下(/operator , /operator/cases , /operator/transactions , /operator/profile 等) | bare=true | OperatorHeader(components/kdz/OperatorHeader.tsx) | SiteChrome.tsx:15 + 各page.tsxの言及コメント(operator/page.tsx:7, operator/profile/page.tsx:10) |
| /operator/login , /operator/signup | bare=true | 未確認(認証前ページ、OperatorHeaderではない可能性)[未解決] | - |

### 混在・欠落の指摘

B1-H1. /admin が消費者向け AppHeader をそのまま流用し、管理者専用の導線がない [High]
- 該当: web/src/app/admin/page.tsx:7,200,210 / web/src/components/kdz/AppHeader.tsx:34-39
- 事象: AppHeaderは「通知ベル -> /notifications」「マイページ -> /mypage」という一般消費者向けリンクを固定で描く。管理者が誤ってクリックすると権限のない一般消費者向け画面へ遷移しうる。管理者名表示・管理者専用ログアウトもAppHeaderには存在しない。
- 修正案: /admin 専用の最小ヘッダー(ロゴ+管理者ログアウトのみ)を新設する。

B1-H2. OperatorHeaderは920px以下でログアウトボタンが完全消滅し、代替導線が無い [High]
- 該当: web/src/components/kdz/operator-header.css:130-136 / web/src/components/kdz/OperatorHeader.tsx:13-18,94-100
- 事象: @media (max-width:920px) で .op-nav, .op-user-name, .op-logout を一括 display:none にし、代わりに .op-nav-toggle のハンバーガーを出す。開閉される .op-nav.open は NAV配列(dashboard/cases/transactions/profile)のみのリンクで、ログアウト項目を含まない。signOut()呼び出しは OperatorHeader.tsx のこの1箇所にしか存在しない(app/operator配下grep確認: サインアウト呼び出しなし)。
- 再現条件: ビューポート幅920px未満(一般的なスマホ・タブレット縦向き含む)で業者ダッシュボードを開く。
- リスク: 920px未満の全端末で業者ユーザーがアプリ内からログアウトできない。
- 修正案: .op-nav.open の末尾にログアウト項目を追加するか、ハンバーガーメニュー内に常設。

B1-H3. 3ヘッダーの折返しブレークポイントが不統一(600px/860px/920px)で挙動の一貫性がない [Medium/High境界]
- 該当: SiteHeader -> katazuke.css:613(860px), AppHeader -> katazuke.css:183(600px), OperatorHeader -> operator-header.css:130(920px)
- 事象: 同じ「ロゴ+右側アクション」という構造なのに畳む幅がバラバラ。OperatorHeaderは920pxという広い閾値で、ノートPC分割ウィンドウ(例:960px)では畳まれる一方、iPad横向き(1024px)は免れる等の不整合。
- 修正案: ブレークポイントをデザイントークン化し3ヘッダーで統一する(または意図差分をコメントで明記)。

---

## B2. フッター/Dockリンク生存確認 (curl, dev:3103)

| path | status | 備考 |
|---|---|---|
| / | 200 | |
| /create | 307 | 未ログイン→ログインへのredirect想定(middleware) |
| /photo-guide | 200 | |
| /examples | 200 | |
| /faq | 200 | |
| /company | 200 | |
| /business | 200 | |
| /legal | 200 | |
| /privacy | 200 | |
| /terms | 200 | |
| /contact | 200 | |
| /login | 200 | |
| /mypage | 307 | 未ログインredirect想定 |
| /notifications | 307 | 同上 |
| /operator | 307 | 同上 |
| /operator/cases | 307 | 同上 |
| /operator/transactions | 307 | 同上 |
| /operator/profile | 307 | 同上 |
| /operator/login | 200 | |
| /admin | 307 | 同上 |

結論: 404は0件。SiteFooter/Dockのリンク先はいずれも生存(307は認証ガードの正常なredirectと判定。ログイン後の実挙動までは未検証)。

---

## B3. レスポンシブ静的抽出(375px幅で横スクロール/破綻の疑いがある箇所)

B3-H1. admin: ステータスフィルタ行が375pxで収まらない疑い [High]
- 該当: web/src/app/admin/page.tsx:335-352
- 事象: flex items-center justify-between に flex-wrap 指定なし。見出し「業者アカウント」+ フィルタボタン4つ(すべて/active/limited/pending、各 px-3 py-1.5)が同一行。Card内側は p-5(左右合計40px)を差し引くと利用可能幅は335px。ボタン4つの推定幅合計(テキスト+padding)だけで300px超、見出しを加えると375px幅を確実に超過。justify-betweenはwrapしないためはみ出し(横スクロールまたは要素の重なり)が起きる可能性が高い。
- 修正案: flex-wrapを追加し、375px時はフィルタ行を見出しの下に折り返す、またはボタン群を横スクロール可能なchipリストにする。

B3-H2. admin: 業者liの右側アクション2ボタンが375pxで収まらない疑い [High]
- 該当: web/src/app/admin/page.tsx:361,380-397
- 事象: li className="flex items-center justify-between gap-2 py-2.5" に flex-wrap なし。右側の div に長文ボタン「許可証画像を確認」「承認する(active化)」が横並び。左側の会社名/メール/バッジ群と合わせて335px(Card内幅)に収まらない。
- 修正案: 右側ボタン群を flex-wrap させる、または375px以下でボタンをフルwidth縦積みに切り替える。

B3-M1. footer-grid 2カラム時(<=860px)の長いリンクラベル折返し [Medium]
- 該当: web/src/app/katazuke.css:558 / components/kdz/chrome.tsx:43(「特定商取引法に基づく表記」)
- 事象: .footer-grid grid-template-columns:1fr 1fr + .container padding-inline:18px(<=560px)。375px時の1カラム幅は概算150px前後で、12文字の日本語リンクラベルは折返し必至(横スクロールにはならないが行が乱れる)。
- 修正案: 375px幅では1カラム表示に切り替える、またはラベルを短縮。

B3-M2. globals.css の旧テーマ(苔緑)デッドコードがブルーテーマと矛盾 [Medium/技術的負債]
- 該当: web/src/app/globals.css:70-100 (.hero-surface, .bg-grid-faint, .bg-grid-faint-light。色値rgba(82,126,82,...)=苔緑)
- 事象: katazuke.css:11 の --primary:#1447e0(ブルー)が正典化された現テーマと矛盾する苔緑系グラデーションが定義済み。tsx側でのクラス使用箇所はgrep該当0件(デッドコード)。メモリノートにある2026-09-03の人の森整合テーマ(苔色系)移行の残骸と推測される[推測]。
- リスク: 将来これらのクラスを誤って使うとテーマが割れる。
- 修正案: 未使用確認の上、削除または新テーマ色へ更新。

B3-参考. operator-shared.css(編集対象外)の固定min-width [参考/未確定]
- 該当: web/src/app/operator/operator-shared.css:294 (.listing-info flex:1;min-width:200px;)
- 事象: 375px幅で同一行に他の固定幅要素が並ぶ場合、200pxのmin-widthが幅超過の一因になり得る。編集対象外のため実装は変更せず、指摘のみ。

---

## B4. 可読性評価(PC 1280px / スマホ 375px)

- 本文グローバル: body font-size:16px; line-height:2 (katazuke.css:71)。line-height 2.0は日本語本文としてはやや広め(目安1.7-1.9)。開発陣も自覚済みで、フォーム地の文のみ .auth-sub font-size:15px;line-height:1.75 (katazuke-pages.css:39、コメントに「2.0だと送信ボタンが折返し下に落ちる」と明記)へ個別に落としている。裏を返すと .founder-copy p, .final p 等その他の地の文(katazuke.css:498,534)は line-height:2 のまま個別対応されておらず、縦間延びが残る可能性[推測]。
- PC本文行長: --maxw-text:760px (katazuke.css:51)。16px本文で概算47-48全角字/行。目安(35-45字)をやや超過[Medium]。該当: .section-head, .founder-copy, .final p 等が --maxw-text を使用。
- hero-sub 等: max-width:30em (katazuke.css:225)は16px基準で約30字/行。目安の下限に近く問題なし。
- スマホ見出し: .hero h1 font-size:clamp(30px,4.6vw,50px) (katazuke.css:220)。375px時はclamp下限30pxが適用。text-wrap:balance (katazuke.css:76)で折返しは制御されており見出し自体の破綻は無し。
- 本文15px系(.emp-body p, .step-body p 等 font-size:15px;line-height:1.9)は目安に近く良好。
- admin管理画面はTailwindユーティリティ(text-sm, text-2xl等)でデフォルトline-height(概ね1.4-1.6)を使用しており、上記のline-height2.0問題は影響しない。

---

## 未解決 / 要追加確認
1. /operator/login , /operator/signup が描くヘッダーの実体未確認(bare=trueだがOperatorHeaderかauth-bar相当かコード未読)。
2. B3-H1/H2(admin 375px破綻)はブラウザ実測(Playwright等)での確定が必要。今回はDOM/CSSからの静的推定に留まる。ログイン操作を要するため本タスクでは未実施。
3. A2(is_suspended解除)はフロント側関数の不在のみ確認。バックエンドAPI自体の有無は未確認(backend全体は編集対象外・読み取りのみの制約下でも今回は未読)。
4. globals.cssのデッドコード(B3-M2)が本当に完全未使用か、コンパイル時のみ参照される可能性は網羅的には排除できていない。

---

## サマリ
OK フッター/Dock/主要ページのリンク生存: 404なし、良好
注意 B1: 3ヘッダーのブレークポイント不統一・adminの専用ヘッダー欠如
重大 A1/A2/B1-H2: 誤操作・導線消失に直結するHigh(許可証未確認active化、停止解除不能、業者ログアウト不能)
注意 B3/B4: 375px幅でのはみ出し疑い2件(要実機確認)、CSSデッドコード1件、行長やや超過
