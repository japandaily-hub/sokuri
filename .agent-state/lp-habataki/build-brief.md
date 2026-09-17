# /lp 構築ブリーフ — 参照LP（はばたき農場）のUIをカタヅケに移植する

作成: 2026-09-17（リーダー）。参照LPの実測仕様は同フォルダの `reference-spec.md`（抽出エージェントが作成）と `shots/`。
本書は「何を・どの内容で・どの制約で作るか」の正本。数値（寸法・余白・波形高さ・アニメ尺）は reference-spec.md を正とする。

## 0. 解釈（リーダー判断・仮定）
- 「参照LPのUIを忠実にカタヅケのUIへフィックス」＝ **構図・区画構成・区画の順序・装飾の作法（帯＋波形上端・浮遊イラスト・大見出し＋英字キャプション・01/02/03 のセル・一日のタイムライン・3枚カード・全画面メニュー・浮遊CTA・pagetop）・モーション（スライダー／揺れ／フェードアップ）を参照LPに忠実に再現**し、**色・書体・角の作法・コピー・画像・導線はカタヅケの正典（`web/src/app/katazuke.css :root` と `web/DESIGN_SYSTEM.md §10`）に置き換える**。
- 参照LPの資産（画像・SVG・CSS本文・JS）は**一切コピーしない**。テクスチャ・波形・ドット模様は CSS/SVG(data URI) で自作する。
- 新規ルート `/lp` として追加する。既存 `/`（page.tsx）と共有CSS（katazuke.css / katazuke-pages.css / katazuke-motion.css / katazuke-top.css）は**編集しない**。
- 参照LPは独自ヘッダー（ロゴ＋MENU OPEN＋浮遊購入ボタン）と独自フッターを持つため、`/lp` も独自クロムを描く（`SiteChrome.tsx` の `BARE_PREFIXES` に `"/lp"` を1行追加＝共通ヘッダー・額装 `.site-frame`・Dock・共通フッターを抑止）。額装フレームは全幅の帯と両立しないため `/lp` では使わない（仮定）。
- 参照の丸み（角丸 1.8rem・円ボタン・blob）はカタヅケ正典（角丸0・影0・円はドットとアバターのみ）に従い**直角**にする。ただし**帯の波形上端はセクション区切りの構図要素**として残す（角丸規約の対象外と解釈）。
- デプロイしない。metadata に `robots: { index: false, follow: false }` を付けて置く（本採用時に外す。コメントで明記）。

## 1. 成果物（ファイル）
| パス | 役割 |
|---|---|
| `web/src/app/lp/page.tsx` | サーバーコンポーネント。metadata・全区画。`import "./lp.css"` |
| `web/src/app/lp/lp.css` | `/lp` 専用CSS。**全セレクタを `.lp-page` 配下にスコープ**（`.lp-page .lp-kv` 等）。@keyframes 名は `lp-` 接頭辞 |
| `web/src/app/lp/_components/LpChrome.tsx` | client。ヘッダー（ロゴ・MENUボタン）、全画面メニュー、浮遊CTA、pagetop |
| `web/src/app/lp/_components/LpSlider.tsx` | client。KVスライダー（クロスフェード＋ゆるいズーム、ドット、一時停止ボタン） |
| `web/src/components/kdz/SiteChrome.tsx` | `BARE_PREFIXES` に `"/lp"` を追加（この1行のみ） |

`page.tsx` は `<main id="main" className="lp-page">` を根にする（layout.tsx のスキップリンクが `#main` を参照）。

## 2. 区画対応表（参照 → カタヅケ）
参照LPの区画順と構図を**そのまま**使い、中身だけ差し替える。各区画の寸法・余白・グリッドは reference-spec.md の該当節を実装する。

