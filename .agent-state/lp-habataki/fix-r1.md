# /lp 修正指示 r1（リーダー裁定・2026-09-17）

3 本の独立レビュー（`review-fidelity-r1.md`／`review-qa-r1.md`／`review-legal-sec-r1.md`）を統合し、採否を確定した。**本書の番号順に全件対応**。却下した指摘は末尾に理由付きで列挙（対応不要）。
編集可: `web/src/app/lp/**`、`web/src/components/kdz/SiteChrome.tsx`、**追加で `web/src/app/robots.ts`（Disallow 1 行のみ）**。他は禁止のまま。

## A. High（必須）
1. **pagetop を footer 内の absolute へ**（fidelity H1）。`position:fixed` チップを廃止。`.lp-footer{position:relative}` の右端に主色ブロック（PC 幅 36%・高 290px、SP 幅 31%・高 98px・top:-11px で footer 上端から少しはみ出す＝参照どおり）。白文字「PAGE TOP」＋上矢印。`aria-label="ページの先頭へ"`。
2. **垂直リズムを参照に合わせる**（fidelity H2）。PC 1280 での区画高さを reference-spec の値の **−15%〜+10%** に収める（KV 900／MESSAGE 976／ABOUT 2829／POINT 各ブロック 2922・2520・1566（撮/選/安）／DAILY 2926／FEE 2635／CASES 3775／BIZ 2447／FOOTER 838）。手段は `padding-block`・item 間 margin・色面の高さ（下記 B-4）・写真枠の拡大。**SP は逆に DAILY を 3300px 前後まで詰める**（写真を 2 サイズにし小さい写真は 2 列に）。修正後、各区画の高さを `getBoundingClientRect` で実測して戻り値に表で貼る（実測はリーダーが行うので、あなたは CSS の値を根拠として表に書く）。
3. **KV ドット列をビューポート右端中央に縦並び**（fidelity H3）: `.lp-slider__dots{position:absolute;right:24px;top:50%;transform:translateY(-50%);flex-direction:column}`（KV セクションを基準に）。一時停止ボタンはドット列の直下。SP も縦のまま右端（参照どおり）。
4. **MENU オーバーレイのフォーカス閉じ込め**（qa H1）: 開いている間、オーバーレイ以外の兄弟（header の他要素・浮遊CTA・main・footer）に `inert` を付与（React 19 の `inert` 属性）。加えて Tab/Shift+Tab を nav 内の最初/最後の要素で循環させる keydown ハンドラ。閉じたら解除。
5. **footer を main の外へ**（qa H2）: 根を `<div className="lp-page">` にし、その中に `<header className="lp-header">`（qa M1: div → header）＋ `<main id="main">`（区画 1〜8）＋ `<footer className="lp-footer">`。lp.css のスコープ `.lp-page` はそのまま効く。
6. **SP でも浮遊CTAの代替導線を残す**（legal H1）: `@media(max-width:859px)` の `.lp-float-cta__alt{display:none}` を撤去し、LINE タイルの直下に白地 11px の「よくある質問を見る」を残す（幅は LINE タイルと同じ）。
7. **引き取り可否の注記を追加**（legal H2）: ABOUT 帯下端の `.lp-about__note` に、既存の `※ 最終的な買取額は業者の現物査定により決まります。` と並べて **`※ 引き取りの可否・条件は品物や業者により異なります。一部、引き取りが難しい物は手放す導線をご案内します。`**（`page.tsx:344` の `.bundle-note` を一字一句）を 2 行目として追加。両方とも **15px・白（不透明度 1.0）**（legal M4）。

