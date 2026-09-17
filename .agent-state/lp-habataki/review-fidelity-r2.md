# /lp 忠実度レビュー r2（独立検査・敵対的・再検証）

検査日: 2026-09-17 / 対象 `http://localhost:3100/lp` / PC 1280x800・SP 390x844（Playwright MCP）
実装スクショ: `.agent-state/lp-habataki/shots-impl-r2/r2-pc-*.png`（20枚）`r2-sp-*.png`（20枚）
基準: `fix-r1.md` A1〜C5 / `review-checklist.md` A節 / `build-brief.md` §2・§2.5・§3 / `reference-spec.md` / `shots/`

**総評: fix-r1 の 21 件中 17 件は実機で確実に直った。垂直リズムは総高 -23% → -6.1% まで回復。一方で「高さを稼いだ手段」が空の色面であり（POINT 色面 794px の中身はバッジのみ、CASES intro 583px の中身は 2 行）、参照の"密度を保ったまま余白が広い"リズムとは質が違う。加えて循環帯のイラストが 6×6px に潰れて帯が空白になっており（新規 High）、浮遊CTA が PC/SP とも本文・見出しを恒常的に覆う（r1 High-1 で pagetop に指摘した現象が CTA で再発）。**

---

## (1) A1〜C5 判定表

凡例: ✅直った ／ △部分的 ／ ❌直っていない ／ ⚠別の問題を生んだ

