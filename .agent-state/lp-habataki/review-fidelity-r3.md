# /lp 忠実度レビュー r3（独立検査・敵対的・最終判定周）

検査日: 2026-09-17 / 対象 `http://localhost:3100/lp`（起動済み dev）/ PC 1280x800・SP 390x844（Playwright MCP）
実装スクショ: `.agent-state/lp-habataki/shots-impl-r3/`（`r3-pc-01..08` / `r3-sp-01..07`）
基準: `fix-r2.md` A1〜A3・B1〜B4・C1〜C6 ／ `review-fidelity-r2.md`(3) 回帰項目 ／ `build-brief.md` §2.5 ／ `shots/pc-*.png`・`shots/sp-*.png`

**総評: fix-r2 の 13 件中 10 件は実機で直った。A1（循環帯イラスト 6px 潰れ）と A3（KV フルブリード化）は完全に是正され、構図の最大差分は解消。B1 の POINT 色面も h2 が面内に入り「空の色面」は縮小。一方で A2 の浮遊CTA は形状こそ縦タブ／下部バーになったが、指示の前提（`.lp-container` = 1140px・右余白 70px）が実装と食い違っており（実測 `max-width:1300px` → 1280 では 1270px＝ほぼ全幅）、フッターでは `.lp-pagetop` を 16,240px² 覆う。B4 の FOOTER 高さは 687→688px と実質未修正。よって High 1 件が残り、r3 は不合格。**

---

## (1) fix-r2 判定表（A1〜A3・B1〜B4・C1〜C6）

凡例: ✅直った ／ △部分的 ／ ❌直っていない ／ ⚠別の問題を生んだ

