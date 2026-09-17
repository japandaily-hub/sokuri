# /lp QA・法務レビュー r3（最終判定・2026-09-17）

検査対象: web/src/app/lp/page.tsx, lp.css, _components/LpChrome.tsx, _components/LpSlider.tsx,
web/src/app/robots.ts, web/src/components/kdz/SiteChrome.tsx
方法: 静的検査のみ（dev/build/ブラウザ不使用）。数値は CSS からの手計算（sRGB 相対輝度・WCAG 2.x 式）。

## 0. 総合判定

**不合格（High 4 件・Medium 4 件）。**
tsc --noEmit = 0 / eslint src/app/lp src/components/kdz/SiteChrome.tsx src/app/robots.ts = 0/0。
C 節（r2 QA 指摘）は C1〜C4 実装済み・C5 は 5 項目中 4 項目実装済み。
A2（浮遊CTA）と A3（KV フルブリード）は構造は入ったが目的（本文を覆わない／可読性）を満たしていない。
とくに A2 と A3 は同じ画面右端を奪い合っており、縦タブがスライダーの一時停止ボタンを覆う（High-1）。

## 1. fix-r2 の項目別判定

| 番号 | 判定 | 根拠 |
|---|---|---|
| A2 PC縦タブ／SP下部バー | 直っていない（別の問題） | 実装はある（lp.css:303-361 / 1547-1602）が High-1・High-2 |
| A3 KV フルブリード | 直っていない（(c) 未達） | 構造・(a)(b) は達成（lp.css:511-582 / LpSlider.tsx:74-87）。veil 可読性が High-3 |
| C1 lp-band__head の lp-en | 直った | lp.css:732-734 rgba(255,255,255,.92) = #1447e0 上 6.15:1（旧 3.32:1） |
| C2 lp-about__body の lp-en | 直った | lp.css:767-769 .82 = 5.20:1 |
| C3 ドット列の基準コメント訂正 | 直った | lp.css:583-584 / LpSlider.tsx:67-68。lp-kv が全幅なので right:24px＝ビューポート右端 24px で記述一致 |
| C4 lp-footer の overflow | 直った | lp.css:1467-1470 overflow:clip + overflow-clip-margin:16px（SP pagetop の -11px を包含） |
| C5-1 role=tab の aria-controls | 直った | LpSlider.tsx:75,106（img の id と一致） |
| C5-2 ドット上ホバーで自動送り停止 | 直った | LpSlider.tsx:92-98 |
| C5-3 アンカーで閉じた時のフォーカス移動 | 直っていない（実行時に無効） | High-4 |
| C5-4 CASES 見出し重複の解消 | 直った | page.tsx:802-806（本文側は p.lp-cases__catch のみ） |
| C5-5 ベータ注記の重複解消 | 直った | page.tsx:903-909（リードは出典 3 文のうち前 2 文・注記は lp-biz__note 1 箇所） |
| C6 据置き 3 件 | 確認済み | ロゴ inert（LpChrome.tsx:143 + lp.css:315-318）／robots 前方一致（src/app 配下に lp 以外の lp* ルート無し）／region 名の和文化（page.tsx:509） |

直った: 8 項目（C1, C2, C3, C4, C5-1, C5-2, C5-4, C5-5）／直っていない: 3（A2, A3, C5-3）

---

## 2. High

### High-1【新規・回帰】PC の縦タブが KV スライダーのドット列と一時停止ボタンを完全に覆う

- 該当: lp.css:303-313（.lp-float-cta = position:fixed; right:0; width:56px; top:160px; z-index:65）
  × lp.css:585-595（.lp-slider__ctrl = position:absolute; right:24px; top:50%; z-index:4）
