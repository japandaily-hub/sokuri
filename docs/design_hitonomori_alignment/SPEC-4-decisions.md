# §4 確定事項（デザイナー査読 CRITIQUE.md の18件を反映）— **実装は本ファイルが SPEC.md §2 より優先**

## 4.1 トークン最終版（`katazuke.css :root`）
```css
:root{
  --primary:#527e52; --primary-d:#3f6640; --primary-l:#7fa37f; --deep:#2f4a30; --lime:#c9d128;
  --navy:#333; --ink:#333; --body:#4a4a4a; --body-soft:#6b6b6b; --head-gray:#959595; /* head-gray は24px以上の見出し専用 */
  --line:#d9e0d6; --line-soft:#ecf1ec; --white:#fff; --pale:#eff3ef; --pale-2:#f6f8f4; --warm:#fdf5d9; --mint:#daf4eb; --sky:#e1f5fd;
  --marker:#d4efb3; /* マーカー下線 */
  --apricot:#f3981d; --green:#527e52; --gold:#e5a323; --danger:#d70035;
  --radius:0px; --radius-s:0px; --shadow-s:none; --shadow-m:none; --shadow-l:none; --glow:none;
  --frame:1px solid #333; --ease:cubic-bezier(.22,.61,.36,1); --maxw:1140px; --maxw-text:760px;
  --serif:"Noto Serif JP","Hiragino Mincho ProN","Hiragino Mincho Pro","Yu Mincho","YuMincho","游明朝体",serif;
  --ui:"Noto Sans JP","Hiragino Kaku Gothic ProN","Yu Gothic UI",sans-serif;
  --head:var(--serif); --sans:var(--serif); --num:var(--ui);
  --en:"Montserrat",sans-serif; --en-display:"Libre Baskerville",serif;
  --blue:var(--primary); --blue-d:var(--primary-d); --blue-l:var(--primary-l); /* 旧名エイリアス */
}
```
- Google Fonts: `Noto+Serif+JP:wght@400;600` + `Noto+Sans+JP:wght@400;500` + `Montserrat:wght@600` + `Libre+Baskerville:wght@400`。Zen系は削除。`layout.tsx` に `<link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="">` を追加。
- **明朝で使うウェイトは 400 と 600 のみ（500禁止＝游明朝に実ウェイトが無く合成太字で滲む）。** 見出しは 400、ボタン文言・強調は 600。
- `body{ -webkit-font-smoothing:auto; -moz-osx-font-smoothing:auto; letter-spacing:.03em; }`（antialiased 指定は katazuke.css / globals.css の両方から外す）。
- 本文サイズ: マーケ面 16px / line-height 2.0。app 地の文 15px / 1.75。表セル・確認行 14px / 1.6。チャット吹き出し 15px / 1.7。
- **入力値・数値はゴシック**: `.field input,.field textarea,.field select, select, td .val, .confirm-row .val, .money, .fee-row .fv, .tabular-nums, [class*="tabular"] { font-family:var(--ui); font-variant-numeric:tabular-nums; letter-spacing:0; }`
- `:focus-visible{ outline:2px solid var(--primary); outline-offset:2px; border-radius:0; }` **リングは消さない。**
- `text-align:justify` は `@media(min-width:768px)` の散文ブロック（`.section-head .sub` `.media-copy .sub` `.founder-copy p`）だけ。

