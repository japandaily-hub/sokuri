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
