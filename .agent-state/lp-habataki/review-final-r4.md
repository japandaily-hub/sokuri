# /lp 最終検査 r4（独立検査官・実機計測）— 2026-09-18

対象: `http://localhost:3100/lp`（起動済み dev）／判定対象: `fix-r3.md` A1〜A5・B1〜B6
計測方法: Playwright MCP。矩形交差は `getBoundingClientRect` の px²、KV コントラストは **文字要素を `visibility:hidden` にした状態のスクリーンショットを canvas でデコードして実ピクセルをサンプリング**（veil・写真・装飾を合成した実効背景）。

## 総合判定

**不合格（High 1 件）。** A1〜A5 の 5 件と B1・B4・B6 は実機で直っている。**B2 の高さ指定が SP に漏れ、下部バーが 229px（vh の 27%）という新規 High を作った。**

---

## 1. 判定表

| # | 指示 | 判定 | 実測根拠 |
|---|---|---|---|
| A1 | スライダー操作列と縦タブの衝突解消 | **PASS** | 1280/1024/1366 とも `.lp-slider__ctrl`(+子) × `.lp-float-cta`(+子) = **0 px²**。ドット列 x≈1171、CTA 左端 1214（1280 時）で 43px 離隔 |
| A2 | 860〜1243px で本文に食い込まない | **PASS**（Low 付記） | 860/880/1000/1100 で `.lp-container` の `padding-inline-end = 72px`、全スクロール位置で重なり **0 px²**。1243/1244 のみ 13/7 px² の接触（下記 NEW-L1） |
| A3 | veil を px 基準・コピー塊の逃げ 40px 以上 | **PASS** | 実効 gradient = `.96 → 0px〜clamp(360,40%,460)`、`0 → clamp(600,72%,700)`。コピー塊下端 297px、第1停止位置 360px → **余裕 63px**。コントラストは §2 |
| A4 | アンカー閉鎖後の focus が inert で失敗しない | **PASS**（Low 付記） | 「料金」クリック後 `document.activeElement = SECTION#fee[tabindex="-1"]`、`#fee.contains(activeElement)=true`、scrollY=14337・feeTop=0。見出し h2 ではなく区画そのもの（NEW-L2） |
| A5 | footer 可視中は浮遊CTA を hidden＋inert | **PASS** | 最下部: 1280×800 / 1366×768 / 1024×768 / 390×844 すべて `visibility:hidden` かつ `inert=true`、`.lp-pagetop` は visible。reduced-motion 下でも同挙動 |
| B1 | FOOTER を 730〜800px に | **PASS** | 1280 で **799px**（参照 838、-4.7%）。`padding-block: 200px 104px` |
| B2 | 縦タブ `min-height:220px;max-height:240px` | **PC PASS / SP FAIL** | PC: `.btn.btn-line.lp-float-cta__btn` = 220px（min 220/max 240）✔。SP 390: 同セレクタが **220px×273px** に膨張し、バー全体 **229px**（NEW-H1） |
| B3 | `#biz` に下部バーの逃げ代 | **一部** | SP で `#biz{padding-bottom:116px}` を確認。ただし実バー高 229px に対し不足（NEW-M1） |
| B4 | 循環帯を 600〜700px | **PASS** | `.lp-cycle` = **662px**（1280） |
| B5 | POINT 色面の下の無地を解消 | **FAIL(Medium)** | `.lp-point__plate` = 460px（= min(40vw,460px) 指示どおり）、h2/バッジは色面内 ✔。しかし色面下端 500px → 次の内容 `.lp-point__main` 758px で **無地 258px**（指摘時 180px より拡大） |
| B6 | `robots.ts` を差分ゼロへ | **PASS** | `git diff --stat -- web/src/app/robots.ts` 空・`git status --porcelain` 空 |

---

## 2. KV コントラスト実測（1280幅・6スライド×4ビューポート高 = 24 条件）

各条件で文字矩形内の**最暗背景ピクセル**を採り最悪値で算出（平均値ではない）。

| 要素 | 文字色 | 要求 | 最悪比（全24条件） | 最良比 | 判定 |
|---|---|---|---|---|---|
| `.lp-kv__sub` | rgb(69,78,89) | 4.5 | **7.19** (vh768/1080・ihin) | 7.53 | PASS |
| `.lp-kv__en` | rgb(86,99,110) | 4.5 | **5.25** (vh640/768/800・closet/ihin/kitchen) | 5.64 | PASS |
| `.lp-kv h1` | rgb(32,36,46) | 3.0 | **13.22** | 14.20 | PASS |

