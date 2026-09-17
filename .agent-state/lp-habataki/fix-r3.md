# /lp 修正指示 r3（リーダー裁定・2026-09-17）— 浮遊CTAの衝突を根絶して合格へ

入力: `review-fidelity-r3.md`（High 1・B4 未達）＋ `review-qa-legal-r3.md`（High 4・Medium 4）。編集範囲は r1 と同じ。

## A. High（必須・全件）
1. **KV のスライダー操作列と縦タブの衝突**（qa H-1）: `@media(min-width:860px){.lp-page .lp-slider__ctrl{right:84px}}`。加えて `.lp-kv{position:relative;z-index:1}` は付けない（CTA は常に前面でよい。操作列を CTA の横にずらすだけ）。
2. **860〜1243px で縦タブが本文に食い込む**（qa H-2）: `@media(min-width:860px) and (max-width:1243px){.lp-page .lp-container{padding-inline-end:max(var(--lp-pad),72px)}}`（`--lp-pad` が無ければ現在の clamp 値をそのまま max の第1引数に）。
3. **veil の停止位置を px 基準に**（qa H-3）: `.lp-kv__veil` の背景を `linear-gradient(180deg, rgba(244,247,252,.96) 0 clamp(320px,38%,440px), rgba(244,247,252,0) clamp(560px,70%,680px))` にし、**KV のコピー塊（h1＋英字＋sub）の下端が常に第1停止位置より 40px 以上上に来る**ことを CSS で担保する（コピー塊は `padding-top` 固定・`max-height` を持つ／sub の直後に veil 内であることを前提としたレイアウトにする）。SP は `clamp(300px,45%,420px)` / `clamp(480px,75%,600px)`。
4. **アンカーで閉じた直後の focus() が inert で失敗**（qa H-4）: `closeToAnchor` 内の `focus()` を `requestAnimationFrame(() => requestAnimationFrame(() => target.focus()))` に（inert 除去の effect が走った後に実行）。
5. **浮遊CTAが footer の pagetop を覆う**（fidelity H1・3 度目の再発）: `LpChrome` に IntersectionObserver を 1 つ追加し、**`.lp-footer` がビューポートに入っている間は浮遊CTA（PC 縦タブ・SP 下部バー）を `hidden`（`display:none` ではなく `visibility:hidden;pointer-events:none` ＋ `inert`）**にする。MENU 開時の非表示と同じ状態変数を使う。footer が見えなくなったら戻す。reduced-motion に関係なく動作。

## B. 高さ・その他（必須）
1. FOOTER 高さ（fidelity B4 未達・688px）: `.lp-footer` の `padding-block` を明示値で **`clamp(200px,20vw,260px) 150px`** にし、PC 1280 で 730〜800px になるよう調整（実測はリーダー）。
2. `.btn.btn-line{min-height:60px}` と縦タブ（220px 指定）の同特異度順序依存（qa M）: 縦タブ側を `.lp-page .lp-float-cta .btn.btn-line` の特異度で書き、高さは **`min-height:220px;max-height:240px`** に（現状 358px は長すぎる＝fidelity M）。
3. SP の下部バーの逃げ代（fidelity M）: `.lp-footer` だけでなく **`main` の最後の区画（`#biz`）にも `padding-bottom:calc(56px + env(safe-area-inset-bottom))`** を足す（footer が短くても本文末尾が隠れない）。
4. 循環帯の高さ（fidelity M）: PC 1064px → **600〜700px**（`padding-block` を詰める・タイルは 110px のまま）。SP は据置き。
5. POINT 色面の下 180px 無地（fidelity M）: 色面高さを `min(40vw,460px)` に。h2 は色面内のまま。
6. `robots.ts` の Disallow を**元に戻す**（qa M: Disallow と noindex の併用は noindex が読まれない）。`git checkout -- web/src/app/robots.ts` 相当（差分ゼロに）。metadata の `robots:{index:false,follow:false}` は維持。

## C. 据置き（対応不要・理由）
- KV 画像の srcset 欠落: 1536px の単一素材しか存在せず、新規画像生成は行わない（金銭・素材方針）。
- 「β期間中は手数料0円」と「成約時8%（税別）」の同一視野: トップの `.biz-banner-tags` と同じ並びであり、出典どおり。
- `overflow-clip-margin` の Safari 対応: 非対応でも `overflow:clip` で pagetop の 11px はみ出しが切れるだけ（機能影響なし）。

## 完了条件
`npx tsc --noEmit` 0／`npx eslint src/app/lp src/components/kdz/SiteChrome.tsx src/app/robots.ts` 0/0／`git diff --stat -- web/src/app/robots.ts` が空。戻り値 20 行以内（対応番号一覧・未対応と理由・変更ファイル）。
