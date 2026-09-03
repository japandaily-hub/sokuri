# カタヅケ — デザインシステム

査定額という金銭情報を扱う Web プロダクトとして、方向性は **「信頼感・クリーン系」（フィンテック寄り）** に固定する。
本書はデザイントークンの正典であり、`web/` 配下の全画面・全コンポーネントはここに従う。アドホックな色・余白指定は禁止する。

実体は `tailwind.config.ts`（トークン）と `src/app/globals.css`（ベース／ユーティリティ）に定義済み。

---

## 1. 配色

### 基幹カラー `brand-*` — 深く落ち着いた真の青
信頼感の主軸。CTA・リンク・選択状態・見出しのアクセントに使う。

| トークン | HEX | 用途 |
| :-- | :-- | :-- |
| `brand-50` / `brand-100` | `#eef4ff` / `#d9e6ff` | 淡い面・選択中の背景・バッジ地 |
| `brand-600` | `#1f54de` | **Primary action**（主CTA・選択状態の枠） |
| `brand-700` | `#1c44b4` | ホバー |
| `brand-900` | `#1d3677` | 見出し・ダーク面 |
| `brand-950` | `#141f48` | フッター・ヒーロー深部 |

### 補助カラー `accent-*` — エメラルド
「価値・成功・前向き」のシグナル専用。チェックマーク、肯定的な比較結果、完了状態に限定。多用しない。

### 中立カラー — Tailwind 標準 `slate-*`
背景は `slate-50`、本文は `slate-600`、見出しは `slate-900`、境界線は `slate-200`。
冷たみのあるグレーで、青系ブランドと調和しクリーンに見える。

### 状態色
エラー = `red-*`、注意 = `amber-*`、PR/広告表記 = `amber-*` のバッジ。中立な相場提示と広告性のある送客はUI上で必ず分離する（ステマ規制対応）。

---

## 2. タイポグラフィ

- フォント: OS標準の和文ゴシック + 欧文サンセリフのスタック（`tailwind.config.ts` の `fontFamily.sans`）。Webフォント非依存でビルドが安定。
- 約物詰め `font-feature-settings: "palt"` を `body` に適用済み。
- ウェイトは **`font-semibold`〜`font-bold` を基本**とする。`font-black` は原則禁止（信頼感より圧の強さが勝ってしまう）。
- 価格・件数など数値には `tabular-nums` を付け、桁のブレを防ぐ。

| 役割 | クラス目安 |
| :-- | :-- |
| ヒーロー見出し | `text-4xl sm:text-5xl font-bold tracking-tight leading-[1.15]` |
| セクション見出し | `text-2xl sm:text-3xl font-bold tracking-tight` |
| カード見出し | `text-base font-semibold` |
| 本文 | `text-sm sm:text-base text-slate-600 leading-relaxed` |
| 補足 | `text-xs text-slate-500` |
| アイブロウ（小見出し） | `text-xs font-semibold uppercase tracking-[0.18em] text-brand-600` |

---

## 3. 余白・レイアウト

- コンテナ: `.container-aw`（`max-w-container` = 72rem + レスポンシブ左右余白）。全画面で統一。
- セクション縦余白: `py-16 sm:py-20 lg:py-24`。
- 余白は 8px グリッドの倍数（`gap-2/3/4/6/8`、`p-4/5/6/8`）で揃える。
- 査定フロー（analyzing / condition / result）はカード中心の単カラム。読み手の視線移動を最小化する。

---

## 4. 角丸・影

| 要素 | 角丸 | 影 |
| :-- | :-- | :-- |
| カード | `rounded-2xl` | `shadow-card` →（hover）`shadow-card-hover` |
| 浮遊カード（アップロード等） | `rounded-2xl` | `shadow-elevated` |
| ボタン・入力 | `rounded-xl` | 主CTAは `shadow-cta` |
| ピル・バッジ | `rounded-full` | なし |

影は4段階（`xs` / `card` / `card-hover` / `elevated` / `cta`）のみ。これ以外を使わない。

---

## 5. コンポーネント規約

- **ボタン**: hover / `focus-visible` / active / disabled の4状態を必ず定義。タップ領域は高さ44px以上。
- **アイコン**: 絵文字を使わない。線画SVGアイコン `src/components/Icon.tsx` に集約。`stroke-width` 1.75 前後で統一。
- **ステッパー**: 査定フローの進捗は `src/components/Stepper.tsx` で共通化（画像解析 → コンディション → 査定）。
- **フォーカス**: キーボード操作でリングが必ず見えること（`focus-visible:ring-2 focus-visible:ring-brand-600 ring-offset-2`）。
- **状態網羅**: loading / empty / error は専用の見た目を用意し、本体UIと統一トーンで描く。

---

## 6. モーション