## B. Medium（必須）
1. ABOUT の強調語の色（fidelity M4）: `--lime` をやめ、**白文字＋白 32% のマーカー下線**（`color:#fff;background:linear-gradient(transparent 68%,rgba(255,255,255,.32) 68%)`）。黄は使わない（カタヅケの `--gold` は注意色）。
2. 循環帯 `.lp-cycle` を主色帯に（fidelity M5）: `background:var(--primary)` ＋上下 `.lp-wave--primary`。イラスト 6 点は **白地の正方形タイル（1px 罫なし・aria-hidden）** に載せる（青系イラストが青地に沈むため）。見出しは白で **「顧客・業者・社会の三者に喜びと安心を。」**（`page.tsx:619` の strong と一致・末尾に「。」のみ追加）に差し替え（legal M7 の「片付いた物は、次の誰かのもとへ。」は削除。英字 `recycle loop` も `three-way satisfaction` 等の効果を示さない語へ）。
3. CASES に intro/outro 帯（fidelity M6）: `#cases` の前に **`--sky`（#e1f5fd）の intro 帯**（上端に波形・高 450px 前後・中に h2「こんなふうに使えます」＋極小英字）→ 淡色地に **2 行の大キャッチ「家まるごとの片付けを、／こんなふうに使えます。」（2 行目を主色）＋本文 2 行（sub の 1 文 ＋ `MODEL_CASE_NOTE`）** → カード 3 件 → **`--sky` の outro 帯**（対応エリア 1 行＋「会社概要を見る」）。`MODEL_CASE_NOTE` はカード群より手前を維持。
4. POINT の色面（fidelity L10 を昇格・A-2 と連動）: `.lp-point__plate{height:min(54vw,640px)}`、バッジは色面の左端から `clamp(24px,18%,220px)` 内側・上端から 15% の位置。
5. FOOTER の地を `--pale-2`（fidelity M7）。
6. SP の KV: `min-height:100svh`（fidelity M8）。**浮遊イラストは SP では見出しに重ねない**（h1 の帯には置かず、写真枠の四隅付近の 4 点だけ・2 点は `display:none`）。sub の「撮って、」の直後に `<br className="sp-br" />` を入れて「け。」の 1 文字折返しを防ぐ（既存の `.sp-br` は globals.css 定義済み・文言は不変）。
7. スライダー非活性スライドに `aria-hidden`（qa M2・`HeroCarousel` と同じ）。
8. コピーの是正（legal M3/M6/M8）: 撮ブロック h2 を **「あなたがするのは、「撮る」と「選ぶ」だけ」** に戻す／浮遊CTAの sub を **「登録・査定・お断りまで無料」**（`page.tsx:288` の一部を一字一句）に／BIZ にタグ **「古物商許可が必要」** を復活し、カード 3 枚は `biz-tag` の並列関係を保つ（カード1「初期費用・月額費用 無料」、カード2「成約時8%（税別）のみ」、カード3「下見なし・一斉架電なし」＋4 本目のタグ「古物商許可が必要」はカード群直下の注記行に）。リード部とカード本文の重複 2 組（fidelity L11）は、リード側に `p` 全文・カード側は短文（タグ文言のみ）にして解消。**`.lp-biz__note`（β期間の注記）は 15px・`--body` でカード群の直前に**（legal M5）。
9. `robots.ts` に `/lp` の Disallow を追加（legal M9）。`metadata.alternates.canonical` を `"/lp"` に（qa L2・legal L）。

## C. Low（対応する）
1. 画像の `width/height` を実寸に（`top-founder-desk`・`top-handover` → 1536×1024）（qa L1）。
2. MESSAGE の下端を二重の丘（`.lp-wave--white` を 2 枚・`translateY` 差 40px・不透明度差）（fidelity L12）。**左の 2 枚を写真に差し替え**: 大＝`top-hero-couple-60s.webp`（2:3 → 枠 4:5）、小＝`top-scene-jikka.webp`（1:1）。alt は出典どおり（`page.tsx:42`／装飾なら `""`）。
3. DAILY の写真を 3 サイズ（46%／33%／26%）に配り、item 間の破線トレイルを 4〜6 本に（fidelity L9）。
4. 署名の後半 **「顧客にも業者にも、社会にも。三方よしの場所をつくります。」** を `.founder-sign` と同じ構造で復活（legal L10）。metadata.description を `layout.tsx:33-34` の文言そのまま（「あなたが」を削除）（legal L11）。
5. `.lp-ill--f1/f2` が SP でビューポート外へ出る（fidelity L14）: SP では `right` を正の値に、または `display:none`（B-6 と合わせて処理）。

## D. 却下（対応不要・理由）
- 浮遊CTAを SP でも右上固定に戻す（fidelity L13）: SP では MENU と衝突し、参照でも SP は右上に MENU・CTA が重なって見える。UX を優先して右下固定を維持（代替導線は A-6 で担保）。
- hero-sub の残り 3 文を KV に足す（legal L9）: 文単位の引用は許容。KV の情報量を参照どおり最小に保つ。
- KV スライダーの ex-lot 画像に打消し（legal L14）: alt=""・数値なし・モデルケース名も出ないため装飾扱いで可。
- `.lp-page` 外に `opacity:0` が 2 箇所（MENU 閉状態・非活性スライド）: 無 JS の初期状態が安全側なので許容。
- 「成約時8%（税別）」の古物競りあっせん業論点: 既知の未決・全ページ共通（/lp 固有ではない）。

## 完了条件
- `npx tsc --noEmit` 0／`npx eslint src/app/lp src/components/kdz/SiteChrome.tsx src/app/robots.ts` 0/0。
- 戻り値（30 行以内）: 対応した番号の一覧（A1〜C5）、未対応があればその番号と理由、区画高さの根拠表、変更ファイル一覧。