| # | 指摘 | 判定 | 実機の実測根拠 |
|---|---|---|---|
| A1 | 循環帯イラストを `padding:10px`＋`width:clamp(72px,9vw,110px)`、img ≥50px | ✅ | PC: タイル 110×110・`padding:"10px"`・`img` 描画 **90×90px**（6 枚すべて同値、`naturalWidth 480`）。SP: `img` 132×132。判定条件 `>=50` を満たす。`r3-pc-04-cycle.png` で 6 点とも白タイル内に視認可 |
| A2 | 浮遊CTA を PC=右端縦タブ／SP=下部全幅バーに | △⚠ | **形状は指示どおり**: PC `.lp-float-cta` `position:fixed; right:0px; top:160px`・実測 **56×358px**・`.btn-line__label` `writing-mode:vertical-rl`・`.btn-line__sub` `display:none`・`.lp-float-cta__alt` `vertical-rl` 幅 56px・LINE 緑地。SP `position:fixed; bottom:0; left:0; right:0`・**380×57px**・LINE（flex）＋「よくある質問を見る」。MENU 開時 PC/SP とも `visibility:hidden`＋`inert` ✅。**不一致 3 点**: ①高さ 358px（指示 約220px・+63%）②`main` の `padding-bottom` が **0px**（指示 `calc(56px + env(safe-area-inset-bottom))` 未適用）③PC でフッターの `.lp-pagetop` と 16,240px² 重なる（(4) H1） |
| A3 | KV をフルブリード写真スライダー＋淡色 veil | ✅ | `.lp-kv img`: `position:absolute`・`object-fit:cover`・`object-position:"50% 60%"`・実測 1321×832（KV 1270×800 を被覆）。`.lp-kv{min-height:800px}`（=`clamp(640px,100svh,900px)` の 100svh）。`.lp-kv__stage` **消滅**（`false`）。veil = `linear-gradient(rgba(244,247,252,.96) 0px, rgba(244,247,252,.96) 38%, rgba(244,247,252,0) 70%)`（SP は 45%/74%）＝指示と完全一致。h1・英字・sub は写真上。浮遊イラスト 6 点は四隅（右側 3 点の右余白 130/160/208px）。下端の白波形・ドット列（右 24px）維持 |
| B1 | POINT 色面 `min(46vw,520px)`＋h2 を面内へ（色面下の h2 は削除） | ✅ | 3 ブロックとも色面 **660×520px**（`height:"520px"`・幅 = 1270 の 52.0%）。h2 は 3 枚とも `within:true`（例: 撮 h2 rect x266..589 ⊂ 面 x0..660 / y4490..4582 ⊂ 面 y4256..4776）。色は 主色面/`--deep` 面 = `rgb(255,255,255)`、`--pale` 面 = `rgb(32,36,46)` ✅。バッジ 120×120 白地・面内左 115px（指示 `clamp(24px,10%,120px)`）・h2 と非重複。**h2 重複なし**（`.lp-point` 配下 h2 は 3 本＋循環帯 1 本のみ）。SP も同様（面 319×304・バッジ 96px・h2 `within:true`） |
| B2 | CASES intro 帯を 448px に | ✅ | `.lp-cases__intro` = **448px**（指示値ちょうど）。中身は h2「こんなふうに使えます」＋極小英字のみ |
| B3 | KV の `.lp-ill--f1/f2` の衝突解消・`right` ≥60px | ✅ | 右側イラスト 3 点の右余白 **130 / 160 / 208px**。ドット列（x1216–1246, y321–480）・浮遊CTA（x1214–1270, y160–518）のいずれとも矩形交差 0 |
| B4 | 区画高さ残差（POINT撮/選 +gap・FOOTER +40px・SP ABOUT/DAILY +24px） | △❌ | POINT撮 2479→**2532**（-13.3%）✅／POINT選 2115→**2198**（-12.8%）✅／SP ABOUT 2041→**2225**（-14.7%）✅／SP DAILY 2617→**2777**（-14.7%）✅。**FOOTER 687→688px（+1px・-17.9%）＝実質未修正 ❌**（`padding-block` 実測 204.8px/89.6px） |
| C1 | 主色帯上の `.lp-en` を `rgba(255,255,255,.92)` に | ✅ | ABOUT 見出し／`three-way satisfaction`／`from listing to pickup` の 3 箇所とも `rgba(255,255,255,0.92)` on `rgb(20,71,224)` → **コントラスト 6.16:1**（r2 は 3.32:1） |
| C2 | `.lp-about__body .lp-en` を .80 以上へ | ✅ | `rgba(255,255,255,0.82)` ×3（01/02/03）→ 5.21:1 |
| C3 | KV ドット列をビューポート右端 24px に確定 | ✅（実機） | `.lp-slider__ctrl` の右余白 **24px**（r2 は 45px）。※lp.css / LpSlider.tsx のコメント文言訂正は実機からは判定不能（(5)-3） |
| C4 | `.lp-footer` を `overflow:clip; overflow-clip-margin:16px` | ✅ | 実測 `overflow:"clip"` / `overflow-clip-margin:"16px"`。pagetop（`top:-11px`）は `r3-pc-07-footer-cta.png` で切れずに描画 |
| C5 | Low 5 件（aria-controls／ドットhover停止／メニュー閉時フォーカス移動／CASES h2 重複／β注記重複） | △ | **aria-controls** ✅ 6 タブすべてに付与・参照先 id 実在（`lp-slide-ex-lot-*`）。**CASES h2 重複** ✅ 解消（intro に h2「こんなふうに使えます」／本文側は `p.lp-cases__catch` のみ）。**β注記重複** ✅ 解消（ページ全体で「β期間中は手数料0円…」は **1 箇所**＝`.lp-biz__note` 15px のみ）。**ドット hover 停止／メニュー閉時のフォーカス移動は未検証**（(5)-1） |
| C6（=C 節 Low 据置き）| ロゴ `inert`／英字 region 名の和文化 | ✅ | MENU 開時の `[inert]` = `A.lp-header__logo` / `DIV.lp-float-cta` / `MAIN` / `FOOTER.lp-footer`（r2 の L3 も解消）。region 名は `aria-label="運営事務局からのメッセージ"`（和文）＋ `aria-labelledby`（`lp-point-shoot`/`choose`/`trust`/`lp-cycle-h`）で見出し参照 |