| # | 指摘 | 判定 | 実測根拠 |
|---|---|---|---|
| A1 | pagetop を footer 内 absolute へ | ✅ | PC: `position:absolute`・親 `FOOTER.lp-footer`(relative)・457×290px(=36.0%)・`bg rgb(20,71,224)`・`PAGE TOP`・`aria-label="ページの先頭へ"`。SP: 118px(30%)×98px・`top:-11px`。`position:fixed` のチップは消滅（全区画で本文への被りなし） |
| A2 | 垂直リズムを参照 −15%〜+10% に | △⚠ | 総高 23,411 / 24,945 = **-6.1%**（r1 -23%）。ただし POINT撮 -15.2%・POINT選 -16.1%・FOOTER -18.0% が帯域外。SP DAILY は逆に -19.6% へ過圧縮。詳細は (2) |
| A3 | KV ドットを右端中央に縦並び | ✅⚠ | `.lp-slider__dots` `flex-direction:column`・親 `.lp-slider__ctrl` が absolute・右余白 PC 45px / SP 31px・一時停止ボタンは直下・SP も縦のまま。⚠新たに `.lp-ill--f1` の真上に重なる（重なり 2,627px²） |
| A4 | MENU オーバーレイのフォーカス閉じ込め | ✅ | 開状態で `inert` が `DIV.lp-float-cta`／`MAIN`／`FOOTER.lp-footer` に付与。Tab 19 回: NAV 内 14 → header の CLOSE → **NAV:トップ へ循環**。Shift+Tab 3 回とも NAV 内。Esc で `aria-expanded=false`・フォーカスは MENU ボタンへ復帰・`inert` 全解除・`body overflow:visible` 復帰 |
| A5 | footer を main の外へ | ✅ | `.lp-page` 直下 = `HEADER.lp-header` / `DIV.lp-float-cta` / `NAV.lp-menu` / `MAIN` / `FOOTER.lp-footer`。header は `div` でなく `<header>` |
| A6 | SP でも浮遊CTAの代替導線 | ✅⚠ | SP で `.lp-float-cta__alt` `display:block`・幅 208px（LINE タイルと同一）・11px・白地・「よくある質問を見る」。⚠CTA 塊が高くなった結果、SP の本文を覆う（(4) H2） |
| A7 | 引き取り可否の注記を追加 | ✅ | `.lp-about__note` に 2 行とも存在・`font-size:15px`・`color:rgb(255,255,255)`。文言は `page.tsx:344` と一致 |
| B1 | ABOUT 強調語を白＋白32%マーカー | ✅ | `em`: `color:rgb(255,255,255)` / `linear-gradient(rgba(0,0,0,0) 68%, rgba(255,255,255,.32) 68%)`。`--lime`・黄は不使用 |
| B2 | 循環帯を主色帯＋白タイル6点 | ❌⚠ | 地 `rgb(20,71,224)` ✅・見出し「顧客・業者・社会の三者に喜びと安心を。」✅・英字 `three-way satisfaction` ✅・タイル 6 枚 100×100 白 ✅・`aria-hidden` ✅。**しかしタイル内 `img` の描画サイズが 6×6px（`naturalWidth 480`＝画像は正常）**。イラストが事実上不可視で、1,064px の帯がほぼ無地の青。(4) H1 参照 |
| B3 | CASES に intro/outro 帯＋大キャッチ | ✅ | `.lp-cases__intro` `rgb(225,245,253)` 583px（h2＋極小英字）→ `.lp-cases__main` 2,412px（`.lp-cases__catch` 36px・2 行目 `rgb(20,71,224)`＋本文＋`MODEL_CASE_NOTE`＋カード3）→ `.lp-cases__outro` `rgb(225,245,253)` 420px。`lp-wave--sky` 追加済。`MODEL_CASE_NOTE` はカード群より手前 ✅ |
| B4 | POINT 色面 `min(54vw,640px)`／バッジ位置 | △⚠ | 色面 584×**794px**（指示値 640px に対し +24%）。バッジ左オフセット **265px**（指示 `clamp(24px,18%,220px)`=105px）、上 17.5%（指示 15%）。⚠色面内にバッジ以外の要素なし＝約 670px の空色面 |
| B5 | FOOTER の地を `--pale-2` | ✅ | `rgb(244,247,252)` |
| B6 | SP KV `100svh`／浮遊ill／`sp-br` | ✅ | `min-height:844px`・実高 844px。`.lp-ill--f1/f2` は SP で一部 `display:none`、残りの最大 right=366 < 380。`.lp-kv .sp-br` 存在 |
| B7 | 非活性スライドに `aria-hidden` | ✅ | 6 枚中 5 枚に `aria-hidden="true"`、ドットに `aria-selected`（活性のみ true）＋`aria-label="N枚目の写真を表示"` |
| B8 | コピーの是正（4件） | ✅ | h2「あなたがするのは、「撮る」と「選ぶ」だけ」／CTA sub「登録・査定・お断りまで無料」／`.lp-biz__req`「古物商許可が必要」復活／カード本文はタグ文言のみ・リード側に全文（重複 2 組 解消）／`.lp-biz__note` 15px・カード群直前 |
| B9 | robots Disallow ／ canonical | ✅ | `robots.ts:19` `disallow:["/analyzing","/condition","/result","/lp"]`。`link[rel=canonical]="https://sokuri.vercel.app/lp"`、`meta[robots]="noindex, nofollow"` |
| C1 | 画像の width/height 実寸 | ✅ | `top-handover.webp` / `top-founder-desk.webp` とも属性 1536×1024、`naturalWidth/Height` 一致 |
| C2 | MESSAGE 二重の丘＋左2枚を写真に | ✅ | `.lp-message` 内に `.lp-wave--white` ×2（片方 `--back`）。画像 `top-scene-jikka.webp`(alt="") ／ `top-hero-couple-60s.webp`(alt=出典どおり) |
| C3 | DAILY 写真 3 サイズ＋破線 4〜6本 | ✅ | PC 幅 565/368/270px（44.5%/29%/21%、指示 46/33/26）。ページ全体の `dashed` 要素 **9**（r1 は 3）。SP は 344 / 164×2（小は 2 列） |
| C4 | 署名後半の復活／metadata.description | ✅ | 「顧客にも業者にも、社会にも。三方よしの場所をつくります。」存在。description は `layout.tsx` 文言（「あなたが」なし） |
| C5 | SP で `.lp-ill--f1/f2` が画面外 | ✅ | 375 / 768 / 1440 いずれも `clientWidth` を超える要素 **0 個**（r1 は 4 個が overflow で吸収されていた） |

**集計: ✅ 17 件 ／ △ 2 件（A2・B4）／ ❌ 1 件（B2）／ そのうち ⚠「別の問題を生んだ」 4 件（A2・A3・A6・B4）。**

