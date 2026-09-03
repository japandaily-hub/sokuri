# SPEC.md §2 への修正指示（Webデザイナー / アートディレクション査読・2026-09-03）

対象: `docs/design_hitonomori_alignment/SPEC.md` §2（写像設計）
突合資料: `hitonomori-top-full.png` / `hn-contact.png` / `hn-mobile-top.png`、
`web/src/app/katazuke.css`（596行）/ `katazuke-pages.css`（188行）/ `page.tsx` / `globals.css`。
コントラスト比は WCAG 2.x 相対輝度式で自算。

**結論**: §2 の方向（トークン差し替え・直角・影ゼロ・明朝）は正しい。ただし
**(1) `--body-soft:#959595` が本文コントラスト不合格**、**(2) `--sans` を明朝エイリアスにすると入力欄の値まで明朝になる**、
**(3) 額装フレーム内 sticky header は `top:0` では成立しない**、**(4) 縦書き見出しの `::after` 方式はSR二重読み上げ**
の4点は、このまま実装するとリリースブロッカーになる。以下 18 件を採用のこと。

---

## 採用すべき修正

### A. タイポグラフィ（論点 a への判定）

**判定: 本文明朝は採用する。ただし「マーケ面＝全部明朝／app面＝地の文まで明朝・入力値と数表だけゴシック」で分ける。**

**1. `--serif` の並び順を逆にする（Windows/Android 対策・最重要）**

SPEC §2.2 は `"Yu Mincho","YuMincho","游明朝体",…,"Noto Serif JP"` の順。これは事故る。
- Windows: 先頭の游明朝が当たる。游明朝 Regular は縦画が細く、15px・`-webkit-font-smoothing` 環境で滲む。
- Android: 明朝が**1書体も入っていない**。`Noto Serif JP` を webfont として確実にロードしない限り
  `serif` → Noto Sans CJK にフォールバックし、**Android ユーザーには再設計が一切見えない**。

```css
--serif:"Noto Serif JP","Hiragino Mincho ProN","Hiragino Mincho Pro","Yu Mincho","YuMincho","游明朝体",serif;
```
逸脱根拠: 人の森は Mac 想定で游明朝先頭だが、カタヅケは一般消費者向けで Windows/Android 比率が高い。
**OS ごとの最適解より、全 OS で同じ明朝が出ること（＝ブランド整合の前提）を優先する。**

**2. `-webkit-font-smoothing:antialiased` を明朝本文から外す**

`katazuke.css` l.53 と `globals.css` `@layer base` の body に二重指定されている。
ゴシック太字では効果的だったが、**明朝 400 では macOS でサブピクセルレンダリングが切られ字画が痩せる**。
```css
body{ -webkit-font-smoothing:auto; -moz-osx-font-smoothing:auto; }
```
（`text-rendering:optimizeLegibility` は据え置き可）

**3. 字送りの単位換算ミスを修正**

SPEC §1.1 の実測は `letter-spacing:0.05rem`（=16px 基準で 0.031em）。§2.2 は `.05em`（=0.8px）と書いており、
**参照サイトより 60% 広い**。明朝は字面が小さいため過剰トラッキングで語のまとまりが崩れる。
```css
body{ letter-spacing:.03em; }        /* 見出しは .04em 据え置きでよい */
```

**4. 本文サイズ・行間を面ごとに切る（15px/2.0 一律は app 画面で破綻する）**

| 面 | `font-size` | `line-height` | 根拠 |
| :-- | :-- | :-- | :-- |
| マーケ（`/`, `/faq`, `/examples`, `/company`, `/business`, `/contact`, `/privacy`, `/terms`, `/photo-guide`） | **16px** | **2.0** | 人の森実測と同値。SPEC の 15px は明朝の可読下限を割る |
| app 地の文（`.step-desc` `.auth-sub` `.modal-sub` 等） | 15px | **1.75** | 2.0 だと `.field`（`margin-bottom:18px`）と重なり、`create` の1画面が約1.3倍に伸びて送信ボタンが折り返し下に落ちる＝CVR損 |
| 表セル・`.confirm-row` | 14px | 1.6 | 行あたり1〜2行。2.0 は行間が空きすぎて行の対応が読めなくなる |
| チャット吹き出し（`chat/[id]/chat.css`） | 15px | 1.7 | |

