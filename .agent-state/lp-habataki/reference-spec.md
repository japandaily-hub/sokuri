# はばたき農場 LP リバースエンジニアリング仕様書
参照元: https://www.coco-terrace.com/lp/habataki/ （2026-09-17 実機計測）
計測環境: PC = 1280×800 / SP = 390×844（Playwright, Chromium）
スクショ格納先: `.agent-state/lp-habataki/shots/`（PC 26枚: pc-01〜pc-25 + pc-full／SP 18枚: sp-01〜sp-17 + sp-full）
実測できた値はそのまま記載。取得できず類推した値には **（推定）** を付す。

---

## (a) 全体トーン・グリッド・書体・色・角丸・余白

### ページ全高
- PC(1280幅): `body.scrollHeight = 24945px`（`<main class="home-main">` が 0〜24189px、footer が 24107〜24945px）
- SP(390幅): `body.scrollHeight ≈ 24135px`（footer が 23454〜24135px）
- 参考: 既知情報にあった「1024×768で20621px」は別ブレークポイント（1024px未満のSPレイアウト境界より上）での計測値。本仕様は1280/390の2点計測。

### タイポグラフィ
- 本文書体: `"Zen Maru Gothic", sans-serif`（Google Fonts, weight 500 固定）
- 英字書体: `"Comfortaa"`（300–700 可変, ロゴ・英字ラベルに使用）
- ルートfont-size: `html { font-size: 10px }` 基準（実測、1280幅時）。全テキストは rem 指定 ×10px。
- 実測フォントサイズ（1280幅, Zen Maru Gothic, weight 500 固定）:
  | 要素 | class | font-size | line-height | letter-spacing | color |
  |---|---|---|---|---|---|
  | 本文(home-message) | `.home-message__txt` | 14px (1.4rem) | 34px | 0.84px | #222 |
  | 本文(home-kome) | `.home-kome__main__txt` | 13px (1.3rem) | 30px | 0.52px | #222 |
  | カード見出し(coco/farm) | `.home-coco__main__item__catch` / `.home-farm__card__title` | 18px (1.8rem) | 30px | 1.44px | #222 |
  | home-about メッセージ行 | `.home-about__item__catch` | 20px (2.0rem) | — | — | #222 |
  | home-point 大見出し漢字1文字 | `.home-point__item__heading__title__ja` | 40px (4rem) | 40px | — | #fff |
  | home-point 英字ラベル | `.home-point__item__heading__title__en` | 9px (0.9rem) | 9px | — | #fff |
  - 各区画の `__title`/`__catch`/`__en` 系（home-message__catch, home-daily__title, home-kome__intro__catch, home-coco__main__title 等）は **画像置換またはSVGロゴ見出し**（textContentが空、`c-title js-trigger js-fadeup` クラス）で、通常のフォントサイズ指標は意味を持たない（背景画像 or インラインSVGで描画）。実装時はスクショから該当ロゴ画像を切り出すこと。

### 色（CSS変数、common.min.cssの `:root` 相当ブロックより実測）
```
--color-primary:   #0d6fb8   (青。ヘッダーボタン・cycleセクション・pagetopボタン)
--color-secondary: #fbeb2c   (黄)
--color-secondary2:#fefe24   (黄・強調)
--color-tertiary:  #059e74   (緑)
--color-hover:     #0d6fb8
--color-hover2:    #0c66aa
--color-bg:        #f4f4f4   (全体背景 / kome・farmセクション背景)
--color-bg2:       #ffffff
--color-bg3:       #ececec   (SP版サイトマップ背景)
--color-bg4:       #05a277   (about/daily/point-eating の緑帯背景)
--color-bg5:       #f9f9f9
--color-bg6:       #ffe100   (point-living の黄背景)
--color-bg7:       #f0f0f0
--color-bg8:       #75c5f0   (coco__intro の水色背景)
--color-txt:       #222222   (本文)
--color-txt2:      #ffffff   (反転文字)
--color-txt3:      #00a0e9
--color-txt4:      #f0f0f0
--color-txt5:       #05a176  (eating見出し文字色)
--color-txt6:       #e9ce00  (living見出し文字色)
```
- body背景: `rgb(244,244,244)` = `--color-bg`