控えめ・上品に。`tailwind.config.ts` 定義の `fade-up` / `fade-in` / `scan` / `shimmer` のみ使用。
`globals.css` で `prefers-reduced-motion` を尊重済み。

---

## 7. レビュー / 拡張

UIの新規設計・改善・レビューは `.claude/agents/ui-designer.md`（デザイナーエージェント）に依頼する。
本書を更新したら、エージェント定義の該当箇所も同期すること。

---

## 8. デザインハンドオフ移行（2026-06／feat/design-handoff-katazuke）

高忠実度ハンドオフ `docs/design_handoff_katazuke/`（33画面）を正典として採用し、本書の旧方針を以下で上書きする。

- **正典CSS**: `src/app/katazuke.css`（ハンドオフ `katazuke-main.css` を移植）。`globals.css` から
  `@layer base, components, utilities;` → `@import "./katazuke.css" layer(components);` で取り込む。
  これにより Tailwind utilities が常に上書きでき、既存 Tailwind ページの余白も壊さない。
- **フォント**: 旧「Webフォント非依存」を撤回。**Zen Kaku Gothic New（見出し900）+ Noto Sans JP（本文）**を
  `globals.css` の `@import url()` で実行時ロード（ビルド非依存）。フォールバックに OS 標準ゴシックを残す。
- **font-black（900）**: 旧「原則禁止」を撤回。見出し・価格はハンドオフ通り 900 を使用する。
- **トークン**: `tailwind.config.ts` に `kdz-*`（navy/ink/body/pale/line/green/gold/LINE green）、`shadow-kdz-s/m/l`、
  `rounded-kdz`、`font-head` を追加。`.container`（Tailwind core）は `corePlugins.container:false` で無効化
  （ハンドオフ `.container` max-width:1140px と衝突回避）。
- **共通部品**: `src/components/kdz/`（Icons[スプライト+Ic]/interactions[Reveal,PhImg,FaqAccordion,ScrollProgress]/
  SiteHeader/chrome[SiteFooter,Dock]/SiteChrome[ルート別クロム出し分け]/Logo[SVGワードマーク]）。
- **画像**: ハンドオフに同梱なし。`PhImg` がプレースホルダで堅牢化。実アセット（ロゴ/写真/カテゴリ）は**[要ユーザー提供]**。
- 進捗とDoDは リポジトリ直下 `KATAZUKE_REDESIGN_PLAN.md` で管理する。

---

## 9. v2 テーマ「White × Cobalt / あたたかさとつながり」— **廃止（履歴）**

> **廃止（2026-09-03）。** 本節は履歴として残す。現行の正典は **§10「人の森整合テーマ」**。
> 本節に出てくる色値（`#1447e0` `#241f1c` `#ebe5dd` 等）・書体（Zen Maru / Zen Kaku）・角丸・影は
> **もう使わない**。新規実装で参照しないこと。

方向性を **「White × Cobalt / あたたかさとつながり」** へ振った試作を、全41ルートの正典として本採用していた。
Refero Styles の DESIGN.md（Notion = warm paper／Superr = cream + matte／Authkit = frosted light）から
**暖色ニュートラル・ヘアライン・大角丸・拡散する光** の4原則だけを採用し、色相はコバルトへ置換している。

- **実体**: 試作用の別ファイル `src/app/katazuke-v2.css` は廃止し、正典 `src/app/katazuke.css` へ
  マージ済み。`tailwind.config.ts` の `brand-600/700` / `kdz-*` / `shadow-kdz-*` / `rounded-kdz*` /
  `font-head` も新トークンへ同期済み。
- **適用範囲**: 全41ルート。`<main data-kdz="v2">` によるスコープ限定は撤去し、`:has()` 依存は解消済み。

### v1 からの主な差分

| 項目 | v1 | v2 |
| :-- | :-- | :-- |
| 見出し書体 | Zen Kaku Gothic New 900 | **Zen Maru Gothic 700**（丸ゴシック＝親しみの主因子） |
| 見出し色 | `#0f2552` 寒色ネイビー | `#241f1c` ウォームニアブラック |
| 本文色 | `#3f4a60` 青みグレー | `#5e5750` 暖色グレー |
| 罫線 | `#e4e8f0` 寒色 | `#ebe5dd` 暖色ヘアライン |
| ブランド青 | `#1f54de` | `#1447e0` コバルト（彩度を一段上げ） |
| 角丸 | 18px | 24px（カード）／28px（ヒーロー写真） |
| 影 | 濃紺の落ち影 | コバルトを帯びた拡散光（`--glow`） |
| 信頼の帯 | 濃紺ベタ | 淡コバルト面（ページ全体の重さを抜く） |
| ヒーロー | 平坦なグラデ | 重なる2つの弧（＝つながり）＋ AI解析スキャン演出 |