**5. `--sans` を明朝のエイリアスにしない。UI 用ゴシック変数を新設する（設計事故の回避）**

SPEC §2.2 は `--sans:var(--serif)` としている。しかし `katazuke-pages.css` l.49 / l.156 が
`.field input, .field textarea, .field select { font-family: var(--sans) }` を持つため、
**この1行だけで全フォームの「入力された値」が明朝になる**。住所・メールアドレス・電話番号・金額を
明朝 400 で表示すると `1/l/I`・`0/O`・全角半角の判別が落ち、入力ミスの発見コストが上がる。

```css
:root{
  --serif:…; --head:var(--serif); --sans:var(--serif);   /* 地の文はSPECどおり明朝 */
  --ui:"Noto Sans JP","Hiragino Kaku Gothic ProN","Yu Gothic UI",sans-serif;  /* 新設 */
  --num:var(--ui);
}
.field input,.field textarea,.field select,.select-wrap select,
td .val,.confirm-row .val,.money,.fee-row .fv,[class*="tabular"]{
  font-family:var(--ui); font-variant-numeric:tabular-nums; letter-spacing:0;
}
```
逸脱根拠: 人の森のフォームは年に数回・5項目の問い合わせ窓口。カタヅケは毎日使う取引画面で、
**書体の印象を担っているのは見出し・面・かたちであり、入力値の書体は印象への寄与が小さい一方で誤読コストが大きい。**
ラベル・説明文・見出しは明朝のままなので、フォーム全体の見た目は人の森と揃う（`hn-contact.png` と同じ構図）。

**6. Google Fonts のロード計画を確定する**

`globals.css` 先頭の `@import` を差し替える（Zen Maru / Zen Kaku / Noto Sans 700 は落とす）。
```css
@import url("https://fonts.googleapis.com/css2?family=Noto+Serif+JP:wght@400;600&family=Noto+Sans+JP:wght@400;500&family=Montserrat:wght@600&family=Libre+Baskerville:wght@400&display=swap");
```
- SPEC の `Noto Serif JP:wght@400;500;600` は 3 ウェイト。**500 は使わない**（後述 8 参照）ので 400/600 の 2 つに削る。
- `layout.tsx` の `<head>` に `<link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />` を追加する。
  現状は CSS 内 `@import` のみで、CSS パース完了まで書体リクエストが始まらない（直列化）。明朝は本文全面に効くため LCP に直撃する。
- フォールバック（游明朝／ヒラギノ明朝）と Noto Serif JP はメトリクスが異なるため、swap 時に CLS が出る。
  `@font-face{font-family:"NSJP-fb";src:local("Yu Mincho");ascent-override:88%;descent-override:12%;line-gap-override:0%}`
  を置き `--serif` の第2候補に差す。[推測] override 値は実測して詰めること。

### B. 色・アクセシビリティ

**7. `--body-soft:#959595` は本文用途に流用できない（Critical）**

`#959595` on `#fff` = **3.0:1**。WCAG AA の本文基準 4.5:1 に不合格。
人の森ではこの色は h3（26px）にしか使われていないが、カタヅケでは
`.cat-body .cs`（10.5px）・`.assure-item span`（11.5px）・`.hero-badge small`（11px）・
`.step-desc`・`.auth-sub`・`.fee-head p`・`.footer` 系と、**小さい本文にこそ多用されている**。

