# /lp QA＋表示規制 独立レビュー r2（2026-09-17）

検査対象: `web/src/app/lp/page.tsx` / `lp.css` / `_components/LpChrome.tsx` / `_components/LpSlider.tsx` /
`web/src/app/robots.ts` / `web/src/components/kdz/SiteChrome.tsx`（差分）
実行環境: dev/build/ブラウザ未使用（指示どおり）。静的解析＋ファイル実測のみ。

## 0. 自動チェック

| 項目 | 結果 |
|---|---|
| `npx tsc --noEmit` | exit 0 / エラー 0 |
| `npx eslint src/app/lp src/components/kdz/SiteChrome.tsx src/app/robots.ts` | 出力なし = 0 error / 0 warning |
| 禁止語スキャン（最高／No.1／絶対／実際の／お客様の声／実績／累計／平均／成約率／利用者数／必ず／保証／◯日で） | ヒット 0 |
| `!important` / `100vw` / `.lp-page` 外セレクタ / `lp-` 以外の keyframes | 0（`html.js-rv .lp-page` の 2 行のみ＝規約で許容） |
| `opacity:0` の位置 | lp.css:338（MENU 閉状態）・lp.css:530（非活性スライド）のみ。`html.js-rv` 外の本文消失リスクなし |
| 外部 URL / dangerouslySetInnerHTML / target=_blank / coco-terrace 参照 | 0（`url()` は data: URI のみ） |
| 画像 27 枚の実在と実寸 | 全件存在・全件 width/height 一致（webp ヘッダ実測。top-founder-desk=1536x1024・top-handover=1536x1024・top-hero-*=900x1350・top-scene-*=800x800・*-3d=1536x864・trust-illus-*=1024x768・top-cta-band/biz-band-sorting=1920x1088・ex-lot-*=1536x1024） |
| コピー一字一句照合（98 文字列を page.tsx / model-cases.ts / examples / business / layout / build-brief §4-B と突合） | 不一致 0 |

## 1. 前周指摘（fix-r1）の再検証

| # | 指摘 | 判定 | 根拠 |
|---|---|---|---|
| A-4 | MENU のフォーカス閉じ込め（inert＋Tab 循環） | 直った（残課題は Low 2 件） | LpChrome.tsx:45 `INERT_SELECTORS=["#main",".lp-footer"]`／:73-78 で付与＋cleanup で必ず除去（閉時・アンマウント時とも）。:132/:156 でロゴ・浮遊CTAに React 19 の boolean `inert`（react ^19.0.0・@types/react ^19・tsc 0 で型 OK）。:81-115 の Tab ハンドラは MENU ボタンを輪に含め、`items.length===0` ガード・`index===-1`（輪の外にフォーカス）・Shift+Tab の両端をすべて処理。body スクロールロック :61-68 は `prev` 保存→復元。 |
| A-5 | footer を main の外へ | 直った | page.tsx:461 `div.lp-page` > :127 `header` ＋ :464 `<main id="main">` ＋ :929 `<footer>`。banner/main/contentinfo が揃う。layout.tsx:122 のスキップリンク `#main` も有効。 |
| A-6 | SP でも浮遊CTA の代替導線 | 直った | lp.css:1487-1493 で `.lp-float-cta__alt{display:block}`（display:none は残っていない）。SP は bottom:0 の列で LINE タイル直下・タイルと同幅（align-items:stretch／width:208px）。LINE 単独導線ではない。 |
| A-7 | 引き取り可否の注記 | 直った | page.tsx:575-577。文字列は page.tsx:344 `.bundle-note` と完全一致（先頭の「※ 」含む）。lp.css:744-754 で 2 行とも font-size:15px / color:#fff（不透明度 1.0）。 |
| B-1 | ABOUT 強調語の色 | 部分的に直った（新規 High を残す） | `h3 em` は lp.css:729-733 で白＋白 32% マーカーに是正済み。しかし `.lp-band__head .lp-en`（lp.css:684-686）に `--lime` が残存＝H-1。 |
| B-2 | 循環帯を主色帯に | 直った（波形は別解） | lp.css:918-939 `background:var(--primary)`＋白正方形タイル（padding:9%・border-radius なし）。page.tsx:670 `.ill-loop` は aria-hidden。見出し :667「顧客・業者・社会の三者に喜びと安心を。」＝page.tsx:619 の strong ＋「。」のみ。英字は three-way satisfaction（効果語でない）。上下の波形は「隣接区画の色」で塗る実装（primary 帯に primary の波は不可視のため）。指示文言と異なるが技術的に妥当。 |
| B-7 | 非活性スライドの aria-hidden | 直った | LpSlider.tsx:80。aria-selected :96／aria-pressed :107／reduced-motion で自動送り停止 :50＋トグル非表示 :104＋CSS transition 無効 lp.css:590-595。タイマーは useEffect 1 本・deps 4 個で多重生成なし・cleanup で clearInterval。document.hidden とホバー（pausedRef）で抑止。 |
| B-8 | コピーの是正 4 件 | 直った | 撮 h2＝page.tsx:243 と一致（lp/page.tsx:174）／浮遊CTA sub「登録・査定・お断りまで無料」＝examples/page.tsx:285 の断片と一致（LpChrome.tsx:161）／BIZ「古物商許可が必要」復活（page.tsx:916、出典 page.tsx:687）／カード 3 枚は biz-tag 3 本と一致（:404-406）で h のみ・p なし＝新しい因果を作っていない。`.lp-biz__note` は page.tsx:904 でカード群（:905）の直前・lp.css:1358-1364 で 15px・文言は page.tsx:693 と完全一致。 |
| B-9 | robots / canonical | 直った | robots.ts で disallow に "/lp" 追加。allow:"/"・sitemap・host は無改変。sitemap.ts に /lp エントリなし（矛盾なし）。lp/page.tsx:19-20 で robots:{index:false,follow:false} ＋ alternates:{canonical:"/lp"}。 |
| C-1 | 画像の width/height を実寸に | 直った | §0 の実測表。top-founder-desk（page.tsx:754）・top-handover（:143-144 / :334-335 / :390-391）とも 1536×1024 で一致。 |
| C-4 | 署名後半＋description | 直った | page.tsx:540-542 は page.tsx:620 `.founder-sign` と span 構造・文言とも完全一致。lp/page.tsx:17-18 の description は layout.tsx:33-34 と一字一句一致。 |