## 4.2 部品の確定
- **ボタン**: `.btn{border-radius:0;padding:16px 40px;font-family:var(--head);font-weight:600;font-size:16px;letter-spacing:.1em;transition:opacity .25s}` `.btn:hover{opacity:.8}` `.btn:active{opacity:.65}`。transform/box-shadow の上書きは全削除。`.btn-line,.btn-line:hover,.final .btn-line:hover{background:#06c755;color:#fff;box-shadow:none}`（既存の白地白文字バグを同時解消）。`.btn-ghost{border:1px solid #333;color:#333;background:#fff}`（緑枠にしない＝LINE緑と苔緑を隣接させない）。`.btn-line-auth`（LINEログイン公式ボタン）だけ角丸 99px 据え置き。
- **カード**: `.emp-card,.step,.scene-card,.trust-c,.bundle-c{border:0;background:transparent;box-shadow:none}` 枠も面も持たない。grid gap `clamp(28px,3.4vw,40px)`。hover は画像 `opacity:.85` + h3 緑のみ。`.cat{border:0;background:transparent}` `.cat-img{border:1px solid var(--line)}`。強調1枚 `.bundle-c.key{background:var(--pale);border-left:3px solid var(--primary)}` `.bc-badge{border-radius:0;background:var(--primary);top:0;left:0;box-shadow:none}`。
- **リズムは罫線で作る**: `.section-head h2::after{content:"";display:block;width:48px;height:1px;background:var(--primary);margin:18px auto 0}`、`h2::first-letter{color:var(--primary)}`（`.section-head h2`, `.hero h1`, `.media-copy h2`, `.bundle-copy h2`, `.founder-copy h2`, `.final h2`）。
- **ヒーロー**: 写真は円形にしない。`.hero-photo{border-radius:0;aspect-ratio:3/4;border:0;box-shadow:none;overflow:visible;position:relative}` `.hero-photo img{object-fit:cover;object-position:center 35%}` `.hero-photo::before{content:"";position:absolute;inset:-6px -6px 6px 6px;border:1px solid var(--primary);pointer-events:none}` `.hero-photo::after{content:"";position:absolute;top:50%;left:-46px;width:38px;border-top:1px dashed #333}`。`kdzScan`/`kdzPulse` と `.hero::before/::after` の弧は削除。「AI解析中」バッジ（`.hero-figure::after`）は直角・白地・緑文字・静止で残す（`.hero-figure::before` のパルス点は削除）。blob: `.hero{background:#fff;position:relative;overflow:hidden}` + `.hero-blob{position:absolute;right:-12vw;top:-30vh;width:70vw;height:120vh;background:#eef4de;border-radius:42% 58% 55% 45%/48% 42% 58% 52%;z-index:0;pointer-events:none}`（B が tsx に `<div className="hero-blob" aria-hidden="true" />` を `.hero` 直下の先頭に1つ追加）。h1 `clamp(30px,4.6vw,50px)` 400 line-height 1.6。`.hl{color:var(--primary);background:linear-gradient(transparent 70%,var(--marker) 70%)}`。
- **マーカー強調 `.mk`**: `.mk{font-weight:400;background:linear-gradient(transparent 68%,var(--marker) 68%)}`。**引用符の扱い: 引用符の中身が強調語（"買取総額" "家まるごと" "めんどう" "まとめ全体" "まとめて一括買取"）なら `<span className="mk">…</span>`、会話・言葉の引用なら「」。** 1段落に鉤括弧が3組並ぶ状態を作らない。
- **無料表示**: `.fee-row .fv{color:var(--primary);font-family:var(--ui);font-weight:600;background:linear-gradient(transparent 68%,var(--marker) 68%)}`。
- **額装フレーム `.site-frame`**: `SiteChrome` で `<SiteHeader/>` の**外側**に描き、`children` を `<div className="site-frame">` で包む（`/` のランディングだけは page.tsx 側が自前で `.site-frame` を 3 枚に分けて描くため、SiteChrome は `pathname === "/"` のとき包まない）。CSS: `.site-frame{margin:20px;border:var(--frame);min-height:calc(100dvh - 40px)} .site-frame+.site-frame{margin-top:0} @media(max-width:859px){.site-frame{margin:0;border:0;min-height:0}}`。**`.site-frame` に `overflow` を書かない**（sticky が死ぬ）。`.header{position:sticky;top:0;background:#fff;border-bottom:1px solid var(--line);backdrop-filter:none}`。`.scroll-progress` は `@media(min-width:860px){display:none}`、モバイルは 2px 緑。
- **縦書き見出し `.vt`**: 実要素 `<span className="vt" aria-hidden="true">…</span>` を `#bundle`（「まとめて出すほど、有利になる。」）と `#auction`（「業者が買取総額で競うから、高くなりやすい。」）の **2 セクションだけ**に、`<section>` 直下の先頭に置く。CSS: `section:has(>.vt){position:relative} .vt{display:none} @media(min-width:1280px){.vt{display:block;position:absolute;top:clamp(64px,8vw,108px);right:max(8px,calc((100vw - var(--maxw))/2 - 46px));writing-mode:vertical-rl;text-orientation:mixed;font-family:var(--head);font-size:34px;font-weight:400;line-height:1.35;letter-spacing:.12em;color:#333} .vt::first-letter{color:var(--primary)}}`。モバイルでは絶対に出さない。
- **ロゴ `KdzLogo`**: 文字ワードマーク。`<span className="kdz-wm" style={{"--wm": size+"px"}}><span className="kdz-wm-ja">カタヅケ</span><span className="kdz-wm-en">KATAZUKE</span></span>`。CSS: `.kdz-wm{display:inline-flex;flex-direction:column;line-height:1;color:#333} .kdz-wm-ja{font-family:var(--head);font-weight:400;font-size:var(--wm,22px);letter-spacing:.14em} .kdz-wm-en{font-family:var(--en);font-weight:600;font-size:calc(var(--wm,22px)*.4);letter-spacing:.18em;color:var(--primary);margin-top:4px} .kdz-wm.white{color:#fff} .kdz-wm.white .kdz-wm-en{color:var(--lime)}`。`variant="white"` は `.white` クラス。OG画像・apple-icon 用にも同じ二段ワードマーク（緑・白地）で描き直し、`manifest.ts` の `theme_color`=`#527e52`、`background_color`=`#ffffff`。
- **ステップ番号・FAQ Q・入札順**: `font-family:var(--en-display);color:var(--primary);background:none;border-radius:0;width:auto;height:auto`。ステップは `.step-n .num::before{content:"0"}` で 2 桁表示（DOM不変）。
- **タグ・ステータスバッジ**: 直角・`1px solid` 細枠・地は透明または `var(--pale)`。意味色: 進行=`var(--primary)` / 注意=`var(--gold)` / 危険=`var(--danger)` / 中立=`var(--body-soft)`。赤地・青地ベタは使わない。円形アバター（`border-radius:50%`）は据え置き。ピル（999px/99px/9999px）は 0 に（`.btn-line-auth` を除く）。
- **フォーム**: `.field input,textarea,select{border-radius:0;border:1px solid #ddd;background:#fff;padding:12px 14px}` focus `border-color:var(--primary)` + 共通 focus-visible リング。必須 `.req{background:var(--primary);color:#fff;padding:2px 10px;font-size:12px}` 任意 `.opt{background:#808080;color:#fff;padding:2px 10px;font-size:12px}`。パネル `.auth-card{border-radius:0;box-shadow:none;border:1px solid var(--line);background:#fff}` `.auth-page{background:var(--pale)}`。
- **フッター**: 白地・`border-top:1px solid var(--line)`・文字 12px `#666`・h5 は `var(--en)` 600 uppercase 11px 緑 `letter-spacing:.14em`。`.footer-bottom` は中央揃え。`.footer-logo img` の invert フィルタは削除（ワードマーク化）。
- **業者バナー `.biz-banner`**: `background:var(--pale);border-top:1px solid var(--line);border-bottom:1px solid var(--line)`。h2 `#333`、p `var(--body)`、`.biz-tag{border:1px solid var(--primary);color:var(--primary);background:#fff;border-radius:0}`、`.btn-white` は緑地白文字の直角（クラス名は据え置き）。
- **オーバーレイ・トースト**: `.kdz-overlay{background:rgba(51,51,51,.45)}` `.kdz-toast{border-radius:0}`。
- **Reveal `.rv`**: `transform:none`、opacity のみ。
- **`width:100vw` を使う箇所は `100%` へ**（額の外にはみ出すため。各グループで grep して潰す）。
- **アイコン `.ic`**: stroke-width 1.5。