- 問題: ctrl の実寸は幅 30px（toggle が最大）・高さ 6×10px + 5×11px + gap14 + 30 = 159px で、
  ビューポート右端から x=[24px,54px]。縦タブは x=[0,56px] を占め、水平方向で完全に内包する。
  垂直方向は KV 高 H に対し ctrl=[H/2-79.5, H/2+79.5]、縦タブ=[160, 約517]（本体 220px + 代替導線 約137px）。
  - H=640（1366×768 相当）→ ctrl [240,400] は縦タブの内側に 100% 入る
  - H=900 → 重なり 146.5px / 159px（92%）
  .lp-kv は position:relative だが z-index 未指定＝スタッキングコンテキストを作らないため、
  ctrl（z:4）と固定CTA（z:65）は同じルートスタッキングコンテキストで比較され、CTA が上に描かれる。
- 影響: WCAG 2.2.2（Pause, Stop, Hide）の一時停止機構がクリック不能・不可視。SC 2.4.11 にも抵触。
- 再現条件: 幅 860px 以上の任意ビューポートで /lp を開き、スクロール位置 0。ドットや一時停止を押すと縦タブが反応する。
- 修正案: @media (min-width:860px) で .lp-page .lp-slider__ctrl の right を 80px にする（縦タブ 56px + 余白 24px）。
  もしくは ctrl を KV 下端（top:auto; bottom:calc(var(--lp-wave-h) + 24px)）へ逃がす。

### High-2【A2 未達】PC 縦タブが 860〜1243px 幅で本文に重なる

- 該当: lp.css:311-313 のコメント「版面の右余白は 1280 で 58px。56px なら本文の外側に確実に収まる」
- 問題: 右余白は --lp-pad = clamp(20px, 4.5vw, 58px)（lp.css:19）で .lp-container は max-width:1300px。
  ビューポート幅 vw < 1300 では右余白 = 4.5vw。4.5vw >= 56px となるのは vw >= 1244px なので、
  860px <= vw < 1244px では本文カラムに (56 - 0.045*vw) px 食い込む。
  vw=860 → 17.3px、vw=1000 → 11px、vw=1200 → 2px。食い込む縦範囲は y=[160,517] の 357px。
  ABOUT／POINT／CASES の右カラム行末が固定要素で欠ける。
  A2 の「1280px では本文と重ならない」は 1280 だけを見た検証で、iPad 横・13 インチノートの実効幅を外している。
- 修正案: @media (min-width:860px) で .lp-page .lp-container の padding-inline-end を max(var(--lp-pad), 72px) にして帯域を予約する。

### High-3【A3 (c) 未達】veil の停止位置が % なので、ビューポートが低いとサブコピーが写真に素で載る

- 該当: lp.css:519-525（PC veil）・lp.css:1640-1642（SP veil）・lp.css:513（min-height: clamp(640px,100svh,900px)）
- 問題: veil は rgba(244,247,252,.96) 0 38% から 0 70% へと KV 高 H の割合で定義されるのに、
  キャッチ群の位置は px 固定（padding-top clamp(104,8.6vw,140) + h1 2行 167px + en 33.6px + sub 42.5px）。
  実効 y（幅 1366 のとき）: h1 117→285 / .lp-kv__en 301→318 / .lp-kv__sub 332→361。
  - H=900（1920×1080 等）: sub 下端 367px の veil 不透明度 0.877 → #454e59 対 暗い写真で 5.94:1（可）
  - H=640（1366×768 や 1440×800 のブラウザ実高）: 0.38H=243px、0.70H=448px
    - .lp-kv__en（11px, --body-soft #56636e）不透明度 約0.61 → 暗部の写真で 2.07:1（AA 4.5:1 に大幅不足）
    - .lp-kv__sub（15px, --body #454e59）不透明度 約0.41 → 1.44:1（中間調 #808080 の写真でも 3.90:1 で不足）
    - h1（54px＝大きな文字）は 8.2:1、.hl（--primary）で 3.70:1 → 3:1 は満たす（合格）
  一般化すると sub が 4.5:1 を保つには H が約 826px 以上必要で、1080p 以上の全画面表示でしか成立しない。