```css
--body-soft:#6b6b6b;   /* 白と 5.3:1。小さい補助テキスト全部をこれに寄せる */
--head-gray:#959595;   /* 新設。24px 以上の見出し（人の森 h3 の作法）専用 */
```
逸脱根拠: 人の森の `#959595` は「大きい見出しを引っ込める」ための色。**同じ色を小さい文字に流用した時点で作法の写し間違い**であり、色を変えることが作法の正しい継承になる。

**8. 緑ボタンの白文字は 4.7:1。文字を痩せさせない**

`#527e52` on `#fff` = **4.70:1**（AA ぎりぎり通過）。ただし明朝 400・15px の細い字画では体感的にさらに読みにくい。
```css
.btn{ font-size:16px; font-weight:500; }   /* Noto Serif JP は 500 の実ウェイトを持つ */
```
**ただし `font-weight:500` を指定してよいのは Noto Serif JP がロードされている時だけ**。
游明朝には 500 が無く合成太字（faux bold）になって滲む → 上記 1 で Noto Serif JP を先頭に置くことが前提条件。
それが担保できない場合はボタン地を `--primary-d:#3f6640`（白と **6.6:1**）にして weight 400 を維持する。

**9. フォーカスリングを消してはならない（SPEC §2.3 の「リングなし」は撤回）**

`border-color:#ddd → #527e52` の変化はコントラスト比 3.4:1 で色差の要件は満たすが、
**1px の枠は WCAG 2.2 Focus Appearance の「2 CSS px 以上の周長」を満たさない**。
`globals.css` は既に `:focus-visible{outline:2px solid var(--blue);outline-offset:2px;border-radius:4px}` を持つ。これを残す:
```css
:focus-visible{ outline:2px solid var(--primary); outline-offset:2px; border-radius:0; }
```
角丸 0 なので `border-radius:0` で作法内に収まる。**リングを消す理由はどこにもない。**

**10. `.final .btn-line:hover` は既存バグ。今回まとめて直す**

`katazuke.css` l.511 `.final .btn-line:hover{background:#f0fff6}` — `.btn-line` は `color:#fff` のため、
**ホバーで白地に白文字になり文言が消える**。人の森作法（hover は opacity のみ）へ寄せる形で解消:
```css
.btn:hover{ opacity:.8; }                       /* 共通。transform / box-shadow の上書きは全削除 */
.btn:active{ opacity:.65; }
.btn-line, .btn-line:hover, .final .btn-line:hover{ background:#06c755; color:#fff; box-shadow:none; }
```

**11. 「無料」の強調を色ではなくマーカーで作る**

`--green` を `#527e52` に一本化すると `.fee-row .fv{color:var(--green)}`（現行 `#0e8a5a`）の
「無料」が地の緑に埋もれる。無料訴求はこのサービスの主要 CVR 要因なので、色を増やさずに強度を戻す:
```css
.fee-row .fv{ color:var(--primary); background:linear-gradient(transparent 68%, #d4efb3 68%); }
```
人の森トップの PURPOSE / VISION / MISSION 見出しに敷かれたマーカー下線と同一作法（`hitonomori-top-full.png` 実測）。

### C. かたち・レイアウト

**12. 額装フレーム × sticky header（論点 c）— `top:0` は誤り**

`.site-frame{margin:20px}` の内側で `.header{position:sticky;top:0}` にすると、
sticky は**ビューポート基準**で貼り付くため、ヘッダーがフレーム上辺（20px の余白と 1px の罫）に重なり、
額の上辺がヘッダーの裏に消える。正しくは:
```css
.site-frame{ margin:20px; border:1px solid #333; min-height:calc(100dvh - 40px); }
.header{ position:sticky; top:20px; }
@media (max-width:859px){ .site-frame{margin:0;border:0;min-height:0} .header{top:0} }
```
- `100vh` ではなく **`100dvh`**。iOS Safari の `100vh` はツールバー分だけ過大で、初期表示で額の下辺が切れる。
- **`.site-frame` に `overflow:hidden` を絶対に付けないこと。** 付けた瞬間、内側の `position:sticky` が
  全ページで機能を失う（スクロールポートが frame に移る）。ヒーローの blob をはみ出させないためには
  `overflow` ではなく blob 側の `clip-path`、またはヘッダーを含まない別ラッパで囲う。