## 4.3 言葉の作法 確定（コピーの意味は不変・記号のみ）
| 対象 | 変換 | 備考 |
| :-- | :-- | :-- |
| `“強調語”` | `<span className="mk">強調語</span>`（JSX内）／metadata 文字列内は引用符を外す | 文字は変えない |
| `“会話・言葉”` | `「…」` | |
| 本文の `——` `—` | 「、」または「。」で切る（意味不変の最小変更） | 例:「納得できる——だから安定する。」→「納得できる。だから安定する。」 |
| metadata/title の ` — ` | `｜` | 例: `カタヅケ｜家まるごと、まとめて片付け買取` |
| withdraw の `title: "X — Y"` | `X：Y` | |
| 欠損値フォールバック `"—"` | **据え置き**（コピーではない） | |
| コードコメント内 | 据え置き | |
| `！` | `。`（h1/h2 の完了文言）／`STAR_LABELS` の「良かった！」「最高でした！」は「良かった」「最高でした」 | |
各担当は自分の担当ファイルの変更を `docs/design_hitonomori_alignment/WORDING_CHANGES_<A|B|C|D1|D2>.md` に「ファイル:行 / 変更前 / 変更後」で記録する。

## 4.4 ファイル所有（並列実装・重複編集禁止）
| 担当 | 所有ファイル |
| :-- | :-- |
| **A コア/テーマ層** | `web/src/app/katazuke.css` `katazuke-pages.css` `globals.css` `web/tailwind.config.ts` `web/src/app/layout.tsx` `manifest.ts` `apple-icon.tsx` `opengraph-image.tsx` `web/src/components/kdz/Logo.tsx` `SiteHeader.tsx` `chrome.tsx` `SiteChrome.tsx` `interactions.tsx` `Icons.tsx` `web/DESIGN_SYSTEM.md` |
| **B ランディング** | `web/src/app/page.tsx` `web/src/components/landing/*.tsx` |
| **C マーケ/静的/認証ページ** | `web/src/app/{business,company,contact,examples,faq,photo-guide,privacy,terms,legal,unsubscribe,verify-email,password-reset,signup,login,vendors}/**` `not-found.tsx` `not-found.css` `error.tsx` `web/src/components/AuthCard.tsx` |
| **D1 アプリ画面(利用者側)** | `web/src/app/{mypage,chat,schedule,notifications,review,applications,cases,result,condition,analyzing,create}/**` `web/src/components/{ChannelCard,ConditionCard,DefectUploader,Icon,PhotoGuide,Stepper}.tsx` |
| **D2 アプリ画面(業者/管理側)** | `web/src/app/{operator,admin}/**` `web/src/components/kdz/{AppHeader,AppHeaderLogout,OperatorHeader,HeaderNav,Ui,DisclosureNotice,auth}.tsx` `web/src/components/kdz/operator-header.css` |
- 他担当のファイルは**読むだけ**。共通クラス（`.site-frame` `.vt` `.mk` `.kdz-wm*` `.req` `.opt` `.hero-blob`）は A が §4.2 の名前で定義する。B/C/D は A の完成を待たずに、§4.1 のトークン名を前提に置換してよい。
- `npm run build` / `npm run dev` は**担当者は実行しない**（.next の同時書き込み衝突）。`npx tsc --noEmit` は可（自分の担当ファイルのエラーだけ直す）。