**集計: ✅ 10 ／ △ 3（A2・B4・C5）／ ❌ 0（ただし A2 に High 1・B4 に FOOTER 未修正が内包）**

---

## (2) 回帰チェック表（`review-fidelity-r2.md`(3) で ✅ だった項目）

| 項目 | r2 | r3 実測 | 判定 |
|---|---|---|---|
| 波形の高さ（PC） | 230×11 / 72 / 128 | `.lp-wave` 13 枚: **230×11・72・128** | ✅ 維持 |
| 揺れの keyframes | `lp-sway/lp-sway2/lp-float/lp-float2` の 4 種のみ | 同 4 種のみ（他は `kdz-spin/spin/bar-grow/shimmer`＝LP 外）。稼働アニメ **22** | ✅ 維持 |
| 角丸 0 | 非 0 は `.lp-slider__dot` 6 個のみ | 完全同一（6 個・すべて dot・50%） | ✅ 維持 |
| MENU オーバーレイ a11y | `inert`＋タブ循環＋Esc 復帰 | `inert` 4 要素（ロゴ追加で **改善**）・`body{overflow:hidden}`・Esc で `aria-expanded=false`／`inert` 0 個／フォーカス `.lp-header__menu` へ復帰 | ✅ 改善 |
| 打消し表示（`MODEL_CASE_NOTE`）の位置 | カード群より手前 | `.lp-cases__catch` 直下・カード 3 件より上（`r3-pc-06-cases.png`） | ✅ 維持 |
| 横スクロール無し | 375/390/768/1280/1440 で `sw===cw` | SP 390: `scrollWidth 380 === clientWidth 380` ✅。PC 1280: 1270===1270 ✅ | ✅ 維持（※(5)-4 の脆さ注記あり） |
| スライダー自動送り | 7 秒で index 3→4 | 7 秒で `aria-selected` が index **1→2** に移動 | ✅ 維持 |
| フォーカス循環 | NAV 内で循環 | MENU 開時に nav 外の focusable がすべて `inert`（ロゴ含む）＝構造的に循環が保証される。CLOSE ボタンのみ header に残る | ✅ 維持（Tab 実押下の全周回は未再実施・(5)-2） |
| コンソール | error 0 | **error 0**（`warnings` は Next dev の画像属性警告のみ） | ✅ |

---

## (3) 区画高さ表（PC 1280・単位 px・参照は `build-brief`/`reference-spec` の実測値）

| 区画 | 参照 | r2 | **r3** | r3 の差% | 判定（−15%〜+10%） |
|---|---|---|---|---|---|
| KV `.lp-kv` | 900 | 975 | **800** | **-11.1%** | ✅ |
| MESSAGE `.lp-message` | 976 | 950 | **950** | -2.7% | ✅ |
| ABOUT `#about` | 2829 | 2506 | **2506** | -11.4% | ✅ |
| POINT 撮 `--primary` | 2922 | 2479 | **2532** | **-13.3%** | ✅（r2 -15.2% から回復） |
| POINT 選 `--deep` | 2520 | 2115 | **2198** | **-12.8%** | ✅（r2 -16.1% から回復） |
| POINT 安 `--pale` | 1566 | 1670 | **1716** | +9.6% | ✅（+10% の境界すれすれ） |
| 循環帯 `.lp-cycle` | 目標 600〜700（fix-r2 §D） | 1064 | **1064** | **+52%（700 比）** | ❌ 新規（(4) M1） |
| DAILY `#daily` | 2926 | 3122 | **3122** | +6.7% | ✅ |
| FEE `#fee` | 2635 | 2316 | **2316** | -12.1% | ✅ |
| CASES `#cases` | 3775 | 3416 | **3280** | -13.1% | ✅（intro 詰めで -9.5%→-13.1% に悪化・帯内） |
| BIZ `#biz` | 2447 | 2112 | **2112** | -13.7% | ✅ |
| FOOTER `.lp-footer` | 838 | 687 | **688** | **-17.9%** | ❌ B4 未修正 |
| **総高** | 24945 | 23411 | **23284** | **-6.7%** | ✅ |