- `.scroll-progress{position:fixed;top:0;left:0}`（l.117）は fixed のため**額の外側の余白に描かれる**。
  `top:20px;left:20px;right:20px;width:auto` に直すか、`@media(min-width:860px)` で非表示にする。
- `.dock`（l.535, `max-width:860px` で表示）は額を出さない幅帯なので整合済み。据え置き。

**13. 抑揚は「額をセクション単位で分割する」で作る（論点 f の本命解）**

`hitonomori-top-full.png` の実測: 人の森トップは**1枚の額ではなく、縦に独立した額が3つ**並び、
額と額の間は白地で約 40px 空いている。SPEC の「ページ全体を1枚の額で包む」は参照実装と異なる。
```css
.site-frame{ margin:20px; border:1px solid #333; }
.site-frame + .site-frame{ margin-top:0; }   /* 額の間は 20px+20px = 40px の白 */
```
マーケページを 2〜3 の額に割ると、**セクション背景色（`.bg-pale`）を使わずに面のリズムが生まれる**。
ヘッダーは最初の額の外に出す（人の森のロゴ／ナビは額の中にあるが sticky ではない。カタヅケは
サービスサイトで CTA 常時到達性が必要なため sticky を優先する — 逸脱根拠）。

**14. カードは「枠を引く」のをやめる（論点 f）**

SPEC §2.3 は全カードを `1px solid var(--line)` の直角箱にする。ステップ4枚＋カテゴリ12枚＋共感3枚＋
信頼3枚＋シーン4枚＋バンドル3枚を全部これにすると、**ページ全体が表組みに見える**。
人の森はそもそもカードに枠を引いていない（枠があるのは DNA 一覧の細枠タグとフォームパネルの面だけ）。

```css
/* 写真＋テキストのカードは枠も面も持たない。区切りは余白のみ */
.emp-card,.step,.scene-card,.trust-c{ border:0; background:transparent; box-shadow:none; }
.emp-grid,.steps-grid,.scenes-grid,.trust-grid{ gap:clamp(28px,3.4vw,40px); }
.emp-card:hover .emp-photo img,.step:hover .step-photo img{ opacity:.85; }   /* hover は opacity のみ */
.emp-card:hover h3,.step:hover h3{ color:var(--primary); }

/* カテゴリ12枚は「額に入った小さな図版」＝枠は写真だけが持つ */
.cat{ border:0; background:transparent; box-shadow:none; }
.cat-img{ border:1px solid var(--line); }

/* 強調1枚は枠色ではなく面＋左の緑縦バー（人の森「本社」小見出しの作法） */
.bundle-c.key{ border:0; background:var(--pale); border-left:3px solid var(--primary); box-shadow:none; }
.bundle-c .bc-badge{ border-radius:0; background:var(--primary); box-shadow:none; top:0; left:0; }
```
リズムは **罫線の長さ**で作る: セクション見出し直下に中央 1px×48px の緑罫、リード文の末尾に右へ伸びる
1px の長罫（人の森「その終わりのない物語。————」の作法）、`h2::first-letter{color:var(--primary)}`。

**15. ヒーロー写真は円形にしない（論点 f の周辺）**