- 最暗写真は `ex-lot-ihin.webp`（vh 640/768/800/1080 いずれも最小群）。最暗背景でも RGB は 234,237,242 程度までしか沈まず、veil が効いている。
- vh 640/768/800/1080 の間で最悪比の変動は 0.3 以内。**ビューポート高依存の破綻なし。**

## 3. reduced-motion 実測（`emulateMedia({reducedMotion:'reduce'})` → reload）

| 項目 | 期待 | 実測 | 判定 |
|---|---|---|---|
| `document.getAnimations().length`（ロード直後） | 0 | **0** | PASS |
| 同（7.5 秒後） | 0 | **0** | PASS |
| スライダー `aria-selected`（7.5 秒後） | 変化なし | `[true,false,false,false,false,false]` で不変（6 ドット） | PASS |
| `.rv/.rv--up` の可視性 | 全 opacity:1 | 56 要素中 **opacity<1 は 0 件** | PASS |
| footer 到達時の CTA 退避 | reduced-motion でも動作 | `visibility:hidden` / `inert=true` | PASS |

## 4. 区画高さ実測（PC 1280）

| 区画 | 参照 | 実測 | 差 |
|---|---|---|---|
| KV | 900 | 800 | -11.1%（KV は 100vh。vh800 計測に起因） |
| MESSAGE | 976 | 950 | -2.7% |
| ABOUT | 2829 | 2506 | -11.4% |
| POINT 撮 | 2922 | 2504 | -14.3% |
| POINT 選 | 2520 | 2138 | -15.2% |
| POINT 安 | 1566 | 1656 | +5.7% |
| 循環帯 | 478〜700 | **662** | 範囲内（B4 目標 600〜700 も達成） |
| DAILY | 2926 | 3122 | +6.7% |
| FEE | 2635 | 2316 | -12.1% |
| CASES | 3775 | 3280 | -13.1% |
| BIZ | 2447 | 2112 | -13.7% |
| FOOTER | 838 | 799 | -4.7%（B1 目標 730〜800 内） |

## 5. 回帰チェック

| 項目 | 結果 |
|---|---|
| `scrollWidth <= clientWidth`（375/390/768/1280/1440） | 全て **一致**（365/380/758/1270/1430）。横スクロールなし |
| console error | **0 件**（warning 24 は Next の dev 警告のみ） |
| 画像 404 / 失敗リクエスト | **0 件**。`naturalWidth===0` の img も 0 件 |
| 角丸非 0 の要素 | **0 件**（ドット以外に無し。ドットは円形で許容） |
| `html.js-rv` | 付与あり。opacity:0 の 54 要素は全て `.rv` 系（スクロール後は 0 件残存） |

## 6. 新規指摘

### NEW-H1 [High] SP の下部CTAバーが 229px（画面の 27%）／本文に最大 78,661px² 被さる
- セレクタ: `.lp-page .lp-float-cta .btn.btn-line`（`min-height:220px;max-height:240px`）
- 期待: SP（<860px）では 56〜64px の帯。B3 が `padding-bottom: calc(56px + safe-area)` を置いていることからも、実装者の想定は 56px 帯。
- 実測（390×844）: `.lp-float-cta` = top 615 / height **229** / `background:#fff`、子の LINE ボタンが **220×273px の緑面**。scrollY 11020 で `.lp-daily__item`（「01 撮る／家じゅうの不用品を1点ずつ撮影。」）と **78,661px²** 交差し、キャプション（top 799〜826）が完全に隠れる。`elementFromPoint` はバー内の `SPAN.btn-line__label` を返す＝実際に被さっている。
- 証跡: `shots-impl-r4/sp390-bar-over-daily.png`, `sp390-kv.png`
- 修正案: B2 の高さ指定を `@media (min-width:860px){ .lp-page .lp-float-cta .btn.btn-line{min-height:220px;max-height:240px} }` に閉じ、SP 側は `min-height:56px;max-height:64px` を明示する。

### NEW-M1 [Medium] B3 の逃げ代がバー実寸と整合しない
- `#biz{padding-bottom:116px}`（SP）。実バー 229px なので 113px 不足。NEW-H1 を直せば解消するが、直後に再実測が必要。