| # | 参照区画 | /lp の区画（id） | 内容（コピーは §4 の出典から**文言そのまま**） | 画像 |
|---|---|---|---|---|
| 1 | `.home-kv` スライダー＋浮遊イラスト＋キャッチSVG＋右側ドット | `#top` `.lp-kv` | h1「片付けたい。でも、動けないあなたへ。」（`.hl` は `動けない`）＋ `.hero-sub` の1文。スライドは6枚（`ex-lot-*.webp` 1536x1024）5秒間隔クロスフェード（参照の `-slow`）。浮遊物は `ill-*.webp` 6点（揺れ＝参照 `c-anime-rotate`/`fluffy` 相当を CSS keyframes で）＋ CSS で描くドットのひし形クラスタ（`--primary-l` / `--marker`）。参照の「たまごを購入する」blob → 浮遊CTA（§5）。 | ex-lot-jikka/moving/closet/ihin/rearrange/kitchen |
| 2 | `.home-message` 詩文＋小イラスト | `.lp-message` | 運営者メッセージ3段落（page.tsx `#founder` の `<p>` 3本）＋署名「カタヅケ 運営事務局」。中央揃え・行間広め。周囲に ill 2〜3点。 | ill-plant / ill-books |
| 3 | `.home-about`（主色帯・波形上端・テクスチャ・`__item`×3 交互配置） | `#about` `.lp-about` | 帯見出し「カタヅケは、まとめ売りの買取マッチングです。」（新規の見出し文。約束・数値は含めない）。item1: 「まとめて出すほど、有利になる。」＋ `.bundle-copy .lead`。item2: 「業者が買取総額で競うから、高くなりやすい。」＋ `#auction .sub`。item3: 「業者が直接、引き取りに来ます」＋ `.handover .sub`。帯の下端に注記 `※ 最終的な買取額は業者の現物査定により決まります。` | bundle-3d / bid-3d / top-handover |
| 4 | `.home-point`（食／住／循環。大漢字＋`- EATING -`、`__cell--main`(01＋小見出し3)＋`__cell--basic`(02/03)、末尾に循環図） | `#point` `.lp-point` | 3ブロック。**撮 / - SHOOT -**「あなたがするのは、撮ることだけ」: 01 主=「1点ずつ撮る」（STEPS[0].p）＋小見出し3＝「仕分け・分別は不要」「値がつかない物も、まとめて回収」「梱包も発送も不要。玄関先で引き渡すだけ。」（各本文は出典どおり）／02「査定が届く」／03「査定を見比べて選ぶ」。**選 / - CHOOSE -**「入札のしくみ」: 01 主=「連絡先を伏せて出品内容が届く」＋小見出し3＝「写真・品目・地域のみ」「氏名・電話は渡りません」「詳細住所とメールは成立後」（本文は `#auction` li と `.assure` の文言）／02「登録業者が買取総額で入札」／03「連絡が来るのは選んだ1社だけ」。**安 / - TRUST -**「はじめてでも、安心して任せられる」: 01 主=「登録事業者のみ」（`#trust` 本文）＋小見出し3＝「古物商許可を確認」「東京・千葉・埼玉・神奈川」「審査を通過した業者から順に参加」／02「連絡先は成立後に開示」／03「訪問買取は特定商取引法の対象」。末尾（参照の循環型農業図）＝既存 `.ill-loop` 帯をそのまま再利用（`ILL_LOOP`・`ILL_POSITIONS`・`Reveal`）に見出し「片付いた物は、次の誰かのもとへ。」（新規見出し・約束なし）。 | 撮: top-hero-woman-20s / top-scene-danshari / top-hero-man-20s。選: bid-3d / top-worry-phone / trust-illus-2。安: trust-illus-1 / trust-illus-3 / top-handover（重複可） |
| 5 | `.home-daily`（主色帯・波形上端・「一日」01〜09 写真＋キャプション） | `#daily` `.lp-daily` | 見出し「カタヅケの、出品から引き取りまで。」09ステップ（下記 §4-B の文言。順序固定）。 | top-hero-woman-20s, top-scene-moving, bid-3d, top-hero-couple-child, top-scene-jikka, top-hero-couple-60s, top-scene-ihin, top-handover, top-cta-band（各1:1 に切る） |
| 6 | `.home-kome`（商品ハイライト＋CTA2本） | `#fee` `.lp-fee` | 「費用は、一切かかりません」＋ `.fee-zero`（お客様のお支払い／¥0／fz-note／**fz-caution 必須・¥0 と同一視野・本文サイズ**）＋ CTA2本＝ `.btn.btn-line`「LINEではじめる（無料）」（sub「LINEアカウントでログインできます」・href `/login?callbackUrl=%2Fmypage`）＋ `.btn-ghost`「6件のモデルケース（買取額の例を含む）を見る」→ `/examples`。 | top-founder-desk（静物） |
| 7 | `.home-coco`（3店舗カード＋詳しく見る＋住所・営業時間・地図） | `#cases` `.lp-cases` | 「こんなふうに使えます」＋ sub「サービスの流れをイメージしていただくための、架空のモデルケースです。」＋ **`MODEL_CASE_NOTE`（カード群より手前・省略不可）**。`FEATURED_CASES` 3件: 各カード先頭に **`MODEL_CASE_CHIP`**、肖像 `/img/v2/${portrait}.webp`（alt=portraitAlt）、`caseName(c)`、`${persona}／${tag}`、`「${quoteShort}」`、facts 3値（まとめて出品 count 点／入札 bidCount 社／成約まで days 日）。**金額（amount）は出さない**。「詳しく見る」→ `/examples`。参照の住所ブロック → 「対応エリア: 東京都・千葉県・埼玉県・神奈川県（順次拡大）」＋「会社概要を見る」→ `/company`（住所・電話は書かない）。 | mc-jikka / mc-moving / mc-ihin |
| 8 | `.home-farm`（淡色テクスチャ帯・波形上端・カード3枚＋リンク） | `#biz` `.lp-biz` | 「買取業者の方へ。カタヅケに参加しませんか。」＋ `.biz-banner-copy p` 全文（β注記含む）。カード3枚＝「初期費用・月額費用 無料」「成約時8%（税別）のみ」「下見なし・一斉架電なし」（本文は biz-tag/biz p の文言のみで構成）＋「β期間中は手数料0円（期間限定・請求開始は事前にお知らせします）」を注記行に。CTA「業者登録の詳細を見る」→ `/business`、テキスト「審査制・登録無料」。 | biz-reason-bulk / biz-reason-photo / biz-reason-route |
| 9 | footer（ロゴ・電話・ナビ・購入CTA・©） | `.lp-footer` | KdzLogo、ページ内ナビ（§5と同じ）、リンク: 使い方 `/#flow`／よくある質問 `/faq`／撮影ガイド `/photo-guide`／会社概要 `/company`／特定商取引法に基づく表記 `/legal`／プライバシーポリシー `/privacy`／利用規約 `/terms`／お問い合わせ `/contact`／業者登録 `/business`／業者ログイン `/operator/login`。`© 2026 カタヅケ`／`東京都・千葉県・埼玉県・神奈川県（順次拡大）`。電話番号は書かない。 | — |