SPEC §2.3 はヒーロー写真を `aspect-ratio:1/1; border-radius:50%` にする。
`p-hero.png` は「部屋で不用品を撮影する人物」＝**情報を持つ写真**で、円形マスクは四隅の情報（散らかった物）を落とす。
面積も 4:3 比で約 6 割に縮み、ヒーローの視覚的重量が落ちる。
```css
.hero-photo{ border-radius:0; aspect-ratio:3/4; border:0; box-shadow:none; overflow:visible; position:relative; }
.hero-photo img{ object-fit:cover; object-position:center 35%; }
.hero-photo::before{ content:""; position:absolute; inset:-6px -6px 6px 6px;
  border:1px solid var(--primary); pointer-events:none; }   /* リングを 6px ずらす作法の直角版 */
.hero-photo::after{ content:""; position:absolute; top:50%; left:-46px; width:38px;
  border-top:1px dashed #333; }                              /* 破線コネクタは維持 */
```
円形マスクは `.cta-staff`（既に円）と `.founder-photo` に限定する。
逸脱根拠: 人の森は「森」という抽象イメージを円で抜いているが、**カタヅケの写真は説明のための写真であり、
円は説明を削る。**「円形写真＋緑リング＋破線」の作法のうち、意味を壊さない後半2つだけを継承する。
スキャン線（`kdzScan`）とパルス（`kdzPulse`）は削除、「AI解析中」バッジは直角・白地・緑文字で**静止して残す**
（削除すると「待つだけで進む」という情報が落ちるため。SPEC の「情報不変」原則）。

**16. 縦書き見出しは `::after` ではなく実要素で、2セクションだけに置く（論点 d）**

SPEC §2.3 の `section[data-vt]::after{content:attr(data-vt)}` は 3 つの問題がある。
1. **擬似要素の `content` は NVDA / VoiceOver が読み上げる。** `data-vt` に見出しと同じ文字列を入れると
   同じ見出しが 2 回読まれる。擬似要素に `aria-hidden` は効かないため、CSS では回避できない。
2. `attr()` のテキストは Ctrl+F で検索できず、翻訳もされない。
3. `position:absolute` するのに `section` 側に `position:relative` が無い（`katazuke.css` の section 群は未指定）。

```html
<span class="vt" aria-hidden="true">まとめて出すほど、有利になる。</span>
```
```css
section:has(> .vt){ position:relative; }
.vt{ display:none; }
@media (min-width:1280px){                       /* 1180px では container(1140px+24px×2) と衝突する */
  .vt{ display:block; position:absolute; top:clamp(64px,8vw,108px);
       right:max(8px, calc((100vw - var(--maxw))/2 - 46px));
       writing-mode:vertical-rl; text-orientation:mixed;
       font-family:var(--head); font-size:34px; font-weight:400; line-height:1.35;
       letter-spacing:.12em; color:#333; }
  .vt::first-letter{ color:var(--primary); }
  .vt .n{ text-combine-upright:all; }            /* 半角数字が横倒しになるのを防ぐ */
}
```
**置くのは主要6セクションではなく2セクションだけ**（`#bundle` と `#auction`）。
`hitonomori-top-full.png` の実測でも縦書きは「人の森という物語」「Brand Statement」の**2箇所しかない**。
6 箇所に出すと縦書きが壁紙になり、作法ではなく装飾になる。
**モバイルでは絶対に出さない。** `hn-mobile-top.png` には人の森自身の**横スクロールバーが写っている**
（縦書きブロックが幅を超過している）。これは参照サイトの実装欠陥であり、模倣対象ではない。

**17. ロゴのワードマーク化は妥当。ただし露出面を取りこぼさない（論点 b）**

判定: **妥当**。現行 PNG は紺＋黄で、緑基調の全 41 ルートに常時出るヘッダーロゴが**最大の混色源**になる。
二段ワードマーク（和文明朝＋極小英字）は意匠として一般的で、人の森アセットの流用にも当たらない。
ただし SPEC の「PNG は OG / apple-icon 用に残す」は**そのままだと事故る**:
SNS シェアやホーム画面追加で**紺＋黄のカタヅケ**が出て、開いたサイトが緑になる＝別ブランドに見える。

- `opengraph-image.tsx` / `apple-icon.tsx` / `icon.png` / `manifest.ts` を緑ワードマークへ更新する（4ファイルとも要変更）。
- **`manifest.ts` の `theme_color` を必ず確認**。`#1447e0` のままだと Android Chrome のツールバーがコバルトで残る。
- ワードマークは `font-weight:400`（500 ではない）。游明朝には 500 が無く、Noto Serif JP の
  ロード前に合成太字で描かれて字画が滲む（項目 8 と同じ理由）。