- 再現条件: ブラウザ実表示高 800px 未満（＝一般的なノート PC）で /lp を開き、暗い写真のスライドが出た瞬間。
  写真は 6 枚ローテーションするので「読める枚と読めない枚が混在する」形で顕在化する。
- 修正案: veil の停止位置を px 基準にする。例:
  linear-gradient(180deg, rgba(244,247,252,.96) 0 clamp(300px,38%,430px), rgba(244,247,252,0) clamp(520px,70%,720px))
  あるいは .lp-kv__catch 自体に同色の面を敷き、写真の明度に依存しない可読性を作る。

### High-4【C5-3 未達】メニュー内アンカーのフォーカス移動が inert 解除前に走るため無効

- 該当: LpChrome.tsx:62-69（closeToAnchor）× LpChrome.tsx:84-89（inert 付与の effect）
- 問題: closeToAnchor は setOpen(false) の直後（同じイベントハンドラ内・同期）に target.focus() を呼ぶ。
  inert を外すのは useEffect のクリーンアップで、これは再レンダリングのコミット後＝ハンドラから戻った後に走る。
  focus() の時点で #main にはまだ inert が付いており、inert 部分木の要素は仕様上フォーカス不能なので
  focus() は無言で失敗し、フォーカスは body に落ちる。
  対象（#top, #about, #point, #daily, #fee, #cases, #biz）は全て #main 配下。
- 再現条件: キーボードで MENU を開き「カタヅケについて」等を Enter → その後 Tab を押すとページ先頭から再開する。
- 修正案: requestAnimationFrame の中で getElementById → setAttribute(tabindex,-1) → focus(preventScroll) を行い、
  inert 解除（effect クリーンアップ）より後のフレームに遅らせる。

---

## 3. Medium

- M-1 KV フルブリード化に伴う画像品質・転送量（LpSlider.tsx:74-87）: 1536×1024 を object-fit:cover で全画面に敷く。
  1440×900 の 1x でも拡大され、DPR2 では約 2 倍の拡大ボケ。srcset/sizes も next/image も無い
  （額縁時代は表示 700px 程度だったので顕在化していなかった）。最低限 1 枚目だけでも 2x 素材 + srcset を推奨。
- M-2 ベータ手数料 0 円とカード「成約時8%（税別）のみ」が同一視野で矛盾して見える（page.tsx:407, 909）:
  文言自体は build-brief.md の区画 8 行で承認済みだが、出典（page.tsx:678）は
  「サービス開始当初（ベータ期間）は手数料を請求しません」であり、「0円」という価格表示への言い換えは
  景表法の有利誤認（通常価格との関係・期間の不明示）の論点を新たに作る。
  修正案:「ベータ期間中は成約時手数料（通常 8%・税別）を請求しません。請求開始は事前にメールでお知らせします。」に戻す。
- M-3 robots.txt の Disallow と meta noindex の併用が機能矛盾（robots.ts:19 × page.tsx:19）:
  Disallow でクロールを止めるとクローラは noindex メタを読めない。外部被リンクが付くと URL のみがインデックスされる。
  プレビュー用途なら noindex 側だけを残し robots.ts の /lp を外すのが正しい（両方は不可）。
  Disallow は前方一致なので将来 /lp-* を作ると巻き込む（今は該当無しを確認）。
- M-4 縦タブの高さ指定が CSS 読み込み順に依存（katazuke.css:190-191 × lp.css:319-324）:
  .btn.btn-line の min-height:60px と .lp-page .lp-float-cta__btn の min-height:220px はともに特異度 (0,2,0)。
  勝敗は出力 CSS の順序に依存し、将来の import 位置変更やチャンク分割で 60px に潰れて縦書きラベルが溢れる回帰が起きうる。
  修正案: .lp-page .lp-float-cta .btn.btn-line（0,4,0）で書いて順序非依存にする。

---

## 4. Low

