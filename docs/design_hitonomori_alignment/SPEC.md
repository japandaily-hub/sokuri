# カタヅケ × 人の森 デザイン整合 仕様書（v1 / 2026-09-03）

目的: カタヅケ（web/）の全ルートを、人の森株式会社コーポレートサイト（https://hitonomoricorp.jp）と
並べて違和感のない見た目・言葉遣いに再生成する。**情報・導線・機能・コピーの意味は一切変えない。**
変えるのは「書体・色・かたち・余白・UI部品の作法・句読点や記号の作法」だけ。

参照スクリーンショット（ローカルのみ・コミットしない）:
`C:\Users\ko13h\AppData\Local\Temp\claude\C--Users-ko13h-Claude-Projects-----\cab93df8-ed7d-4ab2-ae2e-4b293cc0b7c3\scratchpad\`
`hitonomori-top-full.png` / `hn-about-us.png` / `hn-company.png` / `hn-contact.png` / `hn-business_dx_.png` / `hn-mobile-top.png` / `hn-style.css`（テーマCSS原本 105KB）

---

## 1. 人の森サイトの分析結果（一次情報: 実測 computed style + テーマ style.css）

### 1.1 書体
| 用途 | 実測 |
| :-- | :-- |
| 和文すべて（本文・見出し・ナビ和文・表・フォーム） | `"游明朝体","Yu Mincho",YuMincho,"ヒラギノ明朝 Pro","Hiragino Mincho Pro",serif` **weight 400 のみ**（太字見出しを使わない） |
| 本文 | 16px / line-height 2.0（`.section .text` は 13px / 2em） / letter-spacing 0.05rem(=0.5px) / `font-feature-settings:"palt"` / `text-align:justify` |
| 大見出し（縦書き "人の森という物語"） | 明朝 54px 400、`::first-letter{color:#527e52}`（頭文字だけ緑） |
| 中見出し（"森は、やすらぎである。"） | 明朝 26px 400 **色 #959595（グレー）**、末尾に 1px×112px の短い横罫 |
| 英字ナビ（ABOUT US / COMPANY …） | `Montserrat` 600 uppercase 16px |
| 英字ディスプレイ（"Brand Statement" 縦書き） | `Libre Baskerville` |
| 英字セクションキャプション（COMPANY / ABOUT US を薄緑で） | `Noto Sans JP` bold uppercase 4.8rem 色 #c9d128 |
| 数値（電話番号・年） | 明朝そのまま。年表の月だけ Montserrat 緑 |

### 1.2 色
| 役割 | 値 | 出現 |
| :-- | :-- | :-- |
| **主色（苔色グリーン）** | `#527e52` | CSS内 90回。ボタン地・見出し頭文字・表の見出し列・必須バッジ・リンク下線 |
| 主色ホバー | `opacity:.8`（色は変えない） | |
| 差し色（黄緑ライム） | `#c9d128` | 英字キャプション・現在地ナビ・blob |
| 見出しグレー | `#959595` | h3 |
| 文字 | `#333`（body） / `#000`（本文 p） / `#666`（フッターリンク） | |
| 面（フォームパネル） | `#EFF3EF` / `#ECF1EC` / 表の見出し `#D9E3D9` | |
| 面（部署ごとのテーマ色） | 会社概要=クリーム `#fdf5d9` 系、ABOUT=ミント `#daf4eb`、CONTACT=若草 `#d4efb3`、DX=水色 `#e1f5fd` | 有機的な blob 形で右上から流れ込む |
| SMVV アクセント | 橙 `#f98b5a` / 赤 `#f46772` / 青 `#006ff9` | 見出し語のマーカー下線 |
| 汎用ボタン（Google map） | `#4e454a` 濃グレー | |
| 罫線 | `#ddd`（入力枠）/ 淡い黄緑ヘアライン（表） | |

### 1.3 かたち・レイアウト
- **ページ全体を 1px の線で額装**（`.section{padding:20px}` + `.wrap{border:1px solid}`）。白地の上に「一枚の紙」が置かれている印象。
- **角丸ゼロ**。ボタン・パネル・入力枠・部署ボックスはすべて直角。角丸は写真の円形マスクのみ。
- **影ゼロ**。立体感は使わず、ヘアラインと余白で区切る。
- **円形写真 + 細い緑リング（少しずらす）+ 破線コネクタ「- - -」**が写真の基本作法。
- 左固定の縦並びナビ（Montserrat 英字）・ロゴ左上。コンテンツ幅 760px 中心。2カラム本文。
- 縦書き（`writing-mode`/rotate）のセクション大見出しを右端に置く。
- 会社概要の表: 見出し列を緑文字・中央揃え・淡い黄緑ヘアライン。小見出しは **左の緑縦バー**（"本社"）。
- リスト: `■`（緑）と `●` の記号箇条書き。DNA一覧は **緑文字の細枠タグ**（角丸なし）。
- フォーム: `#EFF3EF` の直角パネル、白い入力枠 1px `#ddd`、**必須=緑地白文字 / 任意=グレー地白文字の直角バッジ**、送信は緑直角ボタン `padding:16px 40px`。
- フッター: 白地・中央揃え・「プライバシーポリシー」極小リンク + `© Copyright … All rights reserved.`
- 余白: 非常に広い。セクション上下 128px 級。
- モーション: フェードインのみ（animate.css）。ホバーは opacity .8。持ち上がり・グロー・スキャン演出は無い。

### 1.4 言葉の作法
- 引用符は **「」**（“ ” は使わない）。三点リーダは「…」、ダッシュは使わない。
- 感嘆符「！」を使わない。静かな断定調（「〜である。」「〜していきます。」）。
- 英字ラベルは大文字（ABOUT US）で和文見出しに**添える**（主役は和文）。
- リンク文言は「人の森について知る」+ 小さく「ABOUT US」の二段。

---

## 2. カタヅケへの写像（設計）

### 2.1 基本方針
1. **トークン層の差し替えを主戦場にする。** `katazuke.css :root` の変数値を人の森の値へ置き換え、旧変数名（`--blue` 等）は**新しい意味変数へのエイリアスとして残す**（39本の per-page CSS を壊さない）。
2. **かたちの作法を共通部品で置き換える**: ボタン直角・影ゼロ・ヘアライン・円形写真・額装フレーム・縦書き見出し。
3. **ページ固有 CSS のハードコード色（合計 ~600 箇所）をトークン参照へ寄せる。** 青系 rgba は緑系へ。
4. **コピーは意味不変。** 句読点・記号だけ人の森の作法へ正規化（“ ”→「」、——→削除または「、」、「！」→「。」）。変更箇所は一覧で報告する。
5. **LINE ブランド緑 `#06c755` は据え置き**（ブランドガイドライン）。ただし形は直角。
6. **金額・数値**は明朝 + `tabular-nums`（Noto Serif JP は tnum 対応）。

### 2.2 新トークン（`web/src/app/katazuke.css` の `:root`）
```css
:root{
  /* 主色 = 人の森 苔色 */
  --primary:#527e52;  --primary-d:#3f6640;  --primary-l:#7fa37f;  --deep:#2f4a30;
  --lime:#c9d128;     /* 英字キャプション・現在地 */
  /* 文字 */
  --navy:#333333;  --ink:#333333;  --body:#4a4a4a;  --body-soft:#959595;
  /* 罫線・面 */
  --line:#d9e0d6;  --line-soft:#ecf1ec;
  --white:#fff;  --pale:#eff3ef;  --pale-2:#f6f8f4;  --warm:#fdf5d9;  --mint:#daf4eb;  --sky:#e1f5fd;
  /* アクセント */
  --apricot:#f3981d;  --green:#527e52;  --gold:#e5a323;  --danger:#d70035;
  /* かたち */
  --radius:0px;  --radius-s:0px;  --radius-photo:50%;
  --shadow-s:none;  --shadow-m:none;  --shadow-l:none;  --glow:none;
  --frame:1px solid #333;
  --ease:cubic-bezier(.22,.61,.36,1);  --maxw:1140px;  --maxw-text:760px;
  /* 書体 */
  --serif:"Yu Mincho","YuMincho","游明朝体","Hiragino Mincho ProN","Hiragino Mincho Pro","Noto Serif JP",serif;
  --head:var(--serif);  --sans:var(--serif);  --num:var(--serif);
  --en:"Montserrat",sans-serif;  --en-display:"Libre Baskerville",serif;
  /* 旧名エイリアス（per-page CSS 互換） */
  --blue:var(--primary);  --blue-d:var(--primary-d);  --blue-l:var(--primary-l);
}
```
- 本文: `font-size:15px`（app画面は14px）/ `line-height:2` / `letter-spacing:.05em` / `font-weight:400` / `palt`。
- 見出し: `font-family:var(--head)` / **weight 400**（Noto Serif フォールバック時は 500 可）/ `letter-spacing:.04em` / `line-height:1.6`。`h2::first-letter{color:var(--primary)}`。
- Google Fonts: `Noto+Serif+JP:wght@400;500;600` + `Montserrat:wght@600` + `Libre+Baskerville:wght@400;700`。Zen Maru / Zen Kaku / Noto Sans JP は**読み込みを止める**（ブランド書体が二重に載るのを防ぐ）。
- Tailwind `tailwind.config.ts` は同値へ同期（`brand-600=#527e52`、`kdz-*`、`font-head/sans/serif/en`、`rounded-kdz=0`、影は none）。

### 2.3 共通部品の作法（`katazuke.css` / `katazuke-pages.css`）
| 部品 | 現行（v2 コバルト） | 人の森整合版 |
| :-- | :-- | :-- |
| ボタン `.btn` | 丸ピル・グロー影・持ち上がり | **直角**・`padding:16px 40px`・明朝 15px `letter-spacing:.1em`・primary 緑地白文字・hover は `opacity:.8`（色変化なし・移動なし）。`.btn-ghost` は 1px 緑枠 + 緑文字（人の森 `.company__link--btn`）。`.btn-line` は LINE 緑地のまま直角。`.btn-white` は白地緑文字 |
| アイブロウ `.eyebrow` | 青ピル | 背景なし。明朝 13px 緑 `letter-spacing:.12em`、先頭に 24px の緑ヘアライン（`::before`）。文言はそのまま |
| セクション見出し `.section-head h2` | 丸ゴシック 700 | 明朝 400 `clamp(24px,3vw,34px)` 色 `#333`、直下に中央 1px×48px の緑罫（人の森「本社・事業所」の作法）。`.sub` は 15px / 2.0 / `#4a4a4a` |
| セクション縦書き見出し | なし | `section[data-vt]::after{content:attr(data-vt)}` を右端に `writing-mode:vertical-rl` 明朝 34px 400 `#333` `::first-letter` 緑。≥1180px のみ表示。ランディング主要6セクションに `data-vt` を付与（見出し文言と同一） |
| カード（emp/step/scene/trust/bundle/cat） | 24px 角丸・影・hover 浮上 | 直角・`1px solid var(--line)`・影なし・hover は `border-color:var(--primary)` のみ。写真は直角 |
| ヒーロー | 弧・スキャン線・AI解析中バッジ・4/3 角丸写真 | 右上から流れ込む淡い若草 blob（`border-radius:42% 58% 55% 45%/48% 42% 58% 52%` の大楕円 `#eef4de`）。写真は**円形マスク**（`aspect-ratio:1/1; border-radius:50%`）+ 6px 外側に 1px 緑リング（`::before`）+ 左右に破線コネクタ（`::after` `border-top:1px dashed #333`）。スキャン線・パルスは削除。「AI解析中」バッジは直角の白地緑文字（静止）。h1 明朝 400 `clamp(30px,4.6vw,50px)` line-height 1.6、`.hl` は緑文字 + 下線マーカー（`background:linear-gradient(transparent 70%, #d4efb3 70%)`） |
| 信頼帯 `.assure` | 淡コバルト面 | 白地、上下ヘアライン。アイコンタイルは 1px 緑枠の直角 |
| 数字バッジ（ステップ番号 / FAQ Q / 入札順） | 青丸 | `Libre Baskerville` 緑文字、円や角丸地なし。ステップは「01」二桁表記に見えるよう `font-size:22px`。DOMの数字は変えない（`.num::before{content:"0"}` で桁を補う） |
| 料金カード `.fee-card` | 角丸・warm ヘッダ | 直角・1px 枠・ヘッダは `#eff3ef`。`.fv` は明朝 600 緑 |
| 業者バナー `.biz-banner` | 濃紺グラデ | `#eff3ef` パネル + 1px 枠。h2 明朝 `#333`。タグは緑細枠タグ（DNA一覧の作法）。ボタンは緑直角 |
| FAQ `.faq-item` | 角丸カード | 角丸なし。上下ヘアラインで区切るリスト。Q マークは Libre Baskerville 緑 |
| 最終CTA `.final` | 光グラデ | 白地 + 若草 blob を左下に薄く。スタッフ円写真は残す（円形は作法に合う） |
| フッター `.footer` | 濃紺 | **白地**・上ヘアライン・4カラムは残す（導線不変）が文字 12px `#666` 明朝・h5 は Montserrat 600 uppercase 11px 緑。`footer-bottom` は中央揃え `© 2026 カタヅケ` |
| ヘッダー `.header` | 半透明ぼかし | 白地・下ヘアライン・高さ 72px・ナビは明朝 14px `letter-spacing:.12em`、現在地は緑。ぼかしなし。CTA は直角 LINE 緑 |
| ロゴ `KdzLogo` | 紺+黄の PNG | **文字ワードマーク**へ切替: 「カタヅケ」明朝 500 `letter-spacing:.14em` + 直下に `KATAZUKE` Montserrat 600 9px `letter-spacing:.32em` 緑。PNG は OG/apple-icon 用に残す（PNG は紺+金で緑と衝突するため。正式ロゴの緑版は**要ユーザー提供**） |
| 額装フレーム | なし | `SiteChrome` の共通クロム側ルート（マーケ系）で `<div class="site-frame">` に包む: ≥860px で `margin:20px; border:var(--frame); min-height:calc(100vh - 40px)`。sticky header は frame 内で `top:0` のまま動作 |
| モバイル Dock | 半透明 | 白地・上ヘアライン。ボタン直角 |
| スクロール進捗 | 3px 青グラデ | 2px 緑単色 |
| Reveal `.rv` | translateY(22px) | `opacity` のみ（人の森=fade のみ） |
| フォーム `.field` | 角丸 16px・青フォーカスリング | 直角・1px `#ddd`・focus は `border-color:var(--primary)`（リングなし）・ラベル明朝 14px。必須=`.req{background:#527e52;color:#fff;padding:2px 10px}` 任意=`#808080` |
| テーブル（company/vendor/mypage） | | 見出しセルは緑文字 中央 `#ecf1ec` 地、罫線 `#d9e0d6` |
| 小見出し（app画面の h3/h4） | | 左に 2px 緑縦バー `padding-left:12px` |
| タグ・バッジ（ステータス等） | 丸ピル | 直角・細枠。意味色: 進行=緑 / 注意=`#e5a323` / 危険=`#d70035` / 中立=`#959595` |
| アイコン `.ic` | stroke 1.9 | stroke 1.5、色は文脈色（緑） |

### 2.4 ページ固有 CSS の扱い（39ファイル）
- `#1447e0` / `#1f54de` / `rgba(20,71,224,…)` / `rgba(31,84,222,…)` / `rgba(15,37,82,…)` / `#0f2552` / `#122a6b` / `#101f4a` → `var(--primary)` / `rgba(82,126,82,α)` / `var(--deep)`。
- `#241f1c` `#2f2924` `#5e5750` `#8d857c` → `var(--navy)` `var(--ink)` `var(--body)` `var(--body-soft)`。
- `#ebe5dd` `#f4f0ea` `#f0f5ff` `#f4f7ff` `#eef3ff` → `var(--line)` `var(--line-soft)` `var(--pale)` `var(--pale-2)`。
- `border-radius` の 8px 以上 → `var(--radius)`（=0）。`box-shadow` は `none` か `var(--shadow-*)`。
- `font-weight:900|800|700` の見出し → `500`（明朝は太らせない）。`font-family` の Zen/Noto Sans 直書き → `var(--head)`。
- `translateY(-Npx)` のホバー持ち上がり → 削除。`backdrop-filter` → 削除。
- 状態色（成功=green/注意=amber/危険=red）は意味を保って上記の意味色へ。

### 2.5 言葉の作法（コピー不変・記号のみ）
| 対象 | 変換 |
| :-- | :-- |
| `“…”` / `"…"`（和文中） | `「…」` |
| `——` `—` | 削除して読点、または「。」で文を切る（意味不変の範囲で） |
| `！` | `。`（CTAボタン文言は据え置き可） |
| 英字アイブロウ | 既に和文化済み。据え置き |
| 数字 | 半角のまま |
変更は `docs/design_hitonomori_alignment/WORDING_CHANGES.md` に「ファイル / 変更前 / 変更後」で全件記録する。

### 2.6 やらないこと
- 人の森のロゴ・マスコット・写真・イラスト・blob 画像等の**アセット流用は一切しない**（著作権）。色値・書体・作法だけを参照する。
- 「人の森」の社名・グループ表記を**カタヅケ側に追加しない**（内容不変の原則。追記は別途ユーザー判断）。
- 情報設計・ルート・導線・機能・文章の意味の変更。
- 左固定縦ナビへの構造変更（サービスサイトとして CTA 到達性を優先。ヘッダーは上部のまま人の森の作法で描く）。

---

## 3. 完成条件（DoD）
1. `npm run build`（web/）が成功し、`tsc --noEmit` エラーなし。
2. 全41ルートで Zen Maru / Zen Kaku / Noto Sans JP / コバルト `#1447e0` `#1f54de` が**computed style に出現しない**（Playwright で全ルートを巡回して検査）。
3. 主要7画面（/ /faq /examples /company /contact /business /login）のスクリーンショットを人の森トップと並べ、独立レビュアーが「同一グループのサイトに見える」と判定（4段階で3以上）。
4. アクセシビリティ: 本文コントラスト `#4a4a4a`/白 ≥ 7:1、緑ボタン `#527e52`/白 = 4.6:1（AA 合格）、focus-visible が全ボタン・リンクで可視。
5. `docs/design_hitonomori_alignment/WORDING_CHANGES.md` に記号変換の全件記録。
6. `web/DESIGN_SYSTEM.md` §10 に本テーマの正典を追記（§9 は「廃止・履歴」に格下げ）。
7. security-reviewer / qa-reviewer の並列レビューで Critical/High ゼロ。