- 英字の字送りは SPEC の `.32em` → **`.18em`**。`.32em` は人の森の "HITO NO MORI" とほぼ同一で、
  ロゴレベルの近似はグループロゴの派生に見えすぎる。

**18. LINE 緑ボタンは「直角化する／色は据え置く」で正。ただし用途で 2 系統に割る（論点 e）**

判定: **直角化は可、`#06c755` の据え置きも正しい。**
- `.btn-line`（マーケ導線・自社文言の CTA。`page.tsx` に 4 箇所）→ **直角化する。**
- `.btn-line-auth`（`katazuke-pages.css` l.89、実際の LINE ログイン実行ボタン）→ **角丸 99px のまま据え置く。**
  LINE ログインボタンは公式のボタン仕様に従うことが求められる領域で、形状変更は規約リスク側に倒れる。
  逸脱根拠: **他社ブランドの規約 > 自社の見た目の統一。** 画面内で 1 箇所だけ角丸が残るが、
  それは「他社のボタンである」という正しい信号になる。

混色回避のため、緑を 2 つ隣接させない:
```css
.hero-cta .btn-ghost, .final .btn-ghost{ border:1px solid #333; color:#333; background:#fff; }
```
（`.btn-ghost` を緑枠にすると `#06c755` と `#527e52` が並び、彩度差が最も目立つ組み合わせになる）
LINE ボタンには必ず LINE アイコンと「LINE」の語を残す（既に有り）。これで**混色ではなく引用**として読める。

### D. 言葉の作法（§2.5 への補足）

`page.tsx` の `“まとめ全体”`（l.24 FAQ / l.194 `<strong>` 内）を SPEC どおり `「まとめ全体」` にすると、
同じ段落の `「これは売れないかも」` と近接し、1 段落に鉤括弧が 3 組並ぶ。人の森は「」の多用を避けている。
→ **鉤括弧化せず、緑マーカーに置換する**（文字を一切変えないので意味不変・SPEC の原則内）。
```html
<strong class="mk">まとめ全体</strong>
```
```css
.mk{ font-weight:400; background:linear-gradient(transparent 68%, #d4efb3 68%); }
```

---

## 据え置きでよい点

- **§2.1 の「旧変数名をエイリアスとして残す」方針** — 39 本の per-page CSS を壊さない唯一の現実解。正しい。
- **`#527e52` を主色に据えること** — 白と 4.70:1 で AA 通過。人の森との同一性が最も強く出る一点。
- **角丸ゼロ・影ゼロ・`backdrop-filter` 削除** — 迷わず全面適用でよい。
  `.kdz-overlay{background:rgba(15,37,82,.45)}` → `rgba(51,51,51,.45)`、`.kdz-toast` の `border-radius:99px` → `0` も同時に。
- **`.rv` を opacity のみに変える**（`translateY(22px)` 削除） — 人の森は fade のみ。作法どおり。
- **左固定縦ナビへの構造変更をしない（§2.6）** — サービスサイトの CTA 到達性を優先する判断は正しい。
- **モバイル Dock（`.dock`）と `body{padding-bottom:74px}` の維持** — 人の森に無い部品だが、
  逸脱根拠: コーポレートサイトは「読ませて終わり」、カタヅケは「その場で出品させる」。機能差であって作法違反ではない。
- **`.footer` の 4 カラム維持** — 導線不変の原則どおり。白地化のみでよい。
- **`#06c755` の据え置き** — 白文字とのコントラストは **2.29:1** で WCAG 不合格だが、
  LINE のブランド規約が白抜きを指定しているため**文書化された例外**として扱う。
  `web/DESIGN_SYSTEM.md` §10 に「LINE ブランド色は AA 対象外・単独導線にしない」と明記すること。