### SP（390）

| 区画 | 参照 | r2 | **r3** | r3 の差% | 判定 |
|---|---|---|---|---|---|
| KV | 828 | 844 | **844** | +1.9% | ✅ |
| MESSAGE | 1049 | 1022 | **1022** | -2.6% | ✅ |
| ABOUT | 2609 | 2041 | **2225** | **-14.7%** | ✅（境界・r2 -21.8% から回復） |
| POINT 全体 | 7928 | 6966 | **7216** | -9.0% | ✅ |
| DAILY | 3257 | 2617 | **2777** | **-14.7%** | ✅（境界・r2 -19.6% から回復） |
| 循環帯 / FEE / CASES / BIZ / FOOTER | 参照値なし | ─ | 598 / 1391 / 3214 / 2141 / 842 | ─ | 参照不在（(5)-5） |
| 総高 | 24135 | 21148 | **21671** | -10.2% | ✅ |

---

## (4) 忠実度の区画別総括（`build-brief.md` §2.5・`shots/` 対比）

| 区画 | 判定 | 根拠 |
|---|---|---|
| KV | ✅ | 参照 `pc-02-kv.png` の「画面いっぱい」に対し、r2 の中央 3:2 額縁が撤去されフルブリード写真＋上部 veil に。キャッチ 2 行＋英字＋sub・右端縦ドット・浮遊イラスト 6 点・下端白波形・左上ロゴ・右上 MENU すべて一致 |
| MESSAGE | ✅ | 高さ -2.7%。二重の丘（`.lp-wave--white` ×2） |
| ABOUT | ✅ | 主色帯・3 item 交互・英字 01/02/03・白マーカー |
| POINT（撮/選/安） | ⚠ | 色面に h2 が入り「空の色面」は 794→520px に縮小したが、**色面の下半分（バッジ y220..340 と h2 y234..326 より下、約 180px）は依然として無地**。参照 `pc-05-point-eating.png` は色面上に写真・見出しが食い込む |
| 循環帯 | ⚠ | イラスト 6 点は可視化（A1 ✅）だが帯高 1064px は fix-r2 §D の目標 600〜700px を大きく超過。SP は 598px で目標内＝**PC と SP で設計値が食い違っている** |
| DAILY | ✅ | +6.7%・破線・番号タグ |
| FEE | ✅ | -12.1% |
| CASES | ✅ | intro 448px・大キャッチ・打消し表示の位置 |
| BIZ | ✅ | -13.7%・β注記 1 箇所 |
| FOOTER | ❌ | -17.9%（未修正）。加えて右半分が浮遊CTA と衝突（H1）、`特定商取引法に基づく表記` が 2 行折返しで隣列と行頭不揃い（r2 L4・未対応） |
| MENU オーバーレイ | ✅ | `r3-pc-08-menu-open.png` / `r3-sp-06-menu-open.png`。CTA 非表示・`inert` 4 要素 |

---

## (5) 実装者が確認を求めた 4 点への回答

### ① KV の veil 下端付近（y≈350）に載る sub 文字のコントラスト → **合格（AA・実質 AAA）**

測定法: 各スライドの `<img>` を canvas に `drawImage` し、`.lp-kv__sub` の矩形（x363, y325, 544×29）直下の画素を平均。veil の α を実 CSS（`.96` 0–38%、70% で 0）から y で解析的に求め（**sub 中心 y=339.5 → α=0.828**）、`rgba(244,247,252,α)` と合成して WCAG コントラストを算出。