## 2.5 構図の補足（リーダーがスクショを実見して確定。reference-spec.md の ASCII 図より優先）
- **KV**（`shots/pc-02-kv.png`）: 画面いっぱいの淡色地。上中央にキャッチ（2行・大）＋その直下に小さな英字キャプション（Comfortaa 相当・字間広め）。中央に主写真（参照は有機的なマスク。カタヅケでは**直角の写真枠**、幅は画面の約 45%、縦横 3:2、上端はキャッチのすぐ下）。写真の周囲と地に浮遊イラスト（参照は鶏・花・卵 20 点前後 → カタヅケは `ill-*` 6 点＋CSS ドットひし形クラスタ 4〜6 個）。右端中央に**縦並びのスライダードット**（4〜6 個・活性は主色）。下端は白い波形で次区画へ。左上ロゴ、右上 MENU（参照は青の角丸大ブロック 164×141 → 正方形〜長方形の主色ブロック・白文字「MENU / OPEN」2行＋2本線アイコン）。MENU の左下に浮遊CTA（参照は黄 blob 220×150 → `.btn.btn-line` コンパクト版・固定位置）。
- **MESSAGE**（`pc-03-message.png`）: 左に写真 2 枚（大小・上下にずらした段違い配置。参照は卵型マスク → 直角枠）、右に本文（右カラム幅約 45%、行間 34px 級の詩文体・先頭句だけ主色）。右上に極小の英字キャプション（"message from katazuke"）。区画下端は**丘のような二重波形**で主色帯（ABOUT）に入る。
- **ABOUT**（`pc-04-about.png`）: 主色帯・上端に雲（→ カタヅケでは白い矩形／省略可）。見出しは帯上部に置かず、**3 item の交互配置（写真 左 / 文 右 → 文 左 / 写真 右 → 写真 左 / 文 右）**。各 item の文側に極小英字「about katazuke 01」→ 見出し 2 行（強調語は `--lime`）→ 本文（帯上の白・15px・行間 2）。写真は帯幅の約 45%・3:2。item 間に鳥の足跡の点線（→ カタヅケは 1px の**破線**を斜めに 1 本）。帯下端は白い波形。item3 の下に小さな写真 3 枚の横並び（参照）→ カタヅケでは省略可（画像枯渇のため）。
- **POINT**（`pc-05-point-eating.png`）: 区画の地は淡色。**各ブロック冒頭に大きな色面**（参照は左上から画面の 45% を占める緑の巨大な丸 → カタヅケは主色の**大きな矩形**、左上に寄せて右下は淡色地を残す）。色面の上に**バッジ**（参照は黄の卵型 110×150 に「食」40px＋「- EATING -」9px → カタヅケは**白地の正方形 120px**に主色で漢字 40px＋英字 9px `--en`）。続いて **01 主セル**: 左に見出し（漢字見出し＋右肩に `01` を `--en-display`・主色）＋本文、右に大写真（3:2・幅 45%）。その下に**小見出しカード 3 枚横並び**（参照は白カード・角丸・見出し下にドット列 → カタヅケは白地・1px `--line`・見出し下に**1px の主色罫 40px**）。その下に **02 / 03 を 2 列**（各: 写真 3:2 → 見出し＋番号 → 本文）。3 ブロック（撮／選／安）とも同じ骨格。ブロック間は余白のみ（参照は living が黄地・cycle が青地 → カタヅケは**撮＝主色面／選＝`--deep` 面／安＝`--pale` 面**でバッジ背景を変える）。
- **DAILY**（`pc-08-daily.png`）: 主色帯。01〜09 の写真を**大小 2〜3 種のサイズで左右に段違い配置**（1 行に 2〜3 枚、揃えない）。各写真の右上に**番号の白丸（→ 正方形 32px・白地・主色文字）**、写真の下に白い 2 行キャプション（14px・行間 1.9・最大 22em）。一部に小さなラベル（参照「水飲み」「ごはん」青ピル → カタヅケは**主色地・白文字の直角タグ**、文言は工程名「撮る」「入札」「引き取り」等の既存語）。写真間に足跡点線（→ 1px 破線）。帯下端は白い波形。
- **FEE（参照 KOME）**（`pc-09-kome.png`）: 上部は淡色地に浮遊イラストが散る余白帯（高さ約 500px）。中央に**巨大な卵型のベージュ面**（→ カタヅケは `--pale` の**大きな矩形パネル**・幅 90%・上下 100px 余白）。パネル内: 小見出し（eyebrow）→ 大見出し（¥0 を主役に）→ 英字キャプション → 本文 → 写真（3:2・幅 70%）→ ドット 3 個 → **CTA 2 本横並び**（参照は黄 blob＋青 blob → `.btn.btn-line` ＋ `.btn-ghost`）。パネル外の下端は主色の丘＋水色の波（→ 主色の波形 1 段のみ）。
- **CASES（参照 COCO）**（`pc-11-coco-main.png`）: 淡色地。中央揃えの見出し（和文＋極小英字）→ 2 行の大キャッチ（後半を主色）→ 本文 2 行。**item 3 件は「写真 左（正方形寄り・幅 40%）／ロゴ＋見出し＋本文 右」**で縦積み、各 item の右上に「詳しく見る」ボタン（参照 黄 blob → `.btn-ghost` 小）。カタヅケでは写真＝肖像 1:1、ロゴ位置＝`MODEL_CASE_CHIP`、見出し＝`caseName`＋persona/tag、本文＝quoteShort、その下に facts 3 値。
- **BIZ（参照 FARM）**（`pc-14-farm.png`）: 淡色地に雲。**全幅の集合写真（3:2・幅 92%）**→ その下に **2 列（左: 4 行の大見出し・強調語が主色／右: 本文 6〜8 行）**→ **カード 3 枚横並び（写真 1:1 → 見出し 2 行 → 本文）**→ 中央に CTA 1 本（参照 黄 blob → `.btn.btn-primary`）。カタヅケの全幅写真は `biz-band-sorting.webp`（帯用・横長）。
- **MENU オーバーレイ**（`pc-25-sitemap-open.png`）: 淡色地（`--pale-2`）。左 45% に大写真（参照は有機マスク → 直角・上下いっぱい・`top-cta-band.webp`）。右にリンク 2 列（各行: **主色の矢印マーク（→ 正方形 24px・白矢印 `Ic arrow`）＋ラベル 18px**）、その下に横長の CTA パネル（`.btn.btn-line` 全幅）、さらに下に 2 枚の白パネル（→ 「ログイン」「業者の方へ」の 2 リンクパネル）、最下段にロゴと対応エリアの 1 行。右上 MENU ボタンは「CLOSE」＋×。
- **フッター**（`pc-15-footer.png`）: 主色の波形上端 → 淡色地。左にロゴ、中央にナビ 2 列、右に pagetop（主色の縦長ブロック・白文字「PAGE TOP」＋上矢印）。最下段 © 行。