直った 10 件／部分的 1 件（B-1）／直っていない 0 件。

## 2. コピー照合（C 節 1・2）

98 文字列を自動突合し、非一致はゼロ。新規に書き起こされた文字列は以下のみで、いずれも「区画見出し・ラベル・英字キャプション・aria-label」の範囲内:

- 区画見出し: 「カタヅケは、まとめ売りの買取マッチングです。」「カタヅケの、出品から引き取りまで。」「こんなふうに使えます」「家まるごとの片付けを、／こんなふうに使えます。」「顧客・業者・社会の三者に喜びと安心を。」（末尾「。」のみ追加）
- ラベル: 「詳しく見る」「会社概要を見る」「よくある質問を見る」「6件のモデルケースを見る」「対応エリア: 東京都・千葉県・埼玉県・神奈川県（順次拡大）」
- 英字キャプション: about katazuke / message from katazuke / from listing to pickup / usage images / for buyers / three-way satisfaction / - SHOOT / CHOOSE / TRUST -
- alt 文: いずれも page.tsx の同一画像の alt と完全一致（bundle-3d:315 / bid-3d:362 / top-handover:380 / trust-illus-1:507 ほか）
- DAILY 01〜09 の本文: build-brief.md:72 の確定文言と完全一致（06「提示を見比べて1社を選択。…」含む）
- POINT 小見出し「写真・品目・地域のみ」「詳細住所とメールは成立後」: build-brief.md:33 の確定文言

新しい約束・期間・効果・統計の追加はなし。住所・電話・会社名の新規記載もなし（4 都県＋順次拡大のみ）。

## 3. 打消し表示（景表法）