1. CASES 大キャッチ 2 行目が出典外の新規コピー（page.tsx:802-806「家まるごとの片付けを、／撮るところから。」）。
   build-brief の新規許可範囲は「区画の見出し・英字キャプション・ナビラベル・aria-label」で、
   実装は h2 ではなく p.lp-cases__catch（r2 L-6 の指示どおり）＝厳密には許可範囲外の新規本文。
   効果・期間・統計は含まないので景表法上のリスクは無い。build-brief に追認するか出典語に置換する。
2. 縦タブのタイルが「上端 12px の帯」になっていない（lp.css:326-331）。.btn.btn-line は flex-direction:row のままなので
   flex:0 0 12px は幅に効き、height:12px と合わせて左上の 12×12 の正方形になる。
   ただしタイルもボタンも #06c755 で同色（katazuke.css:190, 203）＝視覚差ゼロのため実害なし。指示との不一致のみ。
3. .lp-float-cta__alt のラベルが「よくある質問を見る」（LpChrome.tsx:177）。A2 の指示は「よくある質問」。
   縦書き 11px で 9 文字＝約 137px となり、縦タブ全体の高さが 357px に伸びて High-1 の重なり量を増やしている。
4. right:0 固定のため focus-visible のアウトラインがビューポート外へ半分切れる（lp.css:304-313）。right:4px を推奨。
5. overflow-clip-margin（lp.css:1470）は Safari の対応状況が版により異なる [要確認]。
   未対応環境では overflow:clip がパディングボックスで切るため、SP の pagetop top:-11px が切れる（C4 の効果が出ない）。
6. .lp-slider が inset:0＝KV 全面のため、PC でポインタが KV 上にあるだけで自動送りが止まる（LpSlider.tsx:70）。
   額縁時代は 3:2 枠の中だけだった。仕様違反ではないが「動かない KV」に見える。
7. メニューを閉じた後 700ms の間 .lp-menu は visibility:visible のままフェードするため（lp.css:375）、
   その間フェード中のリンクがフォーカス可能。visibility の遷移を 0s linear var(--lp-menu-dur) にすると閉じ切りで消える。
8. aria-controls の参照先が role=tabpanel を持たない img（LpSlider.tsx:75, 106）。ID は実在するので axe は通るが、
   tab と tabpanel の対を期待する AT では意味が伝わらない。
9. closeToAnchor が対象へ付けた tabindex=-1 を戻さない（LpChrome.tsx:66-68）。DOM に残り続ける（実害は小）。
10. SP の下部バーは .lp-kv の min-height:100svh の下端 56px を常時覆うため、KV 下端の白波形が隠れる。意匠上の軽微な差。

---

## 5. 回帰再走査（review-checklist.md B・C 節）

- B-10 grep 系: 100vw 0 件 / !important 0 件 / .lp-page 外のセレクタ 0 件（html.js-rv .lp-page ... のみ）/
  keyframes は lp-sway, lp-sway2, lp-float, lp-float2 の 4 本＝全て lp- 接頭辞。
- B-7 opacity:0 は 2 箇所のみ。lp.css:373（.lp-menu＝JS 開閉・既定 visibility:hidden で安全側）、
  lp.css:575（.lp-slider__slide＝1 枚目は React 初期 state の is-active が SSR 出力される）。
  html.js-rv 外での本文消失は無し。
- B-8/B-9 画像: 1 枚目のみ loading=eager + fetchPriority=high、他 5 枚は lazy（LpSlider.tsx:83-84）。
  他区画の img は全て lazy かつ width/height 指定。装飾は alt 空、意味のある alt は出典どおり。
  全スライドは position:absolute inset:0（katazuke-pages.css:484-486 の img-frame）なので CLS 要因なし。
- B-6 スライダー a11y: role=tablist/tab + aria-selected + aria-controls / 一時停止 aria-pressed /
  document.hidden・ホバー・フォーカスで停止 / reduced-motion で自動送りなし。ただし High-1 で操作不能。