## 3. デザイントークンの置換規則
| 参照 | カタヅケ |
|---|---|
| 主色帯 #05a277（緑） | `var(--primary)` #1447e0。帯上の文字は #fff、帯上の補助文字 rgba(255,255,255,.86) |
| 地 #f4f4f4 | `#fff`（本文面）／`var(--pale-2)` #f4f7fc（淡色面・.lp-biz） |
| 黄 #fbeb2c／#ffe100（アクセント・ドット） | `var(--gold)` は装飾のみ（文字には `--gold-text`）。ドットの活性色は `var(--primary)`、非活性は rgba(255,255,255,.5)（帯上）/`var(--line)`（白地） |
| 青 #0d6fb8（MENU・リンク） | `var(--primary)` |
| Zen Maru Gothic | `var(--serif)`（見出し・本文）。数値・入力値・小ラベルは `var(--ui)` |
| Comfortaa（英字キャプション） | `var(--en)`（Montserrat 600 uppercase, letter-spacing .18em）。番号 01〜09 は `var(--en-display)` |
| 角丸 1.8rem／円ボタン | 0。MENU ボタン・pagetop・ドット以外の円形を作らない（スライダードットは円で可） |
| 影・blob | なし。面の変化は帯色と 1px `var(--line)` ヘアラインだけ |
| bg_texture.webp | SVG feTurbulence の data URI を `opacity:.05〜.07` で `::before` に敷く（`mix-blend-mode` 不要） |
| 波形上端 `.c-wave2-top` | SVG path を `mask-image`（または背景 SVG）で自作。高さ・振幅は reference-spec の実測に合わせる。`aria-hidden` |
| ホバー scale(1.2)/opacity .5 | `opacity:.8`（ボタン）／`.85`（画像）のみ。持ち上がり・拡大なし |
| js-fadeup（fade＋上移動） | `Reveal`（`variant="up"`）を使い、`.lp-page .rv--up` を lp.css で定義（`html.js-rv .lp-page .rv--up:not(.in){transform:translateY(var(--rv-shift))}` の形。**opacity:0 を書く行は必ず `html.js-rv` 配下**） |
| c-anime-rotate / fluffy（揺れ・浮遊） | `@keyframes lp-sway`（rotate ±3〜6deg）／`lp-float`（translateY ±6〜10px）。参照の duration を踏襲。`prefers-reduced-motion` は globals.css の全体規則で止まるが、念のため `@media (prefers-reduced-motion:reduce){animation:none}` を明記 |