---

## 実装リスクと回避策

| # | リスク | 兆候 | 回避策 |
| :-- | :-- | :-- | :-- |
| R1 | Android に明朝が出ない | 実機 Android で本文がゴシックのまま | Noto Serif JP を `--serif` 先頭に置き、webfont ロードを Playwright の `document.fonts.check("400 16px 'Noto Serif JP'")` で DoD 検査に追加 |
| R2 | Windows 游明朝が細く滲む | Windows Chrome で本文が灰色に見える | R1 と同じ。加えて `-webkit-font-smoothing:auto`（項目 2） |
| R3 | 合成太字（faux bold）の滲み | `font-weight:500/600` 指定箇所 | 明朝で使うウェイトは **400 と 600 のみ**。500 は禁止（游明朝に実ウェイトが無い） |
| R4 | `.site-frame{overflow:hidden}` で sticky header が全ページ死亡 | ヘッダーが追従しない | frame に `overflow` を書かない。blob は `clip-path` で処理 |
| R5 | iOS で額の下辺が切れる | 初期表示で枠が閉じない | `min-height:calc(100dvh - 40px)` |
| R6 | 縦書きが横スクロールを生む | モバイルで左右に振れる | `.vt` は `min-width:1280px` のみ。DoD に「全41ルート×375px で `document.scrollingElement.scrollWidth <= innerWidth`」を追加 |
| R7 | CLS 悪化 | LCP 後に本文が跳ねる | `preconnect` + `size-adjust`/`ascent-override` フォールバック（項目 6） |
| R8 | `--sans` 明朝化で入力欄まで明朝 | フォームの入力値が明朝 | `--ui` 新設（項目 5） |
| R9 | OG / favicon / `theme_color` の取りこぼし | シェア画像だけ紺＋黄 | 項目 17 の 4 ファイル＋`theme_color` |
| R10 | `--body-soft` 一括置換でコントラスト不合格が残る | axe で contrast 違反 | `#959595` は `--head-gray` として別変数に切り、24px 未満には使わない |
| R11 | `text-align:justify` の JP 均等割付が崩れる | モバイルで字間がまだらになる | `@media(min-width:768px)` の散文ブロック（`.section-head .sub` / `.media-copy .sub`）のみに適用し、13〜14px のカード本文には適用しない |
| R12 | `width:100vw` を使っている箇所が額の外にはみ出す | 横スクロール発生 | [推測] 39 本の per-page CSS を `grep -n "100vw"` で棚卸ししてから frame を入れる |

---

## 未解決（ユーザー判断・実測が必要）

1. **ロゴの正式アセット** — 緑版ワードマークを確定版とするか、既存 PNG の緑リカラーを別途用意するか。
   ワードマークで進める場合、字形（「カタヅケ」の明朝カスタム有無）の確定が要る。
2. **人の森側の合意** — 「同一グループに見える見た目」にすることについて、人の森側の意向確認。
   §2.6 は社名・グループ表記を出さない前提だが、見た目だけ寄せる状態の是非は当社では判断できない。
3. **額の分割単位（項目 13）** — ページを何枚の額に割るかは DOM 構造の変更を伴う。IA は不変だが
   `SiteChrome` の実装範囲が広がるため、採否をユーザーに確認したい。
4. **Noto Serif JP の実転送量と LCP 影響** — [推測] Google Fonts の unicode-range 分割で日本語は
   数百 KB 規模に収まるはずだが、実測していない。Lighthouse で before / after を取ること。
5. **`font-weight:500` の可否** — R3 は「禁止」としたが、Noto Serif JP のロードを
   `document.fonts.ready` まで待つ実装にすれば 500 も使える。工数との見合いでユーザー判断。
6. **`.hero-figure::after`「AI解析中」バッジ** — 静止させると意味が伝わりにくい。
   文言変更は禁止のため静止のまま残す案としたが、削除して `.hero-trust` に統合する案もある（情報の重複はある）。
