# LP 3Dアイコン配線ログ（2026-09-03）

対象: `web/src/app/page.tsx`, `web/src/app/katazuke.css`
方式: `/img/icon3d/<name>.webp`（512×512）を素の `<img>` で配線（alt=""=装飾, eslint-disable no-img-element）。

- page.tsx:7-19 `CATEGORIES`に`img`キー追加、`icon`キー削除（cat-imgでのみ使用の死コードだったため）
- page.tsx:334-341 `.cat-img` → `<img src=.../cat-*.webp>`（12件）
- page.tsx:69-76 `.hero-trust .tb` → `check.webp`（4件）
- page.tsx:77-87 `.hw-ic` → `how-camera/trend/crown/truck.webp`（4件、font-size指定は削除）
- page.tsx:104-111 `.assure-item .ai` → `assure-shield/lock/phone/pin.webp`（4件）
- page.tsx:190-206 `.bc-ic` → `bundle-up/bag/camera.webp`（3件）
- page.tsx:346-347 `.cats-note .cn-ic` → `bundle-bag.webp`流用（1件）
- page.tsx:245-249 `.mlist .ck` → `check.webp`（4件）
- page.tsx:289-310 `trust-c .tc-ic`要素を削除（3Dイラスト`tc-illus`と重複のため）、`.tc-body h3`にmargin-top:2pxで余白調整
- katazuke.css: `.cat-img img`padding 6px→0、`.ai`/`.bc-ic`背景を`var(--pale)`化（`.key`の青ベタ地含む）、`.tb`/`.ck`は枠なし透明化＋`img{object-fit:cover}`、`.hw-ic`をwidth/height 22px+object-fit:coverに置換、`.tc-ic`関連ルール削除

他ページCSS（katazuke-pages.css/business.css等）に同名クラス重複なし＝影響範囲はLPのみ。