## 4. コピーの出典（**一字一句この出典から。要約・書き換え・新しい約束/期間/効果/統計の追加は禁止**）
- A. `web/src/app/page.tsx`: h1・`.hero-sub`・`STEPS`・`.bundle-*`・`#auction` li・`.handover` `.mlist`・`#trust` 3項・`.fee-zero`（fz-label/fz-num/fz-note/fz-caution）・`#founder` の p 3本と署名・`.biz-banner` の h2/p/tags/chip・`.auc-note`。
- B. `#daily` 9ステップ（本書で確定・出典は A と `.assure` の文言の並べ替えのみ）:
  01 家じゅうの不用品を1点ずつ撮影。／02 写真と品目をまとめて登録するだけで出品完了です。／03 業者に届くのは、写真・品目・地域（都道府県・市区町村）・住居情報などの出品内容のみ。／04 複数の業者が、出品した商品すべてに対して買取総額を提示します。／05 提示された総額は、すべて一覧で見比べられます。／06 提示を見比べて1社を選択。選ばなかった業者には自動でお断りが入ります。／07 成立後に連絡先を開示し、引き取り日時を決めます。／08 訪問時の現物確認で写真と状態が違えば、業者から金額のご相談が届くことがあります。納得できなければお断りできます。／09 玄関先で渡すだけで、片付け完了です。
