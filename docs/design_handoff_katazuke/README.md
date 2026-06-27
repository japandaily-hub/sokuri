# Handoff: カタヅケ — 家まるごと片付け買取プラットフォーム

## Overview
カタヅケは、家の不用品をまとめて複数の業者に入札してもらい、最高額で手放せる買取マッチングサービスです。このハンドオフパッケージには、ユーザー向け・業者向けすべての画面のHTMLデザインリファレンスが含まれています。

## About the Design Files
このフォルダに含まれるHTMLファイルは、**デザインリファレンス（プロトタイプ）** です。本番コードをそのまま使用するものではありません。Claude Codeの作業は、これらのHTMLをベースに、**本番環境のコードベース（React / Next.js / Vue 等）のパターンと既存コンポーネントを使って忠実に再実装すること**です。フレームワークが未定の場合は Next.js (App Router) + Tailwind CSS の採用を推奨します。

## Fidelity
**高忠実度（High-fidelity）** — 色・タイポグラフィ・スペーシング・インタラクションすべてが最終仕様に近い状態です。ピクセル精度で再現することを目標としてください。

---

## Design Tokens

### Colors
```
--blue:       #1f54de   ブランドカラー
--blue-d:     #1742b0   ホバー・アクティブ
--navy:       #0f2552   見出し・信頼感
--ink:        #16213a   本文（濃）
--body:       #3f4a60   本文
--body-soft:  #697288   補助テキスト
--line:       #e4e8f0   罫線
--line-soft:  #eef1f7   薄い罫線
--pale:       #eef3ff   淡ブルー背景面
--green:      #1f8a5b   安心・成功・無料
--gold:       #b9892f   ゴールド
--white:      #ffffff
```

### Typography
```
--head: "Zen Kaku Gothic New", sans-serif   見出し・ブランド
--sans: "Noto Sans JP", sans-serif          本文
```
フォントウェイト: 400 / 500 / 600 / 700 / 900

### Spacing & Radius
```
--radius:   18px   カード・大要素
--radius-s: 12px   小カード・入力フィールド
```

### Shadows
```
--shadow-s: 0 2px 10px -4px rgba(15,37,82,.14)
--shadow-m: 0 16px 36px -20px rgba(15,37,82,.30)
--shadow-l: 0 32px 70px -34px rgba(15,37,82,.40)
```

---

## Screens / Views

### 1. トップページ (`カタヅケ.html`)
**Purpose:** サービスのLP。ユーザーが出品登録へ進む起点。

**Layout:** 最大幅 1140px、`padding-inline: 24px`
- Sticky header (height: 76px) — ロゴ左、ナビ中央、CTA右
- Hero: 2カラムグリッド (1.05fr / 0.95fr)、モバイルは1カラム
- 各セクション: `padding: clamp(64px,8vw,108px) 0`

**Key Components:**
- **ヘッダー:** ロゴ(h:54px)、ナビリンク(14px/600)、LINEボタン、ハンバーガー(モバイル)
- **ヒーロー:** h1 `clamp(32px,5.2vw,58px)` / Zen Kaku Gothic / 900weight
- **Green CTAボタン:** `background:#06c755` / `border-radius:999px` / `padding:17px 30px`
- **Blueボタン:** `background:#1f54de` / 同形状
- **追従CTA(モバイル):** `position:fixed; bottom:0; display:flex; padding:12px 16px`

**Navigation:**
- PC: ロゴ → `成約事例.html` / `撮影ガイド.html` / `よくある質問.html` / `ログイン.html` → CTA
- Mobile: ハンバーガー → ドロワー + `ログイン.html` / `マイページ.html`

---

### 2. ログイン (`ログイン.html`)
**Purpose:** 既存ユーザーのログイン。LINE認証 or メール+パスワード。

**Layout:** 背景 `#f4f6fb`、カード最大幅 440px、中央揃え

