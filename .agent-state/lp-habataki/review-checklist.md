# /lp 独立レビュー チェックリスト（検証者用・立案文脈は渡さない）

対象: `web/src/app/lp/**`・`web/src/components/kdz/SiteChrome.tsx`（差分1行）。プレビュー: `http://localhost:3100/lp`（起動済み dev サーバー）。
参照仕様: `build-brief.md`（§2 区画対応表・§2.5 構図補足・§3 トークン置換・§4 コピー出典・§7 DoD）、`reference-spec.md`、`shots/`。

## A. 忠実度（参照LP → /lp）— 各項目 ✅/⚠️/❌ と根拠（スクショ名・行番号）
1. 区画の存在と順序: KV → MESSAGE → ABOUT（主色帯） → POINT（撮／選／安＋循環帯） → DAILY（主色帯・01〜09） → FEE → CASES → BIZ → FOOTER。DOM の section 順で照合。
2. 各区画の構図が §2.5 と一致するか（PC 1280 と SP 390 の両方）。特に: KV の中央写真＋右端縦ドット、MESSAGE の段違い 2 枚＋右カラム本文、ABOUT の交互配置 3 item、POINT の大色面＋バッジ＋01 主セル＋小カード 3 枚＋02/03 2 列、DAILY の段違い写真＋番号タグ、FEE の大パネル＋CTA 2 本、CASES の写真左／文右 3 件、BIZ の全幅写真＋2 列＋カード 3 枚。
3. 装飾: 波形上端（帯 5 箇所以上）、テクスチャ、浮遊イラストのコマ送り揺れ（steps(1)）、ドットひし形クラスタ、破線の足跡。
4. モーション: スライダー 6000ms／1600ms、フェードアップ（Reveal up）、MENU 700ms フェード、pagetop の出現。
5. トークン: 主色 #1447e0／`--pale-2`／白。明朝（--serif）・数値は --ui・英字は --en/--en-display。角丸 0・影 0（ドット以外に円形がないか `border-radius` を grep）。
6. クロム: 左上ロゴ・右上 MENU（OPEN/CLOSE 切替）・浮遊 LINE CTA・pagetop・独自フッター。共通 SiteHeader/Dock/額装が出ていないこと。

## B. 品質・a11y・レスポンシブ
1. `npx tsc --noEmit` 0、`npx eslint src/app/lp src/components/kdz/SiteChrome.tsx` 0/0。
2. console error 0（dev）。404 の画像が無いこと（Network / `img.naturalWidth===0` 走査）。
3. 375／390／768／1280／1440 で横スクロールなし（`scrollWidth<=clientWidth`）。
4. 見出し階層（h1 1 つ・h2→h3→h4）。ランドマーク（header/main/nav/footer）。
5. MENU: aria-expanded/aria-controls、Esc、フォーカス復帰、body スクロールロック、アンカーで閉じる。Tab 順で到達可能。
6. スライダー: role=tablist/tab/aria-selected、一時停止ボタン aria-pressed、ホバー／フォーカス／document.hidden で停止、reduced-motion で自動送りなし。
7. `prefers-reduced-motion: reduce` で揺れ・自動送りが止まり、本文が消えない（`html.js-rv` 外で opacity:0 が無いか grep）。
8. 画像: width/height、eager は 1 枚目のみ、装飾 alt=""、意味のある alt は出典どおり。3D レンダーが 112px 未満の枠に無いか。
9. LCP 候補（1 枚目）が lazy になっていないか。CLS を生む未指定寸法が無いか。
10. `100vw`・`!important`・`.lp-page` 外セレクタ・`lp-` 以外の keyframes 名が無いか（grep）。

## C. 法務・コピー・セキュリティ
1. コピーが §4 の出典（page.tsx／model-cases.ts／assure）と**一字一句**一致するか（新規許可＝区画見出し・英字キャプション・ナビラベル・aria-label のみ）。差分は全件列挙。
2. 禁止語（最高／No.1／絶対／実際の／お客様の声／実績／累計／平均／成約率／利用者数／◯日で／必ず／保証）が無いか。新しい約束・期間・効果・統計が増えていないか。
3. `MODEL_CASE_NOTE` がカード群より手前、`MODEL_CASE_CHIP` が各カード先頭（肖像より上）、金額（amount）非表示、`caseName()` 経由の（仮名）表記。
4. `fz-caution`（減額相談の注記）が ¥0 と同一視野・本文サイズ。β手数料の注記が業者向け区画に残っているか。
5. LINE ボタン: タイル aria-hidden・タイル内にアイコンなし・単独導線でない（各所に ghost/テキストリンク併置）。
6. 住所・電話番号・会社名など未確認の事実を新規に書いていないか（書いてよいのは対応 4 都県と「順次拡大」のみ）。
7. セキュリティ: `dangerouslySetInnerHTML` 不使用、外部 URL なし（参照サイトへのリンク・画像参照が残っていないか grep `coco-terrace`）、`target=_blank` に rel、インライン style は CSS 変数のみ、ユーザー入力なし。
8. `robots: { index:false }` が metadata にあるか（プレビュー段階の想定）。

## 出力様式（各レビュアー共通・30 行以内＋詳細はファイル）
- 重大度 Critical / High / Medium / Low で分類。各指摘に「ファイル:行」「期待」「実測」「修正案 1 行」。
- 「問題ゼロ」は不合格。必ず未解決リスク・確認できなかった項目を書く。
- 詳細は `.agent-state/lp-habataki/review-<領域>-r<N>.md` に保存し、戻り値には要約とパスだけ。