- C. `web/src/lib/model-cases.ts`: `FEATURED_CASES`・`caseName`・`MODEL_CASE_CHIP`・`MODEL_CASE_NOTE`（値の直書き禁止・必ず import）。
- D. 新規に書いてよいのは**区画の見出し・英字キャプション・ナビラベル・aria-label**だけ。禁止語: 最高／No.1／絶対／実際の／お客様の声／実績／累計／平均／成約率／利用者数／◯日で／必ず／保証。

## 5. クロム（LpChrome）の仕様
- ヘッダー: 左上に `KdzLogo`（`/` へリンク）。右上に MENU ボタン（正方形・`var(--primary)` 地・白文字「MENU」＋ハンバーガー線。開いた状態は「CLOSE」）。`position:fixed`。参照の見た目・寸法は reference-spec (b)。
- 全画面メニュー: 参照 `.l-sitemap` と同じ開閉演出（フェード＋スライド、尺は spec）。中身: ページ内アンカー（トップ `#top`／カタヅケについて `#about`／こだわり `#point`／出品から引き取りまで `#daily`／料金 `#fee`／利用イメージ `#cases`／業者の方へ `#biz`）＋ 外部リンク（ログイン `/login`／マイページ `/mypage`／よくある質問 `/faq`／業者登録 `/business`）＋ `.btn.btn-line`。`aria-expanded`/`aria-controls`、Esc で閉じる、開いている間は `body{overflow:hidden}`、閉じたらボタンへフォーカスを戻す、アンカー押下で閉じる。
- 浮遊CTA: 参照の黄 blob の位置に、コンパクトな `.btn.btn-line`（タイル＋ラベル「LINEではじめる」＋sub「無料」）。LINE ブランド色 #06c755 はタイルとボタン地の既存規則どおり（`katazuke.css .btn.btn-line`）。**LINE 単独導線にしない**（各区画に ghost CTA／メニュー内にテキストリンクを併置）。モバイルでの位置は spec に従う（参照が下部固定なら下部固定）。
- pagetop: 参照と同位置。`aria-label="ページの先頭へ"`。スクロール量 > 1画面で表示。