---

## (2) 区画高さ表（PC 1280・単位 px）

| 区画 | 参照 | r1 | r2 | r2 の乖離 | 判定（−15%〜+10%） |
|---|---|---|---|---|---|
| KV `.lp-kv` | 900 | 1105 | **975** | +8.3% | ✅ |
| MESSAGE `.lp-message` | 976 | 650 | **950** | -2.7% | ✅ |
| ABOUT `#about` | 2829 | 1998 | **2506** | -11.4% | ✅ |
| POINT 撮 `--primary` | 2922 | 1716 | **2479** | -15.2% | ❌（僅差で帯域外） |
| POINT 選 `--deep` | 2520 | 1687 | **2115** | -16.1% | ❌ |
| POINT 安 `--pale` | 1566 | 1718 | **1670** | +6.6% | ✅ |
| 循環帯 `.lp-cycle` | 478※ / 1566※ | 834 | **1064** | +123% / -32% | ❌（基準値が資料間で不一致・(5) 参照） |
| DAILY `#daily` | 2926 | 2998 | **3122** | +6.7% | ✅ |
| FEE `#fee` | 2635 | 1618 | **2316** | -12.1% | ✅ |
| CASES `#cases` | 3775 | 2322 | **3416** | -9.5% | ✅ |
| BIZ `#biz` | 2447 | 2023 | **2112** | -13.7% | ✅ |
| FOOTER `.lp-footer` | 838 | 472 | **687** | -18.0% | ❌ |
| **総高** | 24945 | 19141 | **23411** | **-6.1%** | ✅ |

※ `reference-spec.md:198` は `.home-point__item__business` を 478px とし、`review-fidelity-r1.md:45` は同区画を 1566px とする。両者が食い違うため判定不能。

### SP（390）参考

| 区画 | 参照 | r1 | r2 | 乖離 |
|---|---|---|---|---|
| KV | 828 | 682 | **844** | +1.9% ✅ |
| MESSAGE | 1049 | ─ | **1022** | -2.6% ✅ |
| ABOUT | 2609 | ─ | **2041** | -21.8% ❌ |
| POINT 全体 | 7928 | ─ | **6966** | -12.1% ✅ |
| DAILY | 3257 | 4163 | **2617** | **-19.6%**（A2 の「3300 前後」を通り越して過圧縮）❌ |
| FEE / CASES / BIZ / FOOTER | 参照値なし | ─ | 1391 / 3196 / 2231 / 842 | ─ |
| 総高 | 24135 | ─ | **21148** | -12.4% |

---

## (3) 回帰チェック表（r1 で ✅ だった項目）

| 項目 | r1 | r2 実測 | 判定 |
|---|---|---|---|
| 波形の高さ（PC） | 230×6 / 72 / 90 | `lp-wave` 14 枚: 230×11・72（FEE 下端）・128（FOOTER 上端） | ✅ 維持（230/72 は参照どおり。footer 上端が 90→128 に変化したが参照値未定義） |
| 揺れの keyframes | `lp-sway/lp-sway2/lp-float/lp-float2` のみ | 同 4 種のみ。稼働アニメーション 22〜24・全て `running` | ✅ 維持 |
| 角丸 0 | 非 0 は `.lp-slider__dot` 6 個(50%)のみ | 完全同一（6 個・すべて dot） | ✅ 維持 |
| MENU オーバーレイ | 忠実・Esc 復帰 | Esc 復帰に加え `inert` とタブ循環も成立 | ✅ 改善 |
| 打消し表示の位置 | `MODEL_CASE_NOTE` がカード群より手前 | `.lp-cases__main` 冒頭・カード 3 件より上に描画（`r2-pc-15`） | ✅ 維持 |
| 横スクロール無し | 390 で `sw===cw` | 375(365/365)・390(380/380)・768(758/758)・1280(1270/1270)・1440(1430/1430) いずれも一致、はみ出し要素 0 個 | ✅ 改善（脆さも解消） |
| コンソール | 未確認 | error 0 / warning 0 | ✅ |
| 画像 | 36 src すべて 200 | `img` 54 枚、`naturalWidth===0` の破損 0 枚 | ✅ |
| スライダー自動送り | 未計測 | 7 秒待機で活性スライド index 3 → 4、`aria-selected` も移動。一時停止ボタン `aria-pressed="false"`・`aria-label="写真の自動切り替えを一時停止"` | ✅ 新規に確認 |