### 意図的に据え置いた点
- **金額・数値は角ゴシック + `tabular-nums` に固定**（`--num`）。丸ゴシックに寄せると査定額の信頼感が落ちるため。
- LINEブランドグリーン `#06c755` は不変。
- レイアウト・情報設計・コピーは一切変更していない（純粋なビジュアル層の差し替え）。

### 残タスク
- アイブロウの英字ラベル（YOUR WORRIES / PRICING / FOR BUYERS）の和文化 — 全ルートで実施済み。

---

## 10. 人の森整合テーマ（2026-09-03 本採用／同日 主色をブルーへ変更）

現行の正典。`src/app/katazuke.css :root` が実体で、`tailwind.config.ts` はその写し。
仕様の一次資料は `docs/design_hitonomori_alignment/SPEC.md` §1 と `SPEC-4-decisions.md`（確定事項）。
**情報・導線・機能・コピーの意味は不変。変えたのは書体・色・かたち・余白・記号の作法だけ。**

> **2026-09-03 追記**: 本採用直後にユーザー指示で主色を人の森の苔緑からブルー（コバルト系
> `#1447e0`）へ変更した。書体（明朝）・角丸ゼロ・影ゼロ・額装・縦書き見出し等の「かたち」の作法は
> 人の森整合のまま維持し、**色相だけ**ブルーへ差し替えている。以下の表は変更後の値が正典。
> 「成功/完了」を示す `--green` は主色と衝突しないよう緑系のまま独立させた（青=ブランド、緑=状態）。

### 10.1 トークン

| 役割 | 変数 | 値 | 備考 |
| :-- | :-- | :-- | :-- |
| 主色（ブルー） | `--primary` | `#1447e0` | 白と 6.98:1（AA 合格）。ボタン地・見出し頭文字・必須バッジ |
| 主色 濃/淡 | `--primary-d` / `--primary-l` | `#0f37b4` / `#5f86ee` | `--primary-d` は白と 9.43:1。`--primary-l` は非文字コントラスト 3:1 以上（境界線・アイコン用） |
| 沈めた青 | `--deep` | `#14235c` | ダーク面・トースト |
| 差し色（ライトブルー） | `--lime` | `#8fb4ff` | 英字キャプション・現在地・白抜きロゴの英字（トークン名は旧称のまま） |
| マーカー | `--marker` | `#d7e6ff` | 強調の下線（`linear-gradient(transparent 68%, … 68%)`） |
| 文字 | `--navy` / `--ink` / `--body` | `#20242e` / `#20242e` / `#454e59` | 白と各 15.52:1 / 15.52:1 / 8.44:1 |
| 補助文字 | `--body-soft` | `#63707b` | 白と 5.08:1。**小さい補助テキストは必ずこれ** |
| 見出しグレー | `--head-gray` | `#959595` | 白と 3.0:1。**24px 以上の見出し専用**。本文に流用しない |
| 罫線・面 | `--line` / `--line-soft` / `--pale` / `--pale-2` | `#dce3ea` / `#eef1f6` / `#eef3ff` / `#f4f7fc` | |
| 面（文脈色） | `--warm` / `--mint` / `--sky` | `#fdf5d9` / `#daf4eb` / `#e1f5fd` | ブランド色相と独立の副次アクセント。据え置き |
| 状態色 | `--green` / `--gold` / `--danger` | `#15803d` / `#e5a323` / `#d70035` | 完了 / 注意 / 危険。主色（青）とは別系統。中立は `--body-soft` |
| かたち | `--radius` / `--radius-s` / `--shadow-*` / `--glow` | `0px` / `0px` / `none` | **角丸ゼロ・影ゼロ** |
| 額装 | `--frame` | `1px solid #333` | `.site-frame` |
| 幅 | `--maxw` / `--maxw-text` | `1140px` / `760px` | |
| 旧名エイリアス | `--blue` / `--blue-d` / `--blue-l` | `var(--primary)` 系 | 39本の per-page CSS 互換のため残す |

### 10.2 書体

| 用途 | 変数 | スタック |
| :-- | :-- | :-- |
| 見出し・地の文 | `--serif` = `--head` = `--sans` | `"Noto Serif JP","Hiragino Mincho ProN","Hiragino Mincho Pro","Yu Mincho","YuMincho","游明朝体",serif` |
| 入力値・数値・小ラベル | `--ui` = `--num` | `"Noto Sans JP","Hiragino Kaku Gothic ProN","Yu Gothic UI",sans-serif` |
| 英字ラベル | `--en` | `"Montserrat",sans-serif`（600 / uppercase） |
| 英字ディスプレイ（番号・Q） | `--en-display` | `"Libre Baskerville",serif` |

