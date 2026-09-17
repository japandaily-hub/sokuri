# /lp 修正指示 r2（リーダー裁定・2026-09-17）

入力: `review-fidelity-r2.md`（21件中17件✅・B2❌・A2/B4△・新規High 2）＋ `review-qa-legal-r2.md`（到着後に §C を追記）。編集可能範囲は r1 と同じ（`web/src/app/lp/**`・`SiteChrome.tsx`・`robots.ts`）。

## A. High（必須）
1. **循環帯のイラストが 6px に潰れている**（fidelity 新規H1）: `lp.css` の `.lp-cycle .ill-item{padding:9%}` が包含ブロック基準で解決され内容ボックスが消えている。`padding:10px` の固定値にし、タイル 1 枚あたり `width:clamp(72px,9vw,110px)` を明示。修正後、6 点すべてが白タイルの中に見えること（`img.getBoundingClientRect().width >= 50`）。
2. **浮遊CTAが本文を恒常的に覆う**（fidelity 新規H2・r1 High-1 の再発形）。**PC（≥860px）は右端の余白内に収まる「縦タブ」に変える**: 幅 60px・高さ約 220px・`right:0; top:160px`・主色でなく LINE 緑地（`.btn.btn-line` の作法を保ち、タイルは上端 12px の帯・ラベルは `writing-mode:vertical-rl` の白文字「LINEではじめる」・sub は出さない）。代替導線「よくある質問」は縦タブ直下に白地 60px 幅・`writing-mode:vertical-rl` 11px。1280px では container（1140px）の右余白 70px に収まるため本文と重ならない。**SP（≤859px）は既存サイトの Dock と同じ「画面下の全幅バー」**（高さ 56px＋safe-area、白地・上 1px 罫）に LINE ボタン（flex:1）と「よくある質問」テキストリンク（右・11px）を横並び。`main` に `padding-bottom:calc(56px + env(safe-area-inset-bottom))` を付けて末尾が隠れないようにする。MENU オーバーレイが開いている間は非表示。
3. **KV を参照どおりフルブリード写真スライダーに**（fidelity「最大の構図差」・リーダー裁定で採用）: スライドの `<img>` を `.lp-kv` 全面（`position:absolute;inset:0;object-fit:cover;object-position:50% 60%`）に敷き、`.lp-kv{min-height:clamp(640px,100svh,900px)}`。h1・英字キャプション・sub は写真の上に置き、可読性のため **上部だけ淡色のグラデ veil**（`linear-gradient(180deg, rgba(244,247,252,.96) 0 38%, rgba(244,247,252,0) 70%)`）を写真の上・文字の下に敷く（文字色は `--ink`/主色のまま）。中央の 3:2 額縁と `.lp-kv__stage` の白地は撤去。浮遊イラスト 6 点は四隅寄り（h1 と写真の主題に重ねない）、ドットひし形 4 点は veil 上に。ドット列は右端縦（現状維持）。下端の白波形は維持。SP も同じ（veil 45% まで）。1 枚目 eager のまま。

## B. Medium（必須）
1. **POINT の色面が空**（fidelity M）: 色面高さを `min(46vw,520px)` に戻し、**ブロック見出し h2（白文字）を色面の中・バッジの右に置く**（左 `clamp(24px,10%,120px)`・縦中央）。色面の下の h2 は削除（重複させない）。バッジの左オフセットは `clamp(24px,10%,120px)`。3 ブロック共通。`--deep` 面・`--pale` 面の見出し色はそれぞれ白／`--ink`。
2. **CASES intro 帯**: 高さ 448px（参照 44.8rem）に詰め、h2 の下に極小英字を置くだけ（中身は増やさない）。
3. **KV の `.lp-ill--f1/f2` がドット列・CTA と衝突**（fidelity M）: A-3 の再配置で解消し、`right` は 60px 以上に。
4. 区画高さの残差（fidelity 表）: POINT 撮 −15.2%・選 −16.1% は B-1 の色面変更後に `--lp-block-gap` を +24px、FOOTER −18% は `padding-block` を +40px。**SP の ABOUT −21.8%／DAILY −19.6%** は item 間 margin を +24px（SP のみ）。他は据置き。

## C. QA・法務 r2 の指摘（`review-qa-legal-r2.md`・必須）
1. **H-1** `.lp-band__head .lp-en{color:var(--lime)}` → 主色帯上で 3.32:1（11px）。ABOUT／DAILY／循環帯の 3 箇所を `color:rgba(255,255,255,.92)` に。`--lime` は主色帯では使わない（`--deep` 面専用）。
2. **M-1** `.lp-about__body .lp-en` の `rgba(255,255,255,.72)` → `.80` 以上。
3. **M-2** KV ドット列: A-3 でフルブリード化するため「ビューポート右端 24px」で確定。lp.css と LpSlider.tsx のコメント（「基準は .lp-kv」）を実装に合わせて訂正。
4. **M-3** `.lp-footer{overflow:hidden}` が pagetop の `top:-11px` とフォーカスリングを切る → `overflow:clip; overflow-clip-margin:16px`。
5. Low（対応する）: スライダーの `role=tab` に `aria-controls`（対応するスライドに id）／ドット上ホバーでも自動送り停止／メニュー内アンカーで閉じた時にフォーカスをアンカー先の見出し（`tabIndex=-1`）へ移す／CASES の見出し重複（intro 帯 h2 と本文側の同文）は本文側を `p.lp-cases__catch` だけにする／β注記の重複（リード p 内の「※ サービス開始当初…」とカード群直前の `.lp-biz__note`）は `.lp-biz__note` 側だけ残しリード側の同文を削る（リード p は出典 `.biz-banner-copy p` の 3 文のうち前 2 文＝`<br />` 区切りの文単位で可）。
6. Low（据置き・理由）: `inert` を付けたロゴはオーバーレイ下で不可視のため妥当／robots の `/lp` 前方一致は `/lp` 以外に該当ルートが無いため可／英字のみの region 名は `aria-label` を和文に（`aria-labelledby` で見出し参照に変えてよい）。

## D. 却下・据置き
- 循環帯の目標高さの資料矛盾（478 vs 1566）: 参照 `.home-point__item__business` は 478px。本帯は 6 タイル＋見出しで 600〜700px を目標とし、それ以上は伸ばさない。
- `prefers-reduced-motion` の実挙動: CSS の `animation:none`／自動送り停止の実装をコードで確認済み（qa r1）。リーダーが最終確認する。

## 完了条件
- `npx tsc --noEmit` 0／`npx eslint src/app/lp src/components/kdz/SiteChrome.tsx src/app/robots.ts` 0/0。
- 戻り値（30 行以内）: 対応番号一覧、未対応の番号と理由、変更ファイル一覧、KV の新構造（DOM 順）1 行。