---

## (4) 新規指摘

### High

**H1. 循環帯のイラスト 6 点が 6×6px に潰れ、帯が無地の青になっている**
- ファイル: `web/src/app/lp/lp.css:936-939`（`.lp-page .lp-cycle .ill-item { background:#fff; padding: 9%; }`）／描画側 `web/src/app/katazuke-motion.css:147-148`
- 期待: 100×100 の白タイルの中にイラストが 9% の内余白を空けて収まる（fix-r1 B-2）
- 実測: タイル 100×100・`img` の描画サイズ **6×6px**（`naturalWidth 480`＝ファイルは正常取得）。`r2-pc-09-cycle.png` では 1,064px の青帯に空の淡色四角が 2 つ見えるだけ
- 原因: `.ill-item` の `padding: 9%` は**タイル幅ではなく包含ブロック `.ill-loop-inner`（520px）を基準**に解決され、上下左右 46.8px となる。`box-sizing:border-box` により内容ボックスが 100−93.6=6.4px に潰れ、`.ill-item img{width:100%;height:100%}` がそれに従う
- 修正案: `padding: 9%` → `padding: 9px`（または `padding: clamp(6px,0.9vw,10px)`）

**H2. 浮遊CTA（`position:fixed`）が PC・SP とも本文と見出しを恒常的に覆う**
- セレクタ: `.lp-float-cta`（PC 235×102 @ 右上／SP 208×85 @ 右下、ビューポートの約 5%）
- 期待: 常時表示の導線が本文の可読性を壊さない（r1 High-1 で pagetop に対して同じ指摘を出し、pagetop は是正済み）
- 実測（重なり面積）: PC — `h2「入札のしくみ」` 9,071px² ／ `.lp-daily__cap`「成立後に連絡先を開示し…」5,349px² ／ CASES の写真 10,072px²。さらに `r2-pc-15` では CASES カードの「詳しく見る →」ボタンと `.lp-float-cta__alt` タイルが重なる。SP — `#biz`「一括出品への入札で、効率的な仕入れルートを…」11,400px²、「顧客と業者、双方に無駄がない。」2,134px²、β注記 2,583px²、`#cases` の h2 7,295px²
- 補足: A-6 で SP の `__alt` を常時表示にした結果、SP の固定塊が高くなり被りが増えた
- 修正案: 区画に入ったら CTA を `opacity:.15` まで退避するか、PC は `top` を下げ、SP は `.lp-cases`/`.lp-biz` の下端余白を CTA 高さ分確保する

### Medium

**M1. POINT の色面 794px の中身がバッジ 1 枚だけ（約 670px の空色面）**
- セレクタ: `.lp-point__plate`（584×794）／`r2-pc-05-point-shoot.png`
- 期待: 参照の色面は見出し・写真の背面に敷かれる面。fix-r1 B-4 の指示値は `height:min(54vw,640px)`
- 実測: 高さ 794px（指示比 +24%）。色面の矩形内に収まる要素は `.lp-point__badge` とその子のみ。A-2 の高さ回復分のかなりが無地の色面
- 修正案: `height:min(54vw,640px)` に戻し、`01` 主セル（見出し＋写真）の上端を色面に食い込ませて高さを"中身"で作る

**M2. CASES intro 帯 583px に対し中身が 2 行のみ**
- セレクタ: `.lp-cases__intro`（`rgb(225,245,253)` 583px、内側テキストは `usage images` と `こんなふうに使えます` の 2 つだけ）／`r2-pc-14-cases-intro.png`
- 期待: fix-r1 B-3 の「高 450px 前後」
- 実測: 583px（+30%）、うち約 400px が空
- 修正案: `padding-block` を詰めて 450px 前後に戻す