## 6. 実装制約（守れないものは戻り値で明示）
- Next.js 15.5 App Router / React 19 / Tailwind 3（本ページは Tailwind クラスをほぼ使わず lp.css で組む）。
- `100vw` を使わない（縦スクロールバー分の横スクロールが出る）。`width:100%` と負マージンで全幅化。**375px／390px で横スクロールが出ないこと**（`document.documentElement.scrollWidth <= clientWidth`）。
- 画像: 既存 `/img` のみ。`width`/`height` 必須。KV 1枚目のみ `loading="eager" fetchPriority="high"`、他は lazy。装飾は `alt=""`。意味のある画像の alt は page.tsx / model-cases の既存 alt を流用。`<img>` は `// eslint-disable-next-line @next/next/no-img-element` を付ける（既存ページと同じ流儀）。
- 装飾要素は `aria-hidden="true"`。スライダーには一時停止ボタン（`aria-pressed`）とドット（`role="tablist"`/`role="tab"`/`aria-selected`）。`document.hidden`・ホバー・フォーカス中は自動送りを止める（`HeroCarousel` と同じ）。
- 見出し階層: h1 は KV に1つ。区画見出し h2、セル見出し h3、小見出し h4。
- `:focus-visible` は globals の共通リングを消さない。`overflow:hidden` をボタンに付けない。
- CSS は lp.css だけに書く（インライン style は CSS 変数の受け渡し `--i`/`--ill-top` 等に限る）。`!important` 禁止。
- **検証コマンド（実装完了前に必ず通す・結果を戻り値に貼る）**: `cd web && npx tsc --noEmit` → エラー0、`npx eslint src/app/lp src/components/kdz/SiteChrome.tsx` → error 0 warning 0。`next build` はリーダーが行う（dev サーバーと .next が競合するため実装者は実行しない）。
- 編集禁止: `web/src/app/page.tsx`、`katazuke*.css`、`globals.css`、`layout.tsx`、`web/e2e/**`、`.claude/worktrees/**`。

## 7. 完成条件（DoD）
1. `/lp` が dev で 200 を返し、console error 0。
2. 区画 1〜9 がすべて存在し、順序が参照と一致（DOM の section 順）。
3. 各区画の構図が reference-spec の ASCII 図と一致（PC 1280 / SP 390 の両方）。
4. 波形上端・テクスチャ・浮遊イラストの揺れ・KV スライダー・全画面メニュー・浮遊CTA・pagetop が動作。
5. コピーが §4 の出典と一字一句一致（新規見出し以外）。`MODEL_CASE_NOTE` がカード群より手前、`MODEL_CASE_CHIP` が各カード先頭、金額なし。fz-caution が ¥0 と同一視野。
6. 375/390px で横スクロールなし。tsc 0／eslint 0。
7. `prefers-reduced-motion: reduce` で自動送り・揺れが止まり本文が消えない。

## 8. 画像資産インベントリ（`web/public/img/`）
- `v2/`（写真・1536x1024 or 1024x1024 or 900x1350）: top-hero-woman-20s／man-20s／couple-child／couple-60s／top-hero-person（2:3 人物・床で撮影）、top-hero（手元）、top-scene-danshari／moving／jikka／ihin（1:1 静物）、top-worry-listing／phone／boxes（1:1 静物）、top-handover（3:2 玄関先の引き渡し）、top-founder-desk（3:2 机上静物）、top-cta-band（1920x1088 人物）、ex-lot-jikka／moving／closet／ihin／rearrange／kitchen（3:2 部屋にまとめた品物）、mc-jikka／moving／ihin（1:1 肖像・モデルケース専用）、biz-reason-bulk／photo／route（1:1 業者向け）、biz-hero、pg-*（撮影ガイド用・使わない）、*-band（帯用）。
- `real/`（3Dレンダー・淡青スタジオ地・1536x864 or 1024）: bundle-3d、bid-3d、trust-illus-1/2/3（1024x768）、cat-*（512・カテゴリ）、check（512）、how-*（使わない）。**3D は 112px 以上の枠でしか使わない**（縮小するとにじむ）。
- `ill/`（480x480 透過・線画イラスト）: ill-box／books／plant／folding-hands／house-tree／truck。浮遊物はこれだけ。
- アイコン: `Ic name=` `camera|arrow|check|x|spark|trend|people|scan|scale|truck|check-circle|menu|shield|bag|lock|sun|tag|zoom|crop|chat|up|house|crown|phone|clock|pin|sofa|box|chev|yen|pause|play`（`@/components/kdz/Icons`）。