**Components:**
- **上部バー:** 高さ 68px、ロゴ左、「新規登録はこちら」右
- **カードシャドウ:** `0 4px 32px -8px rgba(15,37,82,.16)`
- **LINEボタン:** `background:#06c755` / `border-radius:99px` / `padding:16px 20px` / `font-size:15.5px`
- **仕切り:** `display:flex; align-items:center` + 両端線
- **入力フィールド:** `background:#fafbfe` / `border:1.5px solid #e4e8f0` / `border-radius:12px` / `padding:12px 14px`
  - フォーカス: `border-color:#1f54de` / `box-shadow:0 0 0 3px rgba(31,84,222,.12)`
  - エラー: `border-color:#e05c5c`
- **パスワード強度バー:** 3分割バー、弱=`#e05c5c`、普通=`#f0a030`、強=`#1f8a5b`
- **信頼行:** 小アイコン + テキスト 3点（SSL / プライバシー / 無料）
- **パスワードリセットモーダル:** `backdrop-filter:blur(4px)` / `background:rgba(15,37,82,.45)`

**Validation:**
- メール: `@` 含む必須
- パスワード: 8文字以上

**Redirects:**
- ログイン成功 → `申し込み状況.html`
- LINE認証 → `申し込み状況.html`

---

### 3. 新規登録 (`新規登録.html`)
**Purpose:** 3ステップの会員登録フロー。

**Layout:** flow-header (sticky) + step-pane + fixed footer ボタン

**Flow:**
```
Step 1: メール + パスワード (+ LINE登録)
Step 2: お名前 + エリア選択（チップUI）+ 利用目的（カード選択）
Step 3: 確認画面 + 利用規約同意 → 登録
→ リダイレクト: メール確認完了.html
```

**flow-header:**
- 高さ: sticky、ロゴ + ステップインジケーター
- ステップドット: 24px円、done=`#1f54de`背景、active=ドット+`box-shadow:0 0 0 4px rgba(31,84,222,.18)`
- ステップ間コネクター: `height:2px` / done時=`#1f54de`

**エリア選択チップ:**
- グリッド: `repeat(3,1fr)` → モバイル `repeat(2,1fr)`
- 選択時: `border-color:#1f54de; background:#1f54de; color:#fff`

**利用目的カード:**
- 2カラムグリッド → モバイル1カラム
- 選択時: `border-color:#1f54de` + `box-shadow:0 0 0 3px rgba(31,84,222,.12)`

**Fixed Footer:**
- 「戻る」(border付き) + 「次へ / 登録する」(blue primary)
- `box-shadow: 0 -4px 20px -8px rgba(15,37,82,.15)`

---

### 4. メール確認完了 (`メール確認完了.html`)
**Purpose:** 登録後のメール確認完了。confettiアニメ付き。

**Layout:** 全画面中央、最大幅 460px カード、上部にロゴ

**Design:**
- カード上部: 4pxの青グラデーションライン `linear-gradient(90deg,#1f54de,#6fa3ff)`
- 確認アイコン: 90px円、薄青背景 + メールチェックSVG
- confetti: 12個の8px×8px角丸ボックス、ブランドカラー各色、fall アニメ
- 3ステップ説明: 背景`#f8faff`、番号=26px青円

---

### 5. 申し込み状況 (`申し込み状況.html`)
**Purpose:** 出品中の申し込み一覧・入札状況確認。

**Layout:** 最大幅 760px、ヘッダー + タブ + カードリスト

**States:**
- 入札受付中 / 入札あり / 選択完了 / 成約済み
- 各状態でカードのボーダー色・バッジが変化

**Actions:**
- 「詳細を見る」→ `査定結果.html`
- 「交渉する」→ `chat.html`

---

### 6. 査定結果 (`査定結果.html`)
**Purpose:** 届いた入札の一覧と業者選択。

**3 States (デモ切替バーで確認可):**
1. **査定中:** スケルトンカード + カウントダウン + pulseアニメ
2. **入札あり:** TOP3業者カード、金額・評価・コメント、「決める」ボタン
3. **選択完了:** 決定済みカード + 次のステップリスト + チャット開始CTA