| スライド | 写真平均 | 暗画素率(L<0.25) | 合成背景 | sub `rgb(69,78,89)` とのコントラスト |
|---|---|---|---|---|
| ex-lot-jikka | 159,150,130 | 38.4% | 229,230,231 | **6.76:1** |
| ex-lot-moving | 216,204,187 | 20.3% | 239,240,241 | 7.40:1 |
| ex-lot-closet | 142,141,140 | 41.6% | 226,229,233 | **6.68:1** |
| ex-lot-ihin | 151,135,115 | 55.1% | 228,228,228 | **6.64:1** |
| ex-lot-rearrange | 182,174,166 | 31.0% | 233,234,237 | 7.02:1 |
| ex-lot-kitchen | 179,171,163 | 13.2% | 233,234,237 | 7.02:1 |

最悪ケースの理論値（写真が真っ黒 = `rgb(0,0,0)` の画素）でも合成は `rgb(202,205,209)` で **5.15:1** ＝ AA（4.5:1）を割らない。**6 枚すべて安全。**
参考: 同 veil 帯の全幅プローブ — y=350 α=.750 合成 `229,231,234`（vs `--ink` 12.53・vs 主色 5.64）／y=450 α=.375 合成 `209,200,191`（vs 主色 4.23）／y=550 α=0 合成 `175,161,148`（vs 主色 **2.78**）。**veil の外（y≳500）に主色や muted 色の文字を今後置くと即落ちる**ため、KV 下半分は白文字か配置禁止で運用すること。

### ② POINT の h2 が色面（幅 52%）内に収まっているか → **3 ブロックとも収まっている ✅**

| ブロック | 色面 rect | h2 rect | 面内 | h2 色 |
|---|---|---|---|---|
| 撮 `--primary` | 0,4256,660,520 | 266,4490,323,92 | true | `rgb(255,255,255)` |
| 選 `--deep` | 0,6787,660,520 | 266,7044,155,46 | true | `rgb(255,255,255)` |
| 安 `--pale` | 0,8985,660,520 | 266,9219,323,92 | true | `rgb(32,36,46)` |

面幅 660px = ビューポート 1270 の **52.0%**（指示どおり）。バッジ（120×120・白地）は面内左 115px・上 220px で h2 と非重複。SP でも 3 枚とも `within:true`（面 319×304・バッジ 96px）。

### ③ 区画高さ（撮/選/安、SP の ABOUT・DAILY） → **4 件回復・1 件は境界内**

撮 **-13.3%**（r2 -15.2%）／選 **-12.8%**（r2 -16.1%）／安 **+9.6%**（+10% 境界）／SP ABOUT **-14.7%**（r2 -21.8%）／SP DAILY **-14.7%**（r2 -19.6%）。いずれも −15%〜+10% の帯内だが、安・SP ABOUT・SP DAILY の 3 件は **境界から 0.3〜0.4pt しか余裕がない**。以後 lp.css の余白を触ると即帯域外に落ちる。

### ④ 循環帯タイル内 img の描画幅 ≥50px → **合格 ✅**

PC: タイル 110×110・`padding "10px"`・`img` 描画 **90×90px** ×6 枚（`naturalWidth 480`）。SP: `img` **132×132px**。`r3-pc-04-cycle.png` で 6 点とも視認可。

---

## (6) 新規指摘

### High

**H1. PC の浮遊CTA（縦タブ）がフッターの `.lp-pagetop` を覆う（r1 High-1 / r2 H2 の 3 度目の再発形）**
- セレクタ: `.lp-float-cta`（`position:fixed; right:0; top:160px`・56×358px）× `.lp-pagetop`
- 期待: fix-r2 A-2「1280px では container（1140px）の右余白 70px に収まるため本文と重ならない」
- 実測: **`.lp-container` の `max-width` は 1140px ではなく `1300px`** → 1280 ビューポートでは container 幅 **1270px（left 0 / right 1270）＝ほぼ全幅**。指示の前提が成立していない。ページ最下部（`scrollY 22484`）で重なり面積は `.lp-pagetop` **16,240px²** / `.lp-footer__inner` 11,239px² / `.lp-footer__copy` と x 方向 56px。`r3-pc-07-footer-cta.png` で LINE 縦タブと白い FAQ タブが「PAGE TOP」ブロックの右端に被さっているのが目視できる
- 影響: 操作要素どうしの重なり（クリック可能領域の奪い合い）。本文テキストとの被りは偶然（container の内側パディングで免れているだけ）で、レイアウト変更のたびに再発する構造
- 修正案: (a) `.lp-float-cta` を `position:fixed` のまま `right:0` ではなく `.lp-page` の右端から `max(0px, (100vw - 1140px)/2)` 分内側に置く、または (b) `.lp-footer` が viewport 内に入ったら CTA を `visibility:hidden`（IntersectionObserver / `animation-timeline` の scroll 連動）、または (c) `.lp-pagetop` の右端を CTA 幅 56px 分だけ内側へ（`margin-right:64px`）。**(b) が最も再発しにくい**