- **Noto Serif JP を先頭に置く。** Android には明朝が1書体も入っておらず、webfont が当たらないと再設計が一切見えない。
- **明朝で使うウェイトは 400 と 600 のみ。500 は禁止**（游明朝に実ウェイトが無く、合成太字で字画が滲む）。
- `-webkit-font-smoothing:auto` / `-moz-osx-font-smoothing:auto`。**`antialiased` は付けない**（明朝 400 が痩せる）。
- 本文: マーケ面 16px / 2.0、app 地の文 15px / 1.75、表セル・確認行 14px / 1.6、チャット吹き出し 15px / 1.7。
- 字送り: 本文 `.03em` / 見出し `.04em` / ボタン `.1em`。
- **入力値・数値をゴシックにする根拠**: 住所・メール・電話・金額を明朝 400 で出すと `1/l/I`・`0/O`・全角半角の
  判別が落ち、入力ミスの発見コストが上がる。ラベル・説明・見出しは明朝のままなので面の印象は変わらない
  （書体の印象を担うのは見出し・面・かたちであり、入力値の寄与は小さい）。

### 10.3 かたちの作法

- 角丸ゼロ・影ゼロ・`backdrop-filter` なし。区切りは 1px のヘアラインと余白。
- 円形が許されるのは **アバター（`.cta-staff`）とドット**だけ。ピル（999/99/9999px）は 0 へ。
- カードは枠も面も持たない（`.emp-card` `.step` `.scene-card` `.trust-c` `.bundle-c`）。枠を持つのは
  `.cat-img`（写真）とフォームパネルだけ。強調1枚は `--pale` 面 + 左 3px の緑バー。
- リズムは罫線で作る: `.section-head h2::after`（1px×48px 緑）、`h2::first-letter{color:var(--primary)}`。
- ホバーは `opacity` のみ（`.btn:hover{opacity:.8}` / 画像 `.85`）。持ち上がり・グロー・スキャンは使わない。
- Reveal（`.rv`）は fade のみ。`translateY` は使わない。
- 額装フレーム `.site-frame`: `margin:20px; border:var(--frame); min-height:calc(100dvh - 40px)`。
  **`overflow` を書かない**（内側の `position:sticky` が全ページで死ぬ）。860px 未満では枠を出さない。
- 縦書き見出し `.vt` は**実要素 + `aria-hidden`**（擬似要素の `content` は SR が二重読みする）。
  `min-width:1280px` のみ・`#bundle` と `#auction` の2箇所だけ。

### 10.4 共通クラス

| クラス | 用途 |
| :-- | :-- |
| `.site-frame` | 額装フレーム。`SiteChrome` が `/` 以外で `children` を包む |
| `.vt` | 右端の縦書き見出し（PC のみ・2セクション限定） |
| `.mk` | 引用符の代わりの緑マーカー強調。`.hl` はマーカー + 緑文字 |
| `.kdz-wm` / `.kdz-wm-ja` / `.kdz-wm-en` | 二段ワードマーク。`--wm` で和文サイズを渡す。`.white` で白抜き |
| `.hero-blob` | ヒーロー右上の若草 blob（`.hero` 直下先頭に1つ） |
| `.req` / `.opt` | 必須（緑地白文字）/ 任意（グレー地白文字）の直角バッジ |

### 10.5 アクセシビリティ

- `:focus-visible{outline:2px solid var(--primary);outline-offset:2px;border-radius:0}`。
  **リングは消さない**（1px の枠色変化だけでは WCAG 2.2 Focus Appearance の周長要件を満たさない）。
- 本文 `#4a4a4a`/白 = 8.6:1、補助 `#6b6b6b`/白 = 5.3:1、緑ボタン白文字 = 4.70:1。
- **LINE ブランド色 `#06c755` は AA 対象外の文書化例外。** 白抜き文字とのコントラストは 2.29:1 だが、
  LINE のブランド規約が白抜きを指定しているため据え置く。条件: **単独導線にしない**（必ず別 CTA を併置し、
  LINE アイコンと「LINE」の語を残す）。`.btn-line-auth` の角丸 99px も公式ボタン仕様として据え置く。

### 10.6 言葉の作法（意味は不変・記号のみ）

- 引用符 `“ ”` は使わない。強調語は `.mk`、会話・言葉の引用は「」。1段落に鉤括弧を3組並べない。
- 本文のダッシュ `——` `—` は「、」「。」で切る。metadata / title の ` — ` は `｜`。
- `！` は使わない（`。`）。欠損値フォールバックの `"—"` とコードコメントは据え置き。
- 変更記録は `docs/design_hitonomori_alignment/WORDING_CHANGES_*.md`。

### 10.7 やらないこと

- 人の森のロゴ・写真・イラスト・blob 画像等の**アセット流用**（色値・書体・作法だけを参照する）。
- 「人の森」の社名・グループ表記のカタヅケ側への追加。
- 情報設計・ルート・導線・機能・文章の意味の変更。