**bid-card:**
- TOP業者: `border-color:#1f54de` + `box-shadow:0 0 0 3px rgba(31,84,222,.1)`
- 金額エリア背景: `var(--line-soft)` / `border-radius:10px`
- 金額フォント: `clamp(22px,4vw,32px)` / Zen Kaku / 900

**確認モーダル:**
- `backdrop-filter:blur(5px)` / `background:rgba(15,37,82,.5)`

---

### 7. 業者詳細 (`業者詳細.html`)
**Purpose:** 業者プロフィール詳細・口コミ・入札情報。

**Components:**
- **評価バー:** 5段階分布、`background:#f0a030`
- **統計グリッド:** 3カラム、`background:var(--pale)`
- **入札ハイライト:** `linear-gradient(135deg,#e4edff,#d0e0ff)` / `box-shadow:0 8px 24px -12px rgba(31,84,222,.25)`
- **口コミ:** レビュアーアバター(36px円) + スター + タグ
- **Fixed Footer CTA:** 業者名 + 金額 + 「決める」「質問」ボタン

---

### 8. チャット (`chat.html`)
**Purpose:** ユーザー⇔業者間メッセージ。

---

### 9. 訪問日程調整 (`訪問日程調整.html`)
**Purpose:** 訪問日時の調整。

---

### 10. 取引完了・評価 (`取引完了・評価.html`)
**Purpose:** 取引完了後の評価投稿。

**Components:**
- **完了バナー:** `linear-gradient(135deg,#e4f7ed,#d0f0e0)` / flexカラム中央寄せ / SVGチェック
- **スター選択:** 5個の40pxボタン、初期色`var(--line)`→選択時`#f0a030`
- **評価タグ:** 複数選択チップ、選択時`background:var(--pale); color:var(--blue)`
- **公開トグル:** カスタムCheckbox→スライダー、ON=`var(--green)`

---

### 11. マイページ (`マイページ.html`)
**Purpose:** ユーザーの申し込み管理・プロフィール。

**Layout:** sticky header + サマリーカード4枚グリッド + タブ切替 + カードリスト

**サマリーカード:** クリック → `申し込み状況.html`
**通知ベル:** ヘッダー右、未読時赤9px丸バッジ → `通知・お知らせ一覧.html`

**Tabs:** すべて / 進行中 / 成約済み / プロフィール

---

### 12. 通知・お知らせ一覧 (`通知・お知らせ一覧.html`)
**Purpose:** 入札・メッセージ・システム通知の一覧。

**未読表示:** `border-left:4px solid` (blue/green/warn) + タイトル前に7px色付き円 (`::before`)
**フィルタータブ:** all / 入札 / メッセージ / システム
**既読処理:** 「すべて既読にする」ボタン

---

### 13. プロフィール編集 (`プロフィール編集.html`)
**Purpose:** ユーザーの基本情報・通知設定・パスワード変更。

**変更検知:** 任意のフィールド変更 → 保存バー「未保存の変更があります」表示
**保存バー:** Fixed bottom、保存後トースト表示 (fadeOut 2.5s)
**パスワード変更:** インラインエラー表示（alert不使用）

---