### Medium

**M1. 循環帯 `.lp-cycle` の高さが PC 1064px と目標（fix-r2 §D「600〜700px」）を +52% 超過し、SP（598px）と設計が食い違う**
- セレクタ: `.lp-cycle`（PC 1064px / SP 598px）／`r3-pc-04-cycle.png`
- 期待: fix-r2 §D「6 タイル＋見出しで 600〜700px を目標とし、それ以上は伸ばさない」
- 実測: PC **1064px**（変更なし・r2 と同値）。A1 でイラストが見えるようになった分、青帯の空白が目立つ構図は改善したが高さ自体は据置き
- 修正案: `.lp-cycle` の `padding-block` を -180px、または `.ill-loop` の行高を詰めて 700px 以内へ

**M2. SP で `main` に `padding-bottom` が入っていない（指示 A-2 の未適用）**
- セレクタ: `main`（`padding-bottom: "0px"`）／下部バー `.lp-float-cta` 380×57 @ `bottom:0`
- 期待: fix-r2 A-2「`main` に `padding-bottom:calc(56px + env(safe-area-inset-bottom))` を付けて末尾が隠れないように」
- 実測: 最下部（`scrollY 20827`）で footer 末尾 `© 2026 カタヅケ` の bottom **740px** ／ バー上端 **787px** → **今は 47px の余裕があり隠れていない**（要件 5 の SP 条件は結果的に満たす。`.lp-footer` 配下の被り要素 0 件）。ただしこれは footer 自身の下余白に偶然救われているだけで、①実機 iOS の `env(safe-area-inset-bottom)`（最大 34px）でバーが高くなる、②footer の `padding-block-end`（89.6px）を詰める、のどちらかで即座に © が隠れる
- 修正案: 指示どおり `main{padding-bottom:calc(56px + env(safe-area-inset-bottom))}` を入れる（PC では `@media (min-width:860px)` で 0 に戻す）

**M3. PC の縦タブ高さ 358px が指示値（約 220px）の +63%**
- セレクタ: `.lp-float-cta`（56×358px・y160–518）
- 期待: fix-r2 A-2「幅 60px・高さ約 220px」
- 実測: 「LINEではじめる」縦書き 9 文字＋FAQ 縦書き 8 文字が積み上がって 358px。KV では写真の右 1/4 を 358px にわたって縦断する
- 修正案: FAQ タブのラベルを「よくある質問」6 文字に短縮、または LINE タブを `height:220px` 固定＋文字を `font-size:12px` に

**M4. POINT 色面の下半分が依然として無地（r2 M1 の残り）**
- セレクタ: `.lp-point__plate`（660×520）。面内の要素はバッジ（y220–340）と h2（y234–326）のみで、**y340–520 の約 180px（面積の 35%）が空**
- 期待: 参照 `shots/pc-05-point-eating.png` は色面に写真・見出しが食い込む
- 実測: fix-r2 B-1 は「h2 を面内に」までしか要求しておらず指示は満たしているが、参照の密度には届いていない
- 修正案: `01` 主セルの写真の上端を色面に 120px 食い込ませる（`margin-top:-120px; position:relative`）

### Low