### NEW-M2 [Medium] POINT 色面の下の無地が 258px（指摘時 180px より拡大）
- 色面 `.lp-point__plate` 460px は指示どおりだが、色面下端 500px に対し次の内容 `.lp-point__main` が 758px から。色面を詰めた分が下の余白に転嫁されている。
- 修正案: `.lp-point__main` 側の `margin-top`/`padding-top` を色面縮小分だけ詰める。

### NEW-L1 [Low] 1243〜1270px で縦タブと本文列の離隔がゼロ
- A2 のメディアクエリが 1242px で切れ、1243px 時点で `padding-inline-end` が 72px→55.95px に戻る。本文右端 1177px＝CTA 左端 1177px で密着し、サブピクセル丸めで 13px²/7px² の接触が出る。
- 修正案: 上限を `max-width:1279.98px` まで伸ばすか、`padding-inline-end` の clamp 下限を 72px に。

### NEW-L2 [Low] アンカー後のフォーカス先が見出しでなく区画全体
- `SECTION#fee[tabindex="-1"]` にフォーカス。アクセシブル名がないため、スクリーンリーダーが区画全文を読み上げるおそれ。`h2` 側に `tabindex="-1"` を移すか、section に `aria-labelledby` を付与。

### NEW-L3 [Low] MENU を開いてもフォーカスがメニュー内へ移動しない
- 開いた直後の `activeElement` は `BUTTON.lp-header__menu` のまま（`aria-expanded=true`）。続く Tab はメニュー内リンクへ入るため実害は小。Esc では MENU ボタンへ復帰（`isMenuBtn=true`, `aria-expanded=false`）＝仕様どおり。

---

## 7. 未解決リスク（「問題ゼロ」ではない）

1. **CTA の退避は IntersectionObserver（JS）に全依存。** JS 無効・observer 失敗時、SP では下部バーが footer の `© 2026 カタヅケ` 行と **8,360px²** 幾何交差する（現状は visibility:hidden なので不可視）。CSS だけのフォールバック（footer 手前に `scroll-margin` / `position:sticky` 化など）は無い。
2. **区画高さが参照比 -11〜-15%（ABOUT/POINT撮/POINT選/FEE/CASES/BIZ）に偏っている。** 個別には許容かもしれないが、系統的な縮みで参照 LP の「余白の重さ」は再現していない。忠実度としての可否はリーダー裁定が必要。
3. **veil の停止位置が指示値と不一致。** 指示 `clamp(320,38%,440)/clamp(560,70%,680)` に対し実装は `clamp(360,40%,460)/clamp(600,72%,700)`。結果は合格（より厚い veil）だが、指示どおりではないので次回差分で意図せず戻される危険。
4. **SP は 390 幅のみ実機計測。** 375 幅は scrollWidth のみ確認。バー高さ問題は同様に出ると推定 [推測]。
5. **reduced-motion は Playwright の `emulateMedia` による検証。** OS 設定での実機（Windows「アニメーションを表示する」オフ）は未検証。
6. **スライダーの自動送りは「reduced-motion で止まる」ことは確認したが、通常時に 7 秒で送られるかは今回未計測**（A 項目外のため）。自動送り自体が壊れていないかは別途要確認。
7. **dev サーバ実測であり本番ビルド未検証。** 過去に `@import layer()` が本番ビルドでトークンを落とした事例があるため、`next build` での再確認が必要。

## 8. スクリーンショット

`C:\Users\ko13h\Claude\Projects\ソクウリ\.agent-state\lp-habataki\shots-impl-r4\`
- `pc1280-kv.png` — KV（縦タブとドット列の離隔／veil 上のコピー）
- `pc1280-point-satsu.png` — POINT 撮（色面 460px・下の無地 258px）
- `pc1280-footer-cta-hidden.png` — 最下部（CTA hidden＋inert、pagetop 可視）
- `sp390-kv.png` — SP KV（下部バー 229px が既に見える）
- `sp390-bar-over-daily.png` — **NEW-H1 の証跡**（緑の巨大ブロックが DAILY 01 のキャプションを覆う）
- `sp390-footer-cta-hidden.png` — SP 最下部（CTA hidden、© 行と pagetop 露出）
