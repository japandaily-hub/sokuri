# デザイン見本 v12 の本番展開計画

- 見本: `.agent-state/design-v12-rollout/mockup-v12.html`（正本は `ソクウリ/docs/design_v3_friendly/mockup.html`）
- 作業場所: worktree `C:/Users/ko13h/Claude/Projects/sokuri-design-v12`、ブランチ `claude/design-v12-rollout`（origin/main 14f8662 から）
- 設計: architect（2026-11-19）。下の「決定」はリーダーが既定値として採用したもの。

## 決定（Q1〜Q8）
- Q1 「一括査定」→「一括見積もりに申し込んだら」。「査定」は使わない（public-copy-guard）。
- Q2 古物商許可は「登録の審査で、古物商許可番号と許可証の画像を確認しています。確認が取れない業者は入札できません。」（「取引の前」は書かない）。
- Q3 料金 h2「出品から成約まで、カタヅケの利用料はかかりません。」。行は 出品する／入札を受け取る／お断りする／業者を決める＝0円。「出張・運搬・処分」を含む打消し注記を同じ大きさ・同じ視野に（ガード必須）。
- Q4 案件詳細は順位番号と「1位より X円 低い」を出さない。高い順の並び＋「いちばん高い入札」の印だけ（古物競りあっせん業の論点が未解決）。
- Q5 facts は「業者からの営業電話：選ぶまで、来ません」。
- Q6 LINE ボタンはアイコンなし（現行方針 katazuke.css:184-189 を維持）。白文字/#06c755 のコントラストは現行どおり「ブランドの例外」として注記を引き継ぐ。
- Q7 トップの業者向け区画・モデルケース区画は削る。フッターの /examples・/business は残す。使い方の本文に /examples への文中リンクを1本。
- Q8 案件詳細の「入札の締切」は出さない（API に項目なし）。所在地と StatusBadge を置く。
- --danger は #a8202f（朱と区別）。--green は #166534。

## 1. トークン（変数名は残し値だけ替える。katazuke.css :root）
| 変数 | 新しい値 |
|---|---|
| --primary / -rgb / -d / -l | #2e4a7d / 46,74,125 / #22385f / #6b80a8 |
| --deep / --deep-rgb(新) | #22385f / 34,56,95 |
| --lime | #c3cde0 |
| --navy, --ink | #24221f |
| --body / --body-soft | #37342f / #4f4a43 |
| --head-gray | var(--body-soft) |
| --line / --line-strong(新) / --line-input(新) / --line-soft | #dcd3c4 / #a89d8a / #8a7f6c / #e9e2d5 |
| --white | #fffdf9 |
| --paper(新) / --paper-2(新) | #f6f2ea / #ede6d9 |
| --pale, --pale-2 | var(--paper-2) |
| --indigo-tint(新) | #e3e7ee |
| --marker, --marker-draw | #e3e7ee |
| --warm / --mint / --sky | #f3ead3 / #e4ebdf / #e3e7ee |
| --accent(新) | #b0492a（いちばん高い入札額の数字だけ。業者側画面では使わない） |
| --line-green(新) | #06c755 |
| --green | #166534 |
| --danger / -rgb | #a8202f / 168,32,47（bg-soft・border-soft は追随） |
| --radius / --radius-s | 6px / 4px（影は none のまま） |
| --frame | none（.site-frame の margin 0） |

書体: --maru=var(--font-maru),"Hiragino Maru Gothic ProN",sans-serif ／ --goth=var(--font-goth),"Hiragino Kaku Gothic ProN","Yu Gothic UI","Noto Sans JP",sans-serif ／ --head=var(--maru) ／ --sans=--ui=var(--goth) ／ --num=var(--font-num),"Inter",var(--font-goth),sans-serif ／ --serif=var(--goth)（廃止予定の別名）／ --en=var(--goth) ／ --en-display=var(--num)。

組版: body 17px・line-height 1.85・letter-spacing 0・background var(--paper)・antialiased・font-feature-settings normal。h1〜h5 は weight 700・letter-spacing .02em・line-height 1.5・word-break:auto-phrase・text-wrap:balance。p, li は text-wrap:pretty。::selection は rgba(var(--primary-rgb),.16)。globals.css は触らない（postcss-import 依存）。

Tailwind 橋渡し（tailwind.config.ts）: borderRadius DEFAULT/sm/md/lg/xl/kdz=var(--radius)、kdz-s=var(--radius-s)。colors.brand 50=var(--indigo-tint) 100=#c9d2e1 200=#aebbd3 400/500=var(--primary-l) 600=var(--primary) 700=var(--primary-d) 900=var(--deep)。kdz/navy/ink/pale を var() 参照に。accent 600=var(--green)。fontFamily を var 参照に、num・maru を追加。var 色は `/50` の不透明度が使えない（現状0件）→コメントで禁止。

next/font（layout.tsx）: Noto_Serif_JP/Noto_Sans_JP/Montserrat/Libre_Baskerville を削除。Zen_Maru_Gothic(weight 500,700, subsets latin, swap, --font-maru, preload:false)、Zen_Kaku_Gothic_New(400,500,700, latin, swap, --font-goth, preload:false)、Inter(latin, swap, --font-num)。themeColor と manifest theme_color は #f6f2ea。

## 2. 作業順（1コミット1目的）
- C1a 書体 / C1b 色・角丸・地・Tailwind・themeColor・manifest
- C2 共通部品（.btn/.btn-out/.link/.label/.sec-head/ヘッダー/フッター/Dock/.site-frame/.req/.opt/.btn-line-auth の 99px/.btn-line を単色に/Ui.tsx/ConfirmModal/AuthCard/Logo の英字撤去/SiteHeader/chrome.tsx）
- C3 直書きの掃除（rgba(20,35,92→--deep-rgb、rgba(82,126,82→--primary-rgb、#333→--ink、#1447e0 系、#e8effc、#06c755→--line-green、面の #fff→--white）
- C4 トップ作り直し（page.tsx + top.css の tp- 接頭辞、SiteChrome の BARE から "/" を外す、id は trust/daily/fee/founder、.hero-cta を残す、metadata 不変、写真注記必須、H-4 の本人確認の一文）
- C5 lp/_components・lp.css の削除とガード一覧の修正
- C6 案件詳細（cases/[id]、case-detail.css の cd- 接頭辞、caseProgressStep とテスト、E2E 02 の /入札一覧/→/届いた入札/、ボタン文言「この業者に決める」維持、li 構造維持）
- C7〜C10 4領域の個別作業（business・operator・faq・company・contact・photo-guide・examples・mypage・cases 一覧・create・chat・schedule・signup）。/mypage/identity は触らない（別ブランチで廃止予定）。
- C11 OGP 画像

## 3. 検証
- 各コミット: node --test（src/lib/*.test.mts）、tsc --noEmit、next lint。
- next build は dev と別の場所で（同じ worktree の .next を壊さない）。出力 CSS に --primary:#2e4a7d があること。
- 新ガード design-token-guard.test.mts: #1447e0 #0f37b4 rgba(82,126,82 rgba(20,35,92 Montserrat Libre "Noto Serif" border-radius:99px を CSS/TSX で0件に固定。
- E2E 01/02/04/08/09/10/11。クラス名・文言を変えたら同じコミットで spec を直す。レビュアーと並走させない。
- 375/768/1280 のフルページ写真、scrollWidth、axe のコントラスト。
- 本番 push はユーザー確認後。origin/main 分岐確認→fast-forward→Deployments API で success。