- **L1** FOOTER ナビ「特定商取引法に基づく表記」が 2 行折返しで隣列と行頭が不揃い（r2 L4・fix-r2 に採録されず未対応）。`r3-pc-07-footer-cta.png` で確認。→ 列幅 +40px
- **L2** ABOUT のマーカー 2 系統（`em` と `span.lp-mk`）の色差（r2 L1・fix-r2 に採録されず未対応）
- **L3** SP で `.lp-slider__slide`（395×878・x -8）が `clientWidth 380` を 7px はみ出すが `.lp-kv` の overflow で吸収され `scrollWidth === clientWidth`。横スクロールは発生しないが、KV の overflow 指定を外すと即再発する

---

## (7) 確認できなかった項目（未解決リスク）

1. **`prefers-reduced-motion: reduce` の実挙動**（3 周連続で未検証）。CSS 側に `@media (prefers-reduced-motion)` を含む条件付きルールが **8 件**存在することは `document.styleSheets` から確認したが、Playwright MCP からメディア特性をエミュレートできないため「reduce で揺れと自動送りが止まり、かつ本文が消えない」ことは**依然として未実証**。→ `npx playwright test` で `reducedMotion:'reduce'` コンテキストを 1 本書くのが最短。
2. **fix-r2 C-5 の Low 2 件が未検証**: ①ドット上ホバーでの自動送り停止 ②メニュー内アンカー押下で閉じた時にフォーカスがアンカー先の見出し（`tabIndex=-1`）へ移ること。いずれもツール呼び出し予算の都合で実行せず。**実装されている保証はない**。
3. **C-3 のうち「lp.css と LpSlider.tsx のコメント訂正」はソース未読のため未判定**（実機からは検出不能）。実機のドット位置 24px は ✅。
4. **フォーカス循環の Tab 全周回を r3 では再実行していない**。`inert` の付与状況（nav 外の focusable が全て inert）から構造的に成立すると判断した推論であり、実押下による確認ではない。
5. **SP の参照高さは KV/MESSAGE/ABOUT/POINT/総高 しか資料に無い**。循環帯・FEE・CASES・BIZ・FOOTER の SP 判定は実測値の記録のみ。
6. **循環帯の目標高さは fix-r2 §D の「600〜700px」を採用**した（`reference-spec.md:198` の 478px と `review-fidelity-r1.md:45` の 1566px の矛盾はリーダー裁定で解消済みと解釈）。
7. **`npx tsc --noEmit` / `npx eslint` は未実行**（検査官の担当範囲外）。
8. **ホバー状態（`opacity:.8/.85`）・スクリーンリーダー読み上げ・コピーの一字一句 diff は未実施**（3 周とも未実施）。
9. **KV veil のコントラストは「文字矩形内の平均画素」で評価**。局所的に最も暗い画素での最悪値は理論上限（5.15:1）で代用しており、実際の文字グリフ単位の測定ではない。
10. **`.lp-container` の `max-width:1300px` が意図的か不明**。fix-r2 は 1140px を前提に指示を書いており、どちらが正しい仕様かはリーダーの確定が必要（H1 の修正方針がこれに依存する）。

---

## (8) 総合判定

**不合格（High 1 件が未解消）。**

- fix-r2 の A1・A3・B1・B2・B3・C1・C2・C3・C4・C5（主要 3 件）＝ **10 件が実機で直った**
- **A2 は形状のみ直り、前提（container 1140px）が事実と異なるため PC フッターで新たな重なり（H1・16,240px²）を生んだ**
- **B4 の FOOTER 高さ（-17.9%）は 1px しか動いておらず未修正**
- 回帰は 0 件（波形・keyframes・角丸・MENU a11y・打消し位置・横スクロール・自動送り・console error 0 すべて維持、MENU a11y はロゴ `inert` 追加で改善）

合格条件（High 0）に到達するには、最低限 **H1（CTA × pagetop）** と **B4 の FOOTER 高さ** の 2 件。M2（`main` の padding-bottom 未適用）は現状値では要件を満たすが構造的に脆いため同時修正を推奨。