### 14. プロフィール画像 / 業者詳細 その他
- **退会・アカウント削除 (`退会・アカウント削除.html`):** 3チェック確認 + パスワード再入力、全確認後「削除」ボタン有効化
- **パスワードリセット (`パスワードリセット完了.html`):** 3ステップフロー（メール送信→リンク確認→新PW設定）
- **404 (`404.html`):** floating boxアニメ + よく使うページへのショートカット3件
- **会社概要 (`会社概要.html`):** ミッション / 数字実績 / 会社情報テーブル / チームカード
- **業者向けLP (`業者向け.html`):** 完全に別のLP。ページ内に登録フォーム付き (#register)

---

## User Flows

```
[トップ] 
  → [出品登録] → [出品完了] → [申し込み状況] → [査定結果] → [業者詳細]
                                                             → [チャット] → [訪問日程調整] → [取引完了・評価]
  → [ログイン] ↔ [新規登録] → [メール確認完了] → [出品登録]
  → [マイページ] → [通知・お知らせ一覧]
                 → [申し込み状況]
                 → [プロフィール編集] → [退会・アカウント削除]

[業者向け] → [業者ダッシュボード] → [業者チャット] / [業者プロフィール]
```

---

## Interactions & Behavior

### 共通
- **ホバー:** カード → `translateY(-2px)` + shadow強化 / ボタン → `translateY(-2px)`
- **トランジション:** `0.2–0.3s cubic-bezier(.22,.61,.36,1)`
- **スクロール演出:** `.rv` クラス → `opacity:0; translateY(22px)` → `.in` で解除（Intersection Observer）
- **ローディング:** ボタン内 `<span class="spinning">↻</span>` + 無効化

### フォーム
- **バリデーション:** submit時に全フィールドチェック、エラー時は `has-error` クラス + `field-error` div表示
- **パスワード表示切替:** 目アイコンボタン、`type=password/text` 切替

### モーダル
- **オーバーレイ:** `backdrop-filter:blur(4–5px)` / `background:rgba(15,37,82,.45–.5)`
- **閉じる:** オーバーレイクリック or キャンセルボタン

---

## Responsive Breakpoints
```
1140px: max-width (コンテナ)
 980px: 2カラム → 1カラム切替、ヘッダーナビ非表示
 860px: ハンバーガー表示、モバイル追従CTA表示
 720px: グリッド縮小
 560px: 小サイズフォント・パディング調整
 480px: モバイル最適化（area-grid 2col等）
 360px: 最小対応（ラベル省略等）
```

---

## Assets
- **ロゴ:** `img/logo-katazuke.png` (高さ 36–54px で使用)
- **カテゴリ画像:** `img/cat-*.png` (cat-kaden / cat-brand / cat-camera / cat-beauty 等)
- **入札チャート等:** `img/bid-*.png`
- **Googleフォント:** Zen Kaku Gothic New (500/700/900) + Noto Sans JP (400/500/600/700)
  - CDN: `https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;600;700&family=Zen+Kaku+Gothic+New:wght@500;700;900&display=swap`

---

## Files in This Package

| ファイル | 説明 |
|---|---|
| `カタヅケ.html` | トップLP |
| `ログイン.html` | ログイン |
| `新規登録.html` | 3ステップ新規登録 |
| `メール確認完了.html` | メール確認完了 |
| `出品登録.html` | 出品フロー |
| `出品完了.html` | 出品完了 |
| `申し込み状況.html` | 申し込み一覧 |
| `査定結果.html` | 入札結果・業者選択 |
| `業者詳細.html` | 業者プロフィール |
| `chat.html` | チャット |
| `訪問日程調整.html` | 日程調整 |
| `取引完了・評価.html` | 取引完了・評価 |
| `マイページ.html` | マイページ |
| `通知・お知らせ一覧.html` | 通知一覧 |
| `プロフィール編集.html` | プロフィール編集 |
| `退会・アカウント削除.html` | 退会フロー |
| `パスワードリセット完了.html` | PW リセット |
| `業者向け.html` | 業者向けLP |
| `業者ダッシュボード.html` | 業者ダッシュボード |
| `業者チャット.html` | 業者チャット |
| `業者プロフィール.html` | 業者プロフィール |
| `会社概要.html` | 会社概要 |
| `よくある質問.html` | FAQ |
| `撮影ガイド.html` | 撮影ガイド |
| `成約事例.html` | 成約事例 |
| `contact.html` | お問い合わせ |
| `利用規約.html` | 利用規約 |
| `プライバシーポリシー.html` | PP |
| `特定商取引法.html` | 特定商取引法 |
| `404.html` | 404エラー |
| `katazuke-main.css` | 共通スタイル（デザイントークン含む） |
| `ページ導線マップ.html` | 全画面の導線図 |