- A3 (b) 非活性スライドの aria-hidden: aria-hidden は current 以外に true（全 alt 空なので二重に安全）。
- A2 下部バー: inert（LpChrome.tsx:167。React 19 系なので inert 属性が空文字で出力される）＋
  lp.css:315-318 の [inert] に visibility:hidden で MENU 開時に非表示。
  末尾の逃げ代は main ではなく .lp-footer の padding-bottom: calc(56px + env(safe-area-inset-bottom) + 48px)
  （lp.css:1749-1751）で確保＝footer が最終要素なので等価。
  同一バー内に代替導線 .lp-float-cta__alt があり LINE 単独導線ではない（タップ標的 約103×28px で WCAG 2.5.8 の 24×24 を満たす）。
- 縦タブの読み上げ: writing-mode:vertical-rl は視覚表現のみで DOM 順＝読み上げ順に影響しない。
  .btn-line__tile は aria-hidden（page.tsx:768 / LpChrome.tsx:169, 216）。
- C-1/C-2 コピー: DAILY 01〜09 は build-brief の 9 ステップと一字一句一致。
  h1・ABOUT・POINT・FEE・BIZ リードは page.tsx 出典と一致。
  禁止語はユーザー可視テキストに 0 件（ヒットはコード注釈の「必ず」のみ）。
  注: .lp-kv__sub は出典 .hero-sub の第 1 文のみを切り出している（「登録業者が買取総額で競い合い...」以降を落とす）。
  新しい約束は増えないが、KV 単独では「撮って待つだけ」の負担範囲が最大化して読める。r1/r2 で許容済みのため据置き扱い。
- C-3 モデルケース: MODEL_CASE_NOTE はカード群より手前（page.tsx:810-812）、MODEL_CASE_CHIP は各カード先頭で肖像より上（page.tsx:817）、
  amount 非表示（出るのは count / bidCount / days のみ）、caseName() 経由。
- C-4 打消し表示: .lp-fee__caution は .lp-fee__zero 内＝¥0 と同一視野・15px（lp.css:1160-1164）。
  .lp-about__note 2 行は 15px・白 100%（lp.css:793-799）。.lp-biz__note はカード群直前・15px（lp.css:1427-1433）。
- C-6/C-7: 新規の住所・電話・社名なし。dangerouslySetInnerHTML なし、外部 URL なし、target=_blank なし、
  インライン style は CSS 変数のみ、参照サイトの残骸なし。
- C-8: metadata の robots に index:false, follow:false あり（ただし M-3）。
- 見出し階層: h1 は KV の 1 本のみ。POINT は h2 → h3（main）→ h4（minors）→ h3（cells）の順で、
  h2 から h4 への飛びは無い（h4 が h3 より先に出る並びだが違反ではない）。

## 6. 確認できなかった項目（ブラウザ不使用のため）

1. 横スクロール（375/390/768/1280/1440）。.lp-page の overflow-x:clip があり固定要素は scrollWidth に寄与しないので
   静的には安全と読めるが、実測未了。
2. console error と画像 404（/img/v2/ex-lot-*.webp 6 枚の実在、3D レンダーの枠サイズ）。
3. High-1 / High-2 / High-3 の重なり量・コントラストは CSS からの計算値。実測スクショでの確認が必要。
   とくに High-3 は写真そのものの明度に依存する（暗部が veil のフェード帯に来るスライドが何枚あるか未確認）。
4. 区画高さの帯域（fidelity 側の担当）は本レビューでは未検証。
5. prefers-reduced-motion の実挙動（CSS・JS の実装はコードで確認済み）。
6. overflow-clip-margin の Safari 実対応 [要確認]。

## 7. 最短の修正順序（提案）

1. High-1: min-width:860px で .lp-slider__ctrl の right を 80px に（1 行）
2. High-2: min-width:860px で .lp-container の padding-inline-end を max(var(--lp-pad), 72px) に（1 行）
3. High-3: veil の stop を clamp() の px 基準に置換（PC・SP の 2 行）
4. High-4: closeToAnchor の focus を requestAnimationFrame で 1 フレーム遅延（3 行）
5. M-2 / M-3 は文言・設定の判断が要るためユーザー確認後