### 角丸スケール
```
--radius-sm-fixed: 1.8rem（固定、レスポンシブしない小角丸）
--radius-max:      100rem（円形/ピル用）
--radius-rg:        PC 4rem  / SP(≤1023px) 2.5rem
--radius-md:        PC 5rem  / SP(≤1023px) 2.5rem
```
ボタン類は `clip-path` （`--polygon-oval` 等）で角丸オーバル形状を作るケースが多く、単純な `border-radius` でなく多角形クリップの実装が使われている箇所がある（`.p-button2 a { clip-path: var(--polygon-oval) }` 等）。

### トランジション/イージング・トークン
```
--transition-hover:        350ms ease
--transition-hover-slow:   600ms ease
--transition-sitemap:      700ms ease   ← MENUオーバーレイの開閉
--transition-button:       400ms ease
--transition-slider:       1200ms ease  ← 通常スライダー
--transition-slider-slow:  1600ms ease  ← home-kv__slider（-slowモディファイア）
--transition-slider-dots:  800ms ease
--transition-sticky:       300ms ease
--transition-fadeup:       500ms ease   ← スクロールインのフェードアップ
--transition-slideup:      5000ms ease
--transition-scale:        500ms easeOutBack
```

### コンテナ幅
- `.c-inner-lg`: `max-width: 1300px`（`--base-width:1300` を rem換算）。1280幅実測では内側幅 `1163.64px`（左右余白は親のパディングで確保、要素自体に左右padding無し）。

### テクスチャ・波形装飾（全区画共通パーツ）
- `.c-texture`: `background-image:url(bg_texture.webp)`, `15rem 15rem` タイルリピート, `background-blend-mode: multiply`（紙質・粒状テクスチャを乗算合成）
- `.c-wave2-top::before` / `.c-wave3-top::before`: 各セクション上端に配置される波形マスク。`clip-path: var(--wave-top-mask)` + セクション別 `--wave-top-image` (webp) を使用。高さは `--wave-top-height` カスタムプロパティで区画ごとに指定（下表(c)参照）。PC/SPでそれぞれ別画像・別高さ。

---

## (b) ヘッダー / サイトマップ / 浮遊CTA / pagetop

### ヘッダー `.l-header`
- ロゴ: `.l-header__logo`（`<h1>`）左上固定。PC: `29.7rem × 18.6rem`。SP: `12.2rem × 7.7rem`。`clip-path` で多角形の白カード風に切り抜き、内側にロゴ画像。
- MENU開閉ボタン: `.l-header__button`（`<button aria-label="メインメニューの切替" aria-controls="aria-sitemap" aria-expanded="false">`）
  - 実測サイズ 164×141px（PC）、`position: fixed`、背景色 `rgb(13,111,184)` = `--color-primary`
  - ハンバーガーアイコン2本線（`<span><span></span><span></span></span>`）
  - クリックで `aria-expanded="true"` に切替、`.l-sitemap` に `is-open` クラス付与
  - スクショ: `pc-01-header.png` / `sp-01-header.png`
- 「たまごを購入する」浮遊CTA `.home-kv__button.p-button2.-medium.-secondary2-black`
  - `position: fixed` 相当（画面右上に常時浮遊、スクロールしても追従）
  - サイズ: PC `22rem × 15rem`(=220×150px実測) / SP `12.9rem × 9.4rem`(=129×94px)
  - 形状: `clip-path: var(--polygon-oval)` のオーバル、黄背景に卵アイコン+テキスト
  - スクショ: `pc-16-floating-cta.png` / `sp-16-floating-cta.png`

