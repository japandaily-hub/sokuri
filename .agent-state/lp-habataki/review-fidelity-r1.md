# /lp 忠実度レビュー r1（独立検査・敵対的）

検査日: 2026-09-17 / 対象 `http://localhost:3100/lp`（dev 3100）/ PC 1280x800・SP 390x844（Playwright MCP）
実装スクショ: `.agent-state/lp-habataki/shots-impl/impl-pc-*.png` `impl-sp-*.png`
基準: `review-checklist.md` A節 / `build-brief.md` §2・§2.5・§3 / `reference-spec.md` / `shots/`

**総評: 装飾作法（波形・テクスチャ・steps(1) 揺れ・ドット・バッジ・番号）とMENUオーバーレイは高い再現度。一方で「垂直リズム」が参照の約 77% に圧縮されており、参照LPの"ゆったり流れる"印象は再現できていない。加えて pagetop の実装方式が参照と異なり、本文を恒常的に覆っている。**

PC 実測総高 ≈ 19,141px / 参照 24,945px（-23%）。SP も同傾向。

---

## 区画別

### 1. KV `#top` `.lp-kv` — ⚠️
- 参照の構図: 画面いっぱいのフルブリード写真スライダー、上中央にキャッチ＋英字キャプション、周囲に浮遊物 20 点前後、**画面右端**中央に縦ドット、右上に MENU ブロック(164×141)とその左に浮遊CTA(220×150)、下端に白い波形。PC 高 900 / SP 828。
- 実装の実測: 淡色地(#f4f7fc)、h1 54px 明朝(中央)→英字キャプション(Montserrat)→sub、中央に **3:2 の直角写真枠 510×340（幅 40%）**、浮遊 ill 6 点＋ドットひし形クラスタ 4、**ドット列は x=896（写真枠の右脇、ビューポート右端 1270 ではない）**、一時停止ボタンをドット下に併置、MENU 140×120、浮遊CTA 220×102 @(1050,132)、下端に白波形 230px。PC 高 **1105**／SP 高 **682**。
- 判定: ⚠️（ドット位置は ❌ 相当）
- 根拠: `impl-pc-01-kv.png` / `impl-sp-01-kv.png` vs `shots/pc-02-kv.png` `shots/sp-02-kv.png`
- 修正案: `.lp-page .lp-slider__dots{position:absolute;right:24px;left:auto;top:50%;transform:translateY(-50%);flex-direction:column}`、および `.lp-page .lp-kv{min-height:100svh}`（SP で 682px しかなく画面を満たさない）。

### 2. MESSAGE `.lp-message` — ⚠️
- 参照: 左に写真 2 枚の段違い（卵型マスク）、右カラム約 45% に詩文（14px/lh34）、右上に極小英字、下端は**丘のような二重波形**で主色帯へ。PC 高 976。
- 実装: 左に淡色の正方形枠 2 枚（中身は `ill-plant` / `ill-books` の線画）、右に本文、`#lp-message-en` あり、下端は**単層**の白波形 230px。PC 高 **650**（-33%）。
- 判定: ⚠️
- 根拠: `impl-pc-02-message.png` vs `shots/pc-03-message.png`
- 修正案: `.lp-page .lp-message{padding-block:140px 250px}` で参照の高さに寄せ、波形を 2 レイヤ（`.lp-wave--white` を `translateY` 違いで 2 枚）にして二重丘を作る。

### 3. ABOUT `#about` — ✅（強調色のみ ⚠️）
- 参照: 主色帯＋テクスチャ、`__item`×3 の交互配置（写真左/文右 → 文左/写真右 → 写真左/文右）、各文側に極小英字 `about … 01`、見出し 2 行（強調語は黄）、本文は帯上の白、item 間に足跡点線、上下に波形 231px。PC 高 2829。
- 実装: 交互配置 3 item ✅／英字 `ABOUT KATAZUKE 01` ✅／見出し 2 行 ✅／本文 rgba(255,255,255,.86) ✅／斜めの 1px 破線 ✅／波形 上下 230px ✅（参照 231）。帯下端に `※ 最終的な買取額は…` ✅。PC 高 **1998**（-29%）。
- **強調語の色が `rgb(143,180,255)`（淡い水色）で、主色 #1447E0 に対しコントラスト約 3.6:1。参照の黄(#fbeb2c)のような「効く」アクセントになっていない。**24px 未満の強調に同色を使うと WCAG AA も落ちる。
- 判定: ✅（構図）／⚠️（強調色・高さ）
- 根拠: `impl-pc-03-about.png` vs `shots/pc-04-about.png`
- 修正案: `#about .lp-about__catch b{color:var(--gold)}`（または #ffd54a）に変更。

### 4. POINT `#point`（撮/選/安 3 ブロック） — ✅（寸法 ⚠️）
- 参照: 各ブロック冒頭に**画面の 45% を占める巨大色面**（高さ約 700px）、その上にバッジ（漢字40px＋英字9px）、01 主セル（左に見出し＋番号／右に大写真）、白カード 3 枚横並び、02/03 の 2 列。各ブロックで色が変わる（緑/黄/青）。PC 高 2922 / 2520 / 1566。
- 実装: 色面 `.lp-point__plate` **584×333**（幅 46%・高さは参照の約半分）、白正方形バッジ 120×120（撮 + `- SHOOT -`）を色面左端 x=57 に配置、h2 → 01 主セル（見出し＋`01` Libre Baskerville 主色／右に写真 495px）→ 小カード 3 → 02/03。ブロック別に primary / deep / pale の色面 ✅。PC 高 **1716 / 1687 / 1718**。
- 判定: ✅（骨格）／⚠️（色面が低い・バッジが左端に寄りすぎ・ブロック高さ）
- 根拠: `impl-pc-04-point-shoot.png` vs `shots/pc-05-point-eating.png`
- 修正案: `.lp-page .lp-point__plate{height:min(54vw,640px)}` と `.lp-page .lp-point__badge{margin-left:clamp(24px,18%,220px)}`。

### 5. 循環帯 `.lp-cycle` — ⚠️
- 参照（`-cycle`）: **`--color-primary` の色帯**（青地）で `__business` を載せる。PC 高 1566。
- 実装: 地が `--pale-2`（#f4f7fc）の白っぽい帯、見出し 34px、PC 高 **834**。色帯になっていない。
- 判定: ⚠️
- 根拠: `impl-pc-05-cycle.png`（要素スクショのため描画は薄いが背景色は evaluate 実測 `rgb(244,247,252)`）vs `shots/pc-07-point-cycle.png`
- 修正案: `.lp-page .lp-cycle{background:var(--primary);color:#fff}` ＋上下に `.lp-wave--primary` を追加。

### 6. DAILY `#daily` — ✅（密度 ⚠️）
- 参照: 主色帯、01〜09 を**大小 2〜3 サイズで 1 行 2〜3 枚の段違い**、番号は写真右上の白丸、写真下に白 2 行キャプション、一部にピルのラベル、写真間に足跡点線、上下に波形。PC 高 2926。
- 実装: 主色帯 ✅、英字キャプション＋h2 ✅、写真右上に**白い正方形**の番号タグ ✅、キャプション下付き ✅、写真左下に工程タグ（「撮る」）✅、上下波形 ✅。PC 高 **2998** ✅（ほぼ一致）。
- ただし **1 行 2 枚・サイズ 2 種のみ**で参照の 3 段階の大小混在に届かず、**足跡破線がページ全体で 3 本しかない**（参照は区画内に多数）。SP 高 4163（参照 3257・+28%）。
- 判定: ✅（構図）／⚠️（密度・SP高さ）
- 根拠: `impl-pc-06-daily.png` vs `shots/pc-08-daily.png`
- 修正案: `.lp-daily__item` に `--w` を 3 段階（46%/33%/26%）で配り、`.lp-daily__trail{border-top:1px dashed rgba(255,255,255,.5)}` を item 間に 4〜6 本追加。

### 7. FEE `#fee` — ✅
- 参照(KOME): 上部に浮遊イラストの余白帯（約500px）→ 中央に巨大パネル（小見出し→大見出し→英字→本文→写真→ドット3→CTA2）→ 下端は主色の波。PC 高 2635。
- 実装: `.lp-fee__sky`（浮遊 ill）→ `--pale` の直角パネル 1155×1355（幅 91%）内に eyebrow「料金について」→ h2 →`PRICE / FREE OF CHARGE`→ lead → **¥0 カード（86px・Noto Sans＝`--ui`・主色）→ note →`lp-fee__caution`（15px・同一カード内＝同一視野）** → 写真 3:2 → `lp-marks` 3 点 → CTA 2 本（btn-line ＋ btn-ghost）→ 下端 `.lp-wave--primary` **72px**（参照 7.2rem＝72 ✅）。PC 高 **1618**（-39%）。
- 判定: ✅（順序・要素すべて一致。高さのみ ⚠️）
- 根拠: `impl-pc-07-fee.png` vs `shots/pc-09-kome.png`
- 修正案: `.lp-page .lp-fee__sky{min-height:440px}` ＋ `.lp-fee__panel{padding-block:110px}`。

### 8. CASES `#cases` — ⚠️
- 参照(COCO): **水色帯の `__intro`** → 中央見出し（和文＋極小英字）→ **2 行の大キャッチ（後半を主色）→ 本文 2 行** → item3 件（写真左 40%／ロゴ＋見出し＋本文右、右上に「詳しく見る」）→ 住所ブロック → **水色帯の `__outro`**。PC 高 3775。
- 実装: 白地、`usage images` → h2「こんなふうに使えます」→ **sub 1 行のみ** → `MODEL_CASE_NOTE`（カード群より手前 ✅）→ 3 件（chip 先頭 ✅／肖像 1:1 ✅／`caseName`（仮名）✅／persona／tag ✅／quoteShort ✅／facts 3 値 ✅／**amount 非表示 ✅**／「詳しく見る」右上 ✅、grid 444/666 ≒ 40:60 ✅）→ 「対応エリア: 東京都・千葉県・埼玉県・神奈川県（順次拡大）」＋「会社概要を見る」✅（住所・電話なし ✅）。PC 高 **2322**（-38%）。
- **欠落: §2.5 が要求する「2 行の大キャッチ（後半を主色）＋本文 2 行」。参照の `__intro`/`__outro`（水色帯・波形 2 か所）も無く、CASES 前後の帯の切り替わりが消えている。**
- 判定: ⚠️
- 根拠: `impl-pc-08-cases.png` vs `shots/pc-11-coco-main.png` `shots/pc-10-coco-intro.png`
- 修正案: h2 の下に `.lp-cases__catch`（2 行・後半 `color:var(--primary)`）＋本文 2 行を追加し、`#cases` の前後に `.lp-wave--pale` の帯を 1 本ずつ挿す。

### 9. BIZ `#biz` — ✅
- 参照(FARM): 淡色地＋テクスチャ＋上端波形、全幅集合写真(92%) → 2 列（左 4 行大見出し・強調語が主色／右 本文）→ カード 3 枚 → 中央 CTA 1 本。PC 高 2447。
- 実装: 地 `--pale-2` ✅、全幅写真 1061px（84%）✅、`FOR BUYERS` → 左「買取業者の方へ。／カタヅケに参加**しませんか**。」（強調 `参加` 主色 ✅）／右 本文＋β注記 ✅、カード 3 枚（359px×3）✅、CTA「業者登録の詳細を見る」→`/business` ✅、「審査制・登録無料」✅。PC 高 **2023**。
- **コピー重複: 「顧客と業者、双方に無駄がない。だから長く続く。」と「一括出品への入札で、効率的な仕入れルートを開拓できます。」が、上部リード部とカード本文に各 2 回ずつ出る。**
- 判定: ✅（構図）／⚠️（重複）
- 根拠: `impl-pc-09-biz.png` vs `shots/pc-14-farm.png`
- 修正案: カード 1・3 の本文を `biz-tag` 側の短文に差し替え、リードの重複文を削る。

### 10. FOOTER `.lp-footer` — ⚠️
- 参照: 主色の波形上端 → **淡色地(#f4f4f4)**、左にロゴ、中央にナビ 2 列、**右に pagetop（footer 内に absolute・幅 45.6%相当×290px の主色ブロック）**、最下段 ©。PC 高 838。
- 実装: 主色の波形上端 ✅（90px）、**地は白(#fff)**、左にロゴ＋対応エリア 1 行 ✅、ナビ 2 列（主色の正方形矢印＋ラベル）✅、`© 2026 カタヅケ` ✅、電話番号なし ✅、必要リンク 10 本すべて ✅。PC 高 **472**。
- **pagetop が footer 内ではなく `position:fixed` の 92×172 チップで、KV 以降ずっと画面右下に居座る。実測で POINT の主写真・CASES カード・BIZ カードに重なっている（`impl-pc-04/08/09` 参照）。参照の「フッター右端のブロック」とは別物。**
- 判定: ⚠️
- 根拠: `impl-pc-10-footer.png` `impl-pc-13-pagetop.png` vs `shots/pc-15-footer.png` `shots/pc-21-pagetop-button.png`
- 修正案: `.lp-page .lp-footer{background:var(--pale-2)}`、`.lp-pagetop{position:absolute;right:0;top:0;width:36%;height:290px}` を `.lp-footer{position:relative}` 配下へ移す（fixed をやめる）。

### 11. MENU オーバーレイ — ✅
- 参照: 淡色地、左 45% に大写真、右にリンク 2 列（主色の矢印マーク＋ラベル）、横長 CTA パネル、白パネル 2 枚、最下段にロゴ＋所在地、右上 MENU/CLOSE。700ms フェード。
- 実装: `grid-template-columns: 576px 704px`（**45%/55% ✅**）、左に `top-cta-band.webp` 全面 ✅、右 2 列の矢印リンク 11 本 ✅、全幅 `btn-line`（LINEではじめる（無料））✅、白パネル 2 枚（利用イメージ／買取業者の方へ）✅、ロゴ＋「東京都・千葉県・埼玉県・神奈川県（順次拡大）」✅、MENU/CLOSE ✅。`aria-expanded` 切替 ✅ / `aria-controls="lp-sitemap"` ✅ / `transition: opacity .7s, visibility .7s` ✅（参照 `--transition-sitemap` 700ms）/ `body{overflow:hidden}` ✅ / Esc で閉じ、フォーカスがボタンに復帰 ✅。SP は 1 列 370px に収束。
- 判定: ✅（本レビューで最も忠実な区画）
- 根拠: `impl-pc-12-menu-open.png` `impl-sp-11-menu-open.png` vs `shots/pc-25-sitemap-open.png`

---

## 装飾・モーション・トークン（A-3/4/5/6）

| 項目 | 参照 | 実装実測 | 判定 |
|---|---|---|---|
| 波形上端の数 | 6 区画＋footer | `mask-image` 要素 8 個（230×6／72／90） | ✅ |
| 波形高さ PC | about/point/daily/coco 23.0〜23.1rem、kome 7.2rem | 230px×6、72px、90px | ✅ |
| 波形高さ SP | 5.8rem／1.9rem | 58px×6、19px、28px | ✅ |
| テクスチャ | `bg_texture.webp` 乗算タイル | `.lp-texture` に feTurbulence data URI・`opacity:.06` | ✅ |
| 揺れ | step-rotate3 3.5s / rotate4 4s / fluffy 7s / fluffy2 8s / fluffy3 9s、全て `steps(1)` | `lp-sway 3.5s steps(1)`×5、`lp-sway2 4s steps(1)`×5、`lp-float 7s steps(1)`×3、`lp-float2 8s steps(1)`×4、`lp-float2 9s steps(1)`×3（計 20 要素） | ✅ 秒数・timing とも一致 |
| ドットひし形クラスタ | 参照の点描 | 4 クラスタ | ✅ |
| 足跡の破線 | 各区画に多数 | ページ全体で `border-style:dashed` は **3 本** | ⚠️ |
| スライダー遷移 | 1600ms（`-slow`） | `opacity 1.6s, transform 3.84s` | ✅ |
| スライダー間隔 | 6000ms | **未計測**（下記「確認できなかった項目」） | ─ |
| Reveal | fadeup 500ms | `.rv--up` 49 個すべて `.in` 到達、`opacity:0` は `html.js-rv` 配下のみ（lp.css 74-89） | ✅ |
| 主色 | #05a277 → #1447e0 | `rgb(20,71,224)` | ✅ |
| 淡色面 | #f4f4f4 → `--pale-2` | `rgb(244,247,252)` | ✅ |
| 明朝見出し | Zen Maru → `--serif` | h1/h2 とも Noto Serif JP、h1 54px | ✅ |
| 数値は `--ui` | ─ | `¥0` = Noto Sans JP 86px | ✅ |
| 番号は `--en-display` | Comfortaa | `.lp-num` = Libre Baskerville、英字キャプションは Montserrat（`--en`） | ✅ |
| 角丸 0 | 1.8rem/円 | **非 0 は 6 個のみ、すべて `.lp-slider__dot`(50%)** | ✅ |
| `!important` / `100vw` | ─ | lp.css に 0 件 | ✅ |
| keyframes 名 | ─ | `lp-sway/lp-sway2/lp-float/lp-float2` のみ（`lp-` 接頭辞） | ✅ |
| 共通クロム抑止 | ─ | `.lp-page` 直下は lp- 系のみ。SiteHeader/Dock/`.site-frame` 非出現 | ✅ |
| 外部参照 | ─ | `coco-terrace` 文字列 0 件、`target=_blank` 0 件、画像 36 src すべて HTTP 200 | ✅ |

## レスポンシブ（SP 390）
- `scrollWidth 380 === clientWidth 380` — **横スクロールなし ✅**。ただし `.lp-ill--f1/f2` の 4 要素が right=403〜407 とビューポート外へ出ており（親の overflow で切れている）、親の `overflow` を外すと即座に横スクロールが発生する脆い状態。
- `.lp-case` / `.lp-biz` カードとも 1 列 344px ✅。MENU は 1 列 370px。
- **浮遊CTA が SP では `bottom:0;right:0` の下部固定に変わる。参照は PC/SP とも右上固定（`reference-spec` (b)）。** 判定 ⚠️（UX 的には妥当だが忠実度としては相違）。
- KV ドットは SP で `flex-direction:row`（横並び）に変化。参照 PC は縦・右端。⚠️ Low。

---

## 重大度別まとめ

### Critical
- なし（表示崩壊・404・横スクロール・禁止語・金額露出・打消し欠落はいずれも検出されず）。

### High
1. **pagetop が `position:fixed` の常時表示チップで、本文を恒常的に覆う**（POINT の主写真・CASES カード・BIZ カードに重なることを実測）。参照は footer 内 absolute。→ `.lp-pagetop` を `.lp-footer` 配下の `position:absolute` に変更。
2. **垂直リズムが参照の 77%**（PC 総高 19,141 / 24,945）。特に MESSAGE -33%、ABOUT -29%、POINT 各 -41%、FEE -39%、CASES -38%。参照LPの体験の核である「余白の量」が再現されていない。→ 各区画の `padding-block` と item 間 margin を 1.4〜1.7 倍。
3. **KV スライダーのドット列がビューポート右端でなく写真枠の脇（x=896）**。§2.5 の「右端中央に縦並び」に反し、KV の"額縁感"が出ない。→ `.lp-slider__dots` を `right:24px` の absolute に。

### Medium
4. ABOUT の強調語が `rgb(143,180,255)`（主色帯上でコントラスト約 3.6:1）。参照の黄のような強い対比になっていない＋24px 未満に同色を使えば AA 未達。
5. 循環帯 `.lp-cycle` が淡色地。参照 `-cycle` は主色の色帯。
6. CASES に §2.5 必須の「2 行の大キャッチ（後半 主色）＋本文 2 行」が無い。参照の水色 `__intro`/`__outro` 帯（波形 2 か所）も消失。
7. FOOTER の地が白。参照/§2.5 は淡色地。
8. SP KV が 682px で 844px のビューポートを満たさない（参照 828px）。SP DAILY は逆に 4163px（参照 3257px・+28%）で、SP の縦バランスが参照と噛み合っていない。

### Low
9. DAILY の写真サイズが 2 種のみ（参照は 3 段階混在）。足跡の破線がページ全体で 3 本のみ。
10. POINT の色面が 333px（参照は約 700px）でバッジが左端に密着。
11. BIZ でリード文とカード本文にコピーの重複 2 組。
12. MESSAGE の下端が単層波形（参照は二重の丘）。
13. 浮遊CTA が SP で下部固定に変わる（参照は右上固定）。SP でドット列が横並びに変わる。
14. `.lp-ill--f1/f2` が SP で親をはみ出している（現状は overflow で吸収）。

---

## 確認できなかった項目（未検証リスク）
1. **スライダーの自動送り間隔 6000ms を直接計測していない**（遷移 1.6s は CSS で確認済み）。ホバー／フォーカス／`document.hidden` での停止、一時停止ボタンの `aria-pressed` 挙動も未検証。
2. **`prefers-reduced-motion: reduce` の実挙動**（揺れ停止・自動送り停止・本文が消えないこと）をエミュレーションで確認していない。CSS 側に `html.js-rv` ガードがあることのみ確認。
3. **console error の有無**を未確認（`navigate` 時に console ログファイルが生成されたが読んでいない）。
4. **375 / 768 / 1440px** での横スクロール・レイアウトは未検証（390 と 1280 のみ）。
5. **SP の区画別比較は KV と MENU のみ**。MESSAGE / ABOUT / POINT / DAILY / FEE / CASES / BIZ / FOOTER の SP スクショ比較はツール呼び出し上限のため未実施（高さの数値比較のみ実施）。
6. `#biz` 上端の波形がどのマスク要素に対応するか未特定（マスク 8 個の帰属を全部は追えていない）。
7. `npx tsc --noEmit` / `npx eslint` は本レビューでは未実行（B 節担当範囲）。
8. ホバー状態（`opacity:.8/.85` 規則）、Tab 順の網羅、スクリーンリーダー読み上げは未検証。
9. コピーの**一字一句**照合は §4 出典ファイルとの機械的 diff まで行っておらず、目視と抜き取りのみ（禁止語スキャンは実施し、ヒットは `MODEL_CASE_NOTE` 内の正規の打消し表示のみ）。