| 要件 | 判定 | 根拠 |
|---|---|---|
| MODEL_CASE_NOTE がカード群より手前 | OK | page.tsx:806-808（intro 帯 h2 → 大キャッチ → sub → note → :809 カード群）。intro 帯・大キャッチの挿入で順序は崩れていない。 |
| MODEL_CASE_CHIP が各カード先頭 | OK | page.tsx:813 が Reveal(article) の第 1 子。lp.css:1217-1221 で grid-column:1/-1 ＝ 1 行目を全幅占有し、肖像（:814）・数値（:831）より視覚的にも上。SP 1 列でも同じ。 |
| 金額（amount）非表示 | OK | 描画は count / bidCount / days のみ（page.tsx:831-853）。c.amount 参照なし。days の表示は page.tsx:477 と同型で house 一貫。 |
| caseName() 経由の（仮名） | OK | page.tsx:826。 |
| 打消しが ¥0 と同一視野・15px | OK | `.lp-fee__caution`（page.tsx:747-749 / lp.css:1098-1103）は `.lp-fee__zero` パネル内、¥0 の 2 行下・font-size:15px。文言は出典と一致。 |
| ABOUT 注記 2 行が 15px・不透明度 1 | OK | lp.css:744-754。 |
| `.lp-biz__note` 15px・カード群直前 | OK | page.tsx:904 / lp.css:1358-1364。「成約時8%（税別）のみ」カードより前に「β期間中は手数料0円」が出る＝限定条件が主張に先行。 |
| LINE 単独導線でない | OK | 浮遊CTA（/faq 併置・PC/SP とも）・FEE（/examples ゴースト併置）・MENU（/examples・/business パネル併置）。btn-line__tile は aria-hidden。 |

## 4. 新規指摘

### High

**H-1 主色帯の英字キャプションが WCAG 1.4.3 AA 不足（B-1 の是正漏れ）**
- ファイル: `web/src/app/lp/lp.css:684-686`
- 期待: 主色帯（--primary #1447e0）上の 11px テキストは 4.5:1 以上。
- 実測: `.lp-band__head .lp-en{color:var(--lime)}` → --lime = #8fb4ff（katazuke.css:16）。コントラスト比 3.32:1（11px / weight 600 は「大きな文字」に該当せず 4.5:1 必須）。--lime は katazuke.css のコメントどおり --deep(#14235c) 上（7.06:1）を想定した色で、--primary 上での使用は設計外。さらに `.lp-texture`（黒ノイズ opacity .06）が重なるため実効値はもう一段下がる。影響は ABOUT / DAILY / 循環帯の見出し 3 箇所。B-1 が em（3.6:1）で問題視したのと同一の欠陥がキャプション側に残存している。
- 再現条件: PC/SP 問わず常時。axe・Lighthouse の contrast 検査で検出される。
- 修正案: `.lp-page .lp-band__head .lp-en{color:rgba(255,255,255,.92)}`（6.1:1）に置換し、--lime は --deep 面専用に戻す。

### Medium

**M-1 ABOUT item の英字キャプションも AA 不足**
- ファイル: `web/src/app/lp/lp.css:718-720`
- 期待: 4.5:1 以上。実測: `rgba(255,255,255,.72)` を #1447e0 に合成すると 4.33:1（11px）。
- 修正案: `.72` を `.80` に上げる（4.98:1 で AA 通過・階調差も保てる）。

**M-2 KV スライダーのドット列が写真から数百 px 離れる（操作対象の近接性／実装とコメントの不一致）**
- ファイル: `web/src/app/lp/lp.css:494-498, 521-525, 539-549`／`LpSlider.tsx:67-68`
- 期待: ドットは切り替え対象の写真に隣接（参照は写真右端）。
- 実測: `.lp-slider{max-width:520px;margin:...auto}` で写真は中央 520px。`.lp-slider__ctrl{right:24px}` は全幅の `.lp-kv__stage` 基準なので、1920px 幅では写真右端（x≈1220）とドット（x≈1896）が約 680px 離れる。さらに `top:50%` の基準は `.lp-kv__stage`（lp.css:494 が position:relative）であり、lp.css:492-493 と LpSlider.tsx:67-68 のコメントが言う「基準は .lp-kv」とは異なる（KV 中央ではなく写真中央に揃う）。
- 再現条件: ビューポート幅 1440px 以上で顕著。
- 修正案: `.lp-slider__ctrl{right:max(24px, calc(50% - 300px))}`（100vw 不使用のまま写真右端に寄る）。

**M-3 footer の overflow:hidden が pagetop の SP 仕様とフォーカスリングを切る**
- ファイル: `web/src/app/lp/lp.css:1397`（`.lp-footer{overflow:hidden}`）×`:1495-1498`（`.lp-pagetop{top:-11px}`）
- 期待: A-1 の「SP では footer 上端から少しはみ出す」／`:focus-visible` リング（globals.css:55）が全周見える。katazuke.css:189 が「overflow:hidden を付けない（focus リングを切らないため）」と明示している作法。
- 実測: 祖先が overflow:hidden のため top:-11px のはみ出しは描画されない。`.lp-pagetop{right:0}` の右側フォーカスリングも footer 右端で切り落とされる。
- 修正案: `.lp-footer{overflow:clip;overflow-clip-margin:16px}`（波形の横漏れを抑えたまま 11px のはみ出しとリングを通す）。