**M3. KV の浮遊イラストが新しいドット列・浮遊CTAと衝突**
- セレクタ: `.lp-kv .lp-ill--f1`（rect 1148,555–1256,663）× `.lp-slider__ctrl` = 2,627px² ／ `.lp-ill--f2`（1126,151–1222,247）× `.lp-float-cta` = 9,065px²
- 期待: 装飾は操作系・CTA の背後で潰れない
- 実測: `r2-pc-01-kv.png` で家のイラストがドット列の直下に、箱のイラストが CTA タイルの裏に隠れる。A-3 でドットを右端へ寄せた副作用
- 修正案: PC で `.lp-ill--f1/f2` の `right` を +120px 内側へ、または KV の右 90px を装飾禁止帯にする

**M4. 帯域外に残る区画高さ（POINT撮 -15.2% / POINT選 -16.1% / FOOTER -18.0%）**
- 期待: fix-r1 A-2 の −15%〜+10%
- 修正案: FOOTER は `padding-block` を +150px、POINT 2 ブロックは主セル間の `margin` を +10%

**M5. SP の縦バランスが今度は逆方向に振れた（DAILY -19.6%・ABOUT -21.8%）**
- 期待: SP DAILY は「3300px 前後」（fix-r1 A-2）
- 実測: 2,617px。ABOUT も 2,041px（参照 2,609）
- 修正案: SP の `.lp-daily__item` 下マージンを +24px、`#about` の item 間を +40px

### Low

- **L1** ABOUT にマーカーが 2 系統（`em` = `#fff` + 白32% ／ `span.lp-mk` = `rgba(255,255,255,.86)` + 白30%）。同一帯で強調の強さが揃わない。→ `.lp-mk` を `em` と同値に
- **L2** ドット列の右余白 45px（指示 24px）、縦位置が KV 中央より 54px 下（ドット＋一時停止ボタンの塊を中央寄せしているため）。→ `.lp-slider__ctrl{right:24px}`・ドット列だけを中央基準に
- **L3** MENU 開状態で header のロゴリンク `A:カタヅケKATAZUKE` に `inert` が付かない。Tab 19 回では到達しなかったが、支援技術・クリックからは到達可能。→ ロゴを `inert` 対象に含めるか header 内で CLOSE ボタンのみ除外
- **L4** footer ナビ「特定商取引法に基づく表記」が 2 行に折り返し、隣列と行頭が揃わない（`r2-pc-19-footer.png`）。→ 列幅を +40px

---

## (5) 確認できなかった項目（未解決リスク）

1. **`prefers-reduced-motion: reduce` の実挙動**。ツール側でメディア特性をエミュレートできないため未検証。記録できたのは `document.getAnimations()` = 22〜24 件・`playState` は全て `running`・`.lp-ill*` の `animation-play-state` も `running` のみ。reduce 時に揺れと自動送りが止まり本文が消えないことは**依然として未実証**。
2. **循環帯 `.lp-cycle` の目標高さが資料間で矛盾**（`reference-spec.md:198` 478px vs `review-fidelity-r1.md:45` 1566px）。どちらを採るかで実測 1,064px は +123% にも -32% にもなる。リーダーによる基準の確定が必要。
3. **SP の参照高さは KV(828)・MESSAGE(1049)・ABOUT(2609)・POINT(7928)・総高(24135) しか資料に無い**。FEE / CASES / BIZ / FOOTER の SP 判定は実測値の記録のみ。
4. **揺れの `steps(1)` timing と秒数**は r1 の実測を引用しており、r2 では keyframes 名と稼働数のみ再確認した。
5. **KV が参照の"全画面フルブリード写真スライダー"ではなく中央 3:2 の額縁のまま**（r1 §1 の指摘）。fix-r1 に是正項目が無いため本周では判定対象外としたが、参照との最大の構図差として残っている。
6. `npx tsc --noEmit` / `npx eslint` は未実行（B 節担当範囲）。
7. ホバー状態（`opacity:.8/.85`）、スクリーンリーダー読み上げ、コピーの機械的 diff（一字一句照合）は未実施。
8. `.lp-cycle` のイラストが正しいサイズで描画されたときの帯の見え方（H1 修正後の再検査が必要）。
