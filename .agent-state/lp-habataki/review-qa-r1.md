# /lp QA独立レビュー r1（B節: 品質・a11y・レスポンシブ）

対象: web/src/app/lp/page.tsx, lp.css, _components/LpChrome.tsx, _components/LpSlider.tsx,
      web/src/components/kdz/SiteChrome.tsx（差分1行）
検証方法: 静的読解 + `npx tsc --noEmit` + `npx eslint` + grep + Node製WebPヘッダーパーサでの画像実寸照合。
dev server / next build / ブラウザは方針により未実行。

## ツール結果
- `npx tsc --noEmit` : 0 errors (exit 0)
- `npx eslint src/app/lp src/components/kdz/SiteChrome.tsx` : 0 errors / 0 warnings (exit 0)

## 総合判定: 不合格（Highが2件残っているため）

---

## Critical: 0件

## High: 2件

### H1. MENUオーバーレイに focus trap / inert がなく、開いている間に背後要素へTabで到達できる
- ファイル: `web/src/app/lp/_components/LpChrome.tsx`（`lp-menu` nav 全体、`lp-float-cta`, `lp-pagetop`、および`page.tsx`側の後続セクション全て）
- 期待: 全画面オーバーレイ（背面スクロールロックを伴うモーダル相当のUI）は、開いている間に背後コンテンツへフォーカスが渡らないこと（`inert`/`aria-hidden`付与、またはnav内でのTab循環）。
- 実測: 実装されているのは (a) Esc で閉じる, (b) 閉じたら`buttonRef`へフォーカス復帰, (c) 開いた直後に先頭リンクへフォーカス移動、の3点のみ。`open`時に他要素へ`inert`/`aria-hidden`を付与するコードも、`panelRef`内でTab/Shift+Tabを捕捉するkeydownハンドラも存在しない。
  DOM順は `lp-header → lp-float-cta（z-index:65） → nav#lp-sitemap（z-index:68） → lp-pagetop（z-index:60） → 本文各section`。オーバーレイのz-indexは68、`lp-header`だけ70で最前面に残るが、`lp-float-cta`と`lp-pagetop`はz-indexがオーバーレイより低いため**視覚的にオーバーレイの背後に隠れる**。にもかかわらずどちらも`<a href>`のままDOM上に存在し、`visibility`/`aria-hidden`/`inert`のいずれも設定されないため、開いている間もTabキーで到達しフォーカスが移る。さらにnav内の最後のリンクからTabを続けると、そのままDOM順で後続の本文セクション（KVスライダーのドット/一時停止ボタン、各所の`Link`等）にまでフォーカスが漏れる。body側は`overflow:hidden`でスクロールできないため、フォーカスが当たった要素は画面外にも見えず、フォーカスリングが完全に不可視になる。
- 再現条件: `/lp`でMENUボタンをクリック→開いた状態でTabキーを連打するだけ（ブラウザ実機での確認が必要、今回は未実行のためコード読解による論理的な指摘）。
- 修正案: `open`時に`document.getElementById("main")`配下でnav以外の兄弟要素（または`lp-float-cta`/`lp-pagetop`/各`<section>`の親）に`inert`属性を付与する。もしくは`panelRef`内でTab/Shift+Tabをラップするfocus trapを実装する（`components/kdz/interactions.tsx`に前例なし・新規実装が必要）。

### H2. `<footer>` が `<main>` の内側にあるため contentinfo ランドマークにならない
- ファイル: `web/src/app/lp/page.tsx:832,858`（`<footer className="lp-footer">...</footer>` が `<main id="main" className="lp-page">...</main>` の閉じタグより前にある）
- 期待: ページ末尾の`<footer>`はcontentinfoランドマークとして支援技術に認識される。
- 実測: HTML-ARIA仕様では`footer`要素は`article/aside/main/nav/section`の子孫である場合、暗黙ロールが`contentinfo`ではなく`generic`になる。本実装は`footer`が`main`の子であるため、この条件に該当し、contentinfoランドマークが失われる。
- 修正案: `<footer>...</footer>`を`</main>`の外側（`LpChrome`と同様に`<main>`の兄弟）に移動する。

## Medium: 2件

### M1. `.lp-header` が `<div>` のため banner ランドマークが存在しない
- ファイル: `LpChrome.tsx:96`
- 期待: ページ先頭のグローバルヘッダー領域がbannerランドマークとして識別できる。
- 実測: `<div className="lp-header">`（`<header>`要素を使っていない）。
- 修正案: `<header className="lp-header">`に変更（CSSは`.lp-page .lp-header`セレクタのまま流用可）。

### M2. LpSliderの非アクティブスライドに`aria-hidden`が付与されていない
- ファイル: `LpSlider.tsx:69-82`
- 期待: 同じ実装パターンの手本である`components/kdz/interactions.tsx`の`HeroCarousel`（341-351行）は非アクティブ`<img>`に`aria-hidden={i===current?undefined:true}`を付与している。
- 実測: LpSliderの`<img>`にはそれがなく、6枚全てが常にアクセシビリティツリー/DOM走査上に等しく存在する。`alt=""`のため実害は小さいが、手本との一貫性を欠き、将来意味のあるaltへ変更された場合に問題化する。
- 修正案: `HeroCarousel`と同じ`aria-hidden`分岐を追加する。

## Low: 3件

### L1. 画像のwidth/height属性が実ファイル解像度とわずかに不一致
- 対象: `top-founder-desk.webp`（コード上1600×1067、実ファイル1536×1024）、`top-handover.webp`（同様に1600×1067 vs 1536×1024、3箇所で使用）
- アスペクト比差は約0.03%（1600/1067≈1.4995 vs 1536/1024=1.5）でCLSへの実害はほぼ無いが、値の出典が実ファイルと食い違っている。
- 修正案: width/height属性をファイル実測値に合わせる（必須ではないが資産差し替え時の事故防止になる）。

### L2. `metadata.alternates.canonical` が `"/"` を指している
- ファイル: `page.tsx:19`
- 本採用時に`robots.index=false`を外す際、canonicalの修正を同時に行わないと`/lp`が恒久的に非索引扱いになるリスクがある。
- 修正案: 本採用手順のTODOに「canonicalを`/lp`自身へ変更」も明記する。

### L3. `<nav id="lp-sitemap">` が閉じている間も常にDOMに存在する
- `visibility:hidden`のみで開閉しており、閉状態でもランドマーク一覧に出続ける可能性がある（一般的なオフキャンバスメニューの許容範囲内で実害は小さい）。

---

## 確認できなかった項目（dev server / ブラウザ不使用の制約による）
- 375/390/768/1280/1440幅での実機`scrollWidth<=clientWidth`計測。
- MENUオーバーレイの実際のTabキー挙動・フォーカスリング可視性（H1はコード読解による論理的推定）。
- `NVDA`/`VoiceOver`等スクリーンリーダーでの実読み上げ確認。
- `.lp-case__more`（詳しく見るボタン、絶対配置top:48px）と`.lp-case__chip`（打消し表示）が実際に視覚的に重ならないか（コード上のコメントでは意図的に高さ調整済みと記載）。
- `console error`0件・画像404 0件の実測（Networkタブ/`img.naturalWidth`走査は未実施。ファイルシステム照合では全参照画像の実在を確認済み）。
- POINT/DAILYのCSS Grid明示配置（`nth-child`によるgrid-column/row指定）が実際に意図通りの段違いレイアウトになるかの視覚確認。