### Low

- **L-1** `LpSlider.tsx:91-102`: role="tab" に aria-controls がなく、スライド側に role="tabpanel" もない（ARIA APG 非準拠）。ただし house 実装 HeroCarousel（interactions.tsx:355-361）と同型のため /lp 固有の回帰ではない。修正案: スライドに id＋role="tabpanel" を与え aria-controls で結ぶか、tablist をやめて単純な button 群にする。
- **L-2** `LpSlider.tsx:70` vs `:90`: onMouseEnter/Leave が `.lp-slider`（写真）だけに付き、ドット列 `.lp-slider__ctrl` は対象外。ドットへポインタを置いたまま 6 秒経つとスライドが動く。修正案: pause/resume を両方を包む共通ラッパに移す。
- **L-3** `LpChrome.tsx:55-58` の close() を `:184` のページ内アンカーからも呼ぶため、キーボードで「料金」等を選ぶとフォーカスがヘッダーの MENU ボタンに戻り、遷移先の区画に追従しない。修正案: アンカー経由の close はフォーカス復帰を行わない別関数にする。
- **L-4** `LpChrome.tsx:127` の `.lp-header` は z-index 70（lp.css:240-247）で `.lp-menu` の 68 より上。MENU を開いている間、inert 済みのロゴ白タイルがオーバーレイの上に残り、押しても何も起きない死角になる。修正案: 開いている間は `.lp-header__logo` を visibility:hidden にする。
- **L-5** `robots.ts:18` の "/lp" は前方一致（将来の /lp-* も巻き込む）。また Disallow と robots:{index:false} の併用はクローラが noindex を読めないため URL のみのインデックス登録を防げない。sitemap.ts に /lp が無く公開前提でもないため実害は小さいが、本採用時は Disallow を先に外す運用が必要。
- **L-6** `page.tsx:789` の h2「こんなふうに使えます」と `:798-802` の大キャッチ「家まるごとの片付けを、／こんなふうに使えます。」が 1 ビューポート内でほぼ同文の反復（B-3 の指示どおりだが冗長）。
- **L-7** `page.tsx:506` の aria-labelledby="lp-message-en" が指すアクセシブル名は英字「message from katazuke」のみ。日本語ページのリージョン名として読み上げが不自然。修正案: 視覚非表示の日本語見出しを別途与える。
- **L-8** `page.tsx:888-901` のリード 3 行目（β手数料）と `:904` の `.lp-biz__note` が同一条件の重複表示（両方とも出典どおりなので違反ではない）。

## 5. 確認できなかった項目（本周の制約）

1. **A-2 / B-4 の区画高さ**（PC 1280 で reference-spec の -15%〜+10%）: CSS 値からは padding/gap の増加を確認できるが、実レンダリング高さは未計測（dev/ブラウザ使用禁止のため）。視覚レビュアー側の実測に依存。
2. **375/390/768/1280/1440 の横スクロール有無**: 静的には溢れ要因を特定できず（`.lp-ill` は SP 幅 clamp(56,16vw,72)＋float 振れ幅 10% でも 390px 内に収まり、親も overflow:hidden。`.lp-float-cta` は right:0・208px 固定）。ただし scrollWidth<=clientWidth の実測は未実施。
3. **console error・画像 404**: パスとファイル実在は照合済み（27/27 一致）だが、実行時の警告（React の inert 出力・fetchPriority 等）は未確認。
4. **`.lp-texture`（黒ノイズ opacity .06）重畳後の実効コントラスト**: 計算は素地のみで実施。H-1/M-1 は実効値がさらに悪化する方向で、判定は変わらない。
5. **iOS Safari での body{overflow:hidden} スクロールロック**: iOS では効かないことが知られる［要確認: 本プロジェクトの対象ブラウザ範囲が未定義］。必要なら position:fixed＋top:-scrollY 方式へ。
6. **`.lp-menu` に role="dialog"/aria-modal が無い点**: inert で背面を落としているため実害は小さいが、スクリーンリーダーの実機確認は未実施。