### サイトマップ（MENUオーバーレイ） `.l-sitemap`（`<nav id="aria-sitemap">`）
- 通常時: `opacity:0; visibility:hidden`
- 開いた時: `.is-open` → `opacity:1; visibility:visible`
- トランジション: `opacity 0.7s, visibility 0.7s`（`--transition-sitemap`）＝ふわっとしたクロスフェード（スライドや拡大なし、単純フェード）
- `position: fixed; width:100%; height:100%; z-index` 最上位。PC背景 `--color-bg`(#f4f4f4)、SP背景 `--color-bg3`(#ececec) と背景色が変わる
- 内部 `.l-sitemap__contents` は `overflow:hidden` の中にリンク一覧
- 実測: クリック→700ms待機後にフルオーバーレイ表示を確認（`pc-25-sitemap-open.png`, `sp-17-sitemap-open.png`）

### pagetopボタン `.l-footer__pagetop`
- footer内、右側に絶対配置 `position:absolute; right:0`
- PC: `width: calc(456/1540 *100%)`, `height:29rem`, `top:6rem`
- SP: `width: calc(118/375 *100%)`, `height:9.8rem`, `top:-1.1rem`（footer上端からわずかに飛び出す配置）
- 背景色 `--color-primary`（青）、文字色 `--color-txt2`（白）、`clip-path: var(--polygon-footer_pagetop)` の多角形カード
- スクショ: `pc-21-pagetop-button.png`（ページ最下部までスクロールした状態でのクリップ撮影）

### KVスライダー `.home-kv__slider.js-slider.-slow`
- 4枚のスライド（`li` 4個、鳥・卵・雲イラストの浮遊背景を含む合成ビジュアル）
- JS実装（`common.js` の `intervalChange`）実測パラメータ:
  - `autoplay: true`
  - `intervalSpeed: 6000ms`（`-slow` 修飾子付きインスタンス。無印は5000ms）
  - `dots: true`（`.js-slider__dots`）, `navigation: true`（前/次矢印 `.js-slider__arrow li.-prev/-next`）
  - スライド切替トランジション: `--transition-slider-slow = 1600ms ease`（無印スライダーは1200ms）
- スクショ: `pc-23-kv-slider-t0.png`（初期状態）と `pc-24-kv-slider-t4s.png`（4秒後、まだ同じスライド＝6秒間隔を裏付け）

---

## (c) 区画ごとの詳細

以下、top/height は PC=1280幅・SP=390幅での実測px。

### 1. `.home-kv`（top 0, PC高さ900 / SP高さ828）
```
┌─────────────────────────────────────────────┐
│ [ロゴ]                          [MENU btn]    │
│                                   [CTA 卵]    │
│        ┌─ home-kv__catch (キャッチコピー) ─┐  │
│        │   中央やや上、absolute配置          │
│        └──────────────────────────────────┘  │
│   home-kv__slider (鳥・卵・雲が浮遊する      │
│   フルブリード背景スライダー, 4枚)            │
│                    ~~~ 波形(kv_wave) ~~~      │
└─────────────────────────────────────────────┘
```
- `.home-kv__catch`: `position:absolute; transform:translate(-50%,-50%)`。PC `max-width:74.7rem`、位置は `--base-width:1540/--base-height:1085` を基準にした%計算（レスポンシブ座標系）
- 高さ計算式: PC `min-height: calc(1050/1540 * ww)`, `max-height: calc(1300/1540 * ww)`（ビューポート幅に対する可変高）
- 波形: `--wave-bottom-height: 37.5rem`(PC)/`8.7rem`(SP)、画像 `kv_wave-pc.webp`/`kv_wave-sp.webp`
- スクショ: `pc-02-kv.png` / `sp-02-kv.png`, スライダー詳細 `pc-23/24`

### 2. `.home-message`（top 900/828, PC高さ976 / SP高さ1049）
```
┌─────────────────────────────────┐
│                    ┌───────────┐ │
│                    │ 英字ラベル │ │
│  (右寄せflex,       │ キャッチ   │ │
│   row-reverse)      │ 本文(14px/lh34,ls0.84px)│
│                    └───────────┘ │
└─────────────────────────────────┘
```
- PC padding: `0 0 25rem`／SP(560px以下) padding: `4.1rem 0 7.6rem`
- `.home-message__inner`: `display:flex; flex-direction:row-reverse; justify-content:flex-end`（768px以上のみ。SPは縦積み想定）
- スクショ: `pc-03-message.png` / `sp-03-message.png`

### 3. `.home-about`（top 1876/1877, PC高さ2829 / SP高さ2609）背景 `--color-bg4`(#05a277)、`c-texture` + `c-wave2-top`
```
   ~~~ 波形(about_wave, 上端 23.1rem PC/5.8rem SP) ~~~
┌───────────────────────────────┐
│  home-about__title (ロゴ見出し) │
│  ┌─item1─┐ ┌─item2─┐ ┌─item3─┐ │  ← 3つの__itemが縦積み
│  │catch(20px)+contents(60%幅,右寄せ)│
│  └───────┘ └───────┘ └───────┘ │
│  鳥・葉・草・雲の浮遊イラスト(c-object2) │
└───────────────────────────────┘
```
- `.home-about__item__contents`: 768px以上で `width: calc(600/1300*100%)`（=約46%）, `margin-top:2rem`
- 浮遊装飾: bird-1(c-anime-rotate4, 141px), bird-2(c-anime-rotate3, 128px), grass×3, leaf-1, cloud-1(fluffy), cloud-2(fluffy2), cloud-3(fluffy3)
- スクショ: `pc-04-about.png` / `sp-04-about.png`

### 4. `.home-point`（top 4705/4486, PC高さ7702 / SP高さ7928）`c-wave2-top`、内部に3サブセクション
PC padding `12.8rem 0 34.4rem` / SP padding `6rem 0 9.2rem`。波形高さ23rem(PC)/5.8rem(SP)。
```
       home-point__title (52.5rem幅 PC / 26.3rem幅 SP, ロゴ見出し)
┌─ .home-point__item.-eating (top 4945, PC高2922) ──────┐
│ 見出し: 背景色--color-bg4(緑) / 文字--color-txt5        │
│  [丸型見出しバッジ 16.8rem×21.4rem: "食" 40px + "- eating -" 9px] │
│  ┌─────────2列グリッド(PC)──────────┐                  │
│  │ セル1 (541.8px)   │ セル2 (541.8px) │  gap:100px(行)80px(列)│
│  └───────────────────┴────────────────┘                │
└──────────────────────────────────────────────────────┘
┌─ .home-point__item.-living (top 7922/8072, PC高2520) ─┐
│ 背景色--color-bg6(黄) / 見出し文字は--color-txt(黒)に反転 │
│  同様の2列グリッド、セル数はeatingより少なめ(高さ1470)    │
└──────────────────────────────────────────────────────┘
┌─ .home-point__item.-cycle (top 10497/10813, PC高1566) ─┐
│ 背景色--color-primary(青)                                │
│  .home-point__item__business (478px)                    │
└──────────────────────────────────────────────────────┘
```
- グリッド実測（PC1280幅）: `.home-point__item__list { display:grid; grid-template-columns: 541.8px 541.8px; gap:100px 80px }`
- グリッド実測（SP390幅）: `grid-template-columns: 343.2px`（**1カラムに収束**）, `gap:55px 40px`
- 見出しバッジ `.home-point__item__heading__title`: PC `16.8rem×21.4rem`, `top: calc(230/924*100%)`、背景画像 `point1_title_bg.webp`（-eating/-cycleで共用）/ `point2_title_bg.webp`（-living）
- 浮遊装飾: bird-1(rotate3), leaf-1, cloud-1(fluffy)/cloud-2(fluffy2)/cloud-3(fluffy3)が `.home-point` 直下に1セットのみ（3サブセクション共通で先頭にまとまっている）
- スクショ: `pc-05/06/07-point-*.png`, 中間ビューポート `pc-17-point-mid-viewport.png`（-eating下部〜-living境界）, `pc-18-point-living-mid.png`（-cycle手前）/ SP `sp-05/06/07`

### 5. `.home-daily`（top 12406/12414, PC高2926 / SP高3257）背景`--color-bg4`緑、`c-texture`+`c-wave2-top`
- `.home-daily__inner.c-inner-lg`: `display:block`（グリッドではなくブロック縦積み、01〜09のタイムラインを内部で個別配置）、PC高さ2578px
- 浮遊装飾クラスは `.home-about__bird-*` 等を流用（about と daily で同一の装飾クラス名を共有 = CSS上一体設計）
- スクショ: `pc-08-daily.png` / `sp-08-daily.png`, 中間 `pc-19-daily-mid-viewport.png`

### 6. `.home-kome`（top 15332/15671, PC高2635 / SP高1472）
- `.home-kome__intro`背景 `--color-bg`(#f4f4f4)、波形高さ7.2rem(PC)/1.9rem(SP)、`.home-kome__intro__inner` PC padding `12.5rem 0 42.6rem`
- 本文 `.home-kome__main__txt`: 13px/lh30px/letter-spacing 0.52px、weight500
- CTAボタン2本（商品購入導線）を含む
- スクショ: `pc-09-kome.png` / `sp-09-kome.png`

### 7. `.home-coco`（top 17967/17143, PC高3775 / SP高3600）4サブブロック
```
__intro(448/184)  背景--color-bg8(#75c5f0 水色) 波形23.1rem/5.8rem, height 44.8rem(PC)/18.4rem(SP)
__main (2306/2796) 店舗3件カード。display:blockで縦積み(グリッドではない)
__map  (693/468)   地図+住所プロフィール
__outro(881/148)   背景--color-bg8 波形あり
```
- カード見出し `.home-coco__main__item__catch`: 18px/lh30px/letter-spacing1.44px
- スクショ: `pc-10〜13`, `sp-10〜13`、中間 `pc-20-coco-main-mid-viewport.png`

### 8. `.home-farm`（top 21742/20739, PC高2447 / SP高2712）背景`--color-bg`(#f4f4f4) + `c-texture` + `c-wave2-top`
- `.home-farm__inner.c-inner-lg`: `display:block`（縦積み、カード3枚）、波形高さ23.2rem(PC)/5.9rem(SP)
- `.home-farm__title` max-width 33rem(PC)/15.2rem(SP)
- カードタイトル `.home-farm__card__title`: 18px/lh30px/letter-spacing1.44px（coco同一スタイル）
- `.home-farm__cinema`: PC `margin-top:9.5rem`（動画/シネマ枠と推測、要目視確認）
- 浮遊装飾: cloud-1(fluffy2)/cloud-2/cloud-3(fluffy3)
- スクショ: `pc-14-farm.png` / `sp-14-farm.png`

### footer `l-footer`（top 24107/23454, PC高838 / SP高681）
- `c-wave3-top`（他区画と別バリエーションの波形マスク）+ `c-texture-ba`（::before/::after両面テクスチャ）
- pagetopボタン詳細は(b)参照
- スクショ: `pc-15-footer.png` / `sp-15-footer.png`

---

## (d) モバイルでの変化（PC→SP差分まとめ）

| 項目 | PC(1024px以上) | SP(1023px以下) |
|---|---|---|
| home-point グリッド列数 | 2列（541.8px×2, gap 100/80px） | 1列（343.2px, gap 55/40px） |
| home-about/daily 波形高さ | 23.1rem | 5.8rem |
| home-point 波形高さ | 23rem | 5.8rem |
| home-kome 波形高さ | 7.2rem | 1.9rem |
| home-coco 波形高さ | 23.1rem | 5.8rem |
| home-farm 波形高さ | 23.2rem | 5.9rem |
| home-kv 高さ計算基準 | base 1540×1085 | base 375×655 |
| ロゴサイズ | 29.7rem×18.6rem | 12.2rem×7.7rem |
| 浮遊CTA(.p-button2.-medium) | 22rem×15rem | 12.9rem×9.4rem |
| pagetopボタン | 45.6%幅相当×29rem, top6rem | 31.5%幅相当×9.8rem, top-1.1rem |
| サイトマップ背景色 | `--color-bg`(#f4f4f4) | `--color-bg3`(#ececec) |
| home-message flex | row-reverse横並び(768px以上) | 縦積み（推定、768px未満はflex指定なし） |
| home-about__item__contents幅 | 600/1300=約46% | 幅指定なし=100%（推定） |
| ページ総高さ | 24945px | 24135px |

- 浮遊イラスト（鳥・雲・葉）は間引きではなく**同一DOM構成を保持**（bird/cloud/leaf要素はSPでもすべて存在、`c-object2` の `--width/--base-width` 比率でサイズのみ追従）。実測上、要素の削除は確認できなかった＝表示/非表示の間引きは無し（**推定**：`display:none` 等での明示的間引きは今回のDOM走査では検出せず）。
- home-farm/home-coco/home-daily の内部レイアウトは `display:block` のため、PC/SPともに縦積み構造は共通（横→縦に変わるのではなく、そもそも横並びグリッドを使っていない区画）。実際の見た目の列変化はFlexboxまたは個別要素の `width` プロパティで制御されている可能性が高い（**推定**、詳細はスクショで目視確認要）。

---

## (e) モーション一覧

| keyframes名 | 動き | duration/timing | 使用クラス | 対象 |
|---|---|---|---|---|
| `step-rotate` | 0deg→-20deg→0deg（ステップ式・階段状） | 3.5s steps(1) infinite | `.c-anime-rotate` | 浮遊する鳥イラスト等 |
| `step-rotate2` | 0deg→+20deg→0deg | 3.5s steps(1) infinite | `.c-anime-rotate2` | 同上・逆回転版 |
| `step-rotate3` | 3deg→-3deg→3deg（小振幅） | 3.5s steps(1) infinite | `.c-anime-rotate3` | bird-2等 |
| `step-rotate4` | 5deg→-5deg→5deg | 4s steps(1) infinite | `.c-anime-rotate4` | bird-1等 |
| `step-fluffy` | translate3d 0→(-10%,-4%)→(-4%,4%)→(12%,2%)→(5%,-4%) | 7s steps(1) infinite | `.c-anime-fluffy` | 雲イラスト cloud-1系 |
| `step-fluffy2` | translate3d 0→(-5%,-5%)→(-10%,2%)→(0,-3%)→(10%,4%) | 8s steps(1) infinite | `.c-anime-fluffy2` | cloud-2系 |
| `step-fluffy2`（再利用） | 同上 | 9s steps(1) infinite | `.c-anime-fluffy3` | cloud-3系（durationのみ変更、keyframeはstep-fluffyを再利用） |
| `loopslider-x` | translate3d(0,0,0)→translate3d(-100%,0,0) | 未確定（**推定**：帯状の無限横スクロール演出、店舗ロゴ等の流れる帯に使用と推測） | `.js-loopslider`系（DOM上未確認、CSS定義のみ検出） | 未特定 |
| （fadeup） | opacity 0→1 + translateY(1rem→0) + rotate(.001deg)（サブピクセルアンチエイリアス対策のダミーrotate） | 500ms ease、delay既定200ms（`--transition-delay`変数で個別指定可） | `.js-fadeup` → `.is-shown` トリガーで発火 | 全区画の見出し・本文（スクロールで画面内に入ったタイミングでIntersectionObserver等により`is-shown`付与と推測） |
| （fadeups 子要素stagger） | 同上fadeupを子要素ごとに遅延 | 1個目 +160ms、2個目 +320ms（以降160ms刻みと推測） | `.js-fadeups > *` | リスト状の子要素（**推定**：3個目以降は160ms×nで外挿） |
| （サイトマップ開閉） | opacity + visibility フェード | 700ms ease（`--transition-sitemap`） | `.l-sitemap.is-open` | MENUオーバーレイ全体 |
| （KVスライダー切替） | クロスフェード/スライド（**推定**：詳細トランジションプロパティはCSSから未特定、JSの`intervalChange`が発火） | 6000ms間隔、遷移1600ms（`-slow`修飾子） | `.home-kv__slider.-slow` | KVビジュアル4枚 |
| （ボタンhover） | 背景色/装飾の変化（`pc-22-button-hover.png`参照。目視上は明確な差分小さく、色変化は僅か） | 350ms ease（`--transition-hover`） | ボタン全般 | `.p-button2`等 |
| （page-top button） | 出現/追従 | 300ms ease（`--transition-sticky`、推定：スクロール追従のスムーズさに使用） | `.l-footer__pagetop`等 | pagetopボタン |

- アニメーションはすべて `steps(1)` によるコマ送り（イージングなし・瞬間切替）で、CSS transitionではなく `@keyframes` 直接適用。浮遊イラストの「揺れ」は滑らかな補間ではなく、5段階前後のキーフレーム間を瞬時にジャンプする独特の質感（アニメーションGIF風の動き）である点に注意。

---

## 実測できなかった項目（推測含む・要目視/追加検証）
1. `loopslider-x` keyframesの実際の適用箇所（DOM上に対応クラスの要素が見当たらず、店舗ロゴ帯などSP限定要素の可能性）
2. `.js-fadeups` の3個目以降のstagger遅延値（1,2個目のみCSSに明記、以降は外挿）
3. KVスライダーのスライド間トランジション種別（フェード/スライドのどちらか。`--transition-slider-slow`の適用先セレクタまでは追えたが、`transform`か`opacity`かは未特定）
4. home-message / home-about 等の768px未満(SPでも768px以上769px未満は稀だが)における `flex` 解除後の具体的レイアウト（`display:flex`の条件が「768px以上」のみ確認、それ未満の明示スタイルは今回未取得）
5. home-about__title 等、textContentが空でロゴ画像的に描画される見出し要素の実体（SVGインライン/background-image/`::before`疑似要素のいずれか未特定。スクショから画像を切り出して実装すること）
6. hover時の視覚差分の詳細数値（`pc-22-button-hover.png`は撮影済みだが、色のRGB差分は未測定）
7. `home-farm__cinema` の中身（動画埋め込みの可能性、`margin-top:9.5rem`のみ確認、要素の実体は未調査）
