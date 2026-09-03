# カタヅケ → 人の森デザイン移行 棚卸し表

調査対象: `web/src/` 配下の全 `.css`・`.tsx`（`katazuke.css`／`katazuke-pages.css` は §A のみ対象外）。
仕様書: `docs/design_hitonomori_alignment/SPEC.md` §2.4／§2.5。
断定調・実測値。編集は未実施（本ファイルは調査結果のみ）。

---

## A. CSS ファイル別棚卸し（31ファイル、`katazuke.css`・`katazuke-pages.css` 除外）

色分類は HSL 色相による機械判定（青系=hue 170–250°かつ明度0.35以上／紺系=hue 200–250°かつ明度0.35未満／その他=上記以外の有彩色＋白・グレー等無彩色）。**「暖色グレー系」は現行コードに実在せず0件** — 現行は「ブランドブルー＋白」基調で、苔色系の暖かみグレーは新規トークンとして導入が必要という意味。border-radius は明示px値が6px以上のもののみ（`var(--radius)`等トークン参照は除外＝再置換不要のため非計上）。

| ファイル | 行数 | 色 計(青/紺/他) | radius≥6px | box-shadow | translateY(-) | backdrop-filter | font-family直書き | font-weight 700+ | 置換対象合計 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| app/business/business.css | 411 | 32(青11/紺0/他21) | 3 | 12 | 3 | 0 | 5 | 8 | 63 |
| app/chat/[id]/chat.css | 420 | 27(青4/紺0/他23) | 10 | 0 | 0 | 0 | 11 | 13 | 61 |
| app/company/company.css | 283 | 14(青6/紺0/他8) | 3 | 3 | 0 | 0 | 9 | 9 | 38 |
| app/contact/contact.css | 265 | 14(青7/紺0/他7) | 1 | 6 | 2 | 0 | 5 | 5 | 33 |
| app/create/complete/complete.css | 300 | 16(青1/紺0/他15) | 3 | 0 | 0 | 0 | 5 | 11 | 35 |
| app/create/create.css | 137 | 21(青4/紺0/他17) | 8 | 4 | 0 | 0 | 7 | 12 | 52 |
| app/examples/examples.css | 322 | 13(青5/紺0/他8) | 5 | 2 | 0 | 0 | 7 | 13 | 40 |
| app/faq/faq.css | 404 | 14(青5/紺0/他9) | 4 | 4 | 2 | 0 | 6 | 6 | 36 |
| app/globals.css | 174 | 14(青8/紺0/他6) | 1 | 0 | 0 | 0 | 0 | 0 | 15 |
| app/legal/legal.css | 154 | 3(青0/紺0/他3) | 0 | 0 | 0 | 0 | 2 | 5 | 10 |
| app/mypage/mypage.css | 673 | 27(青8/紺0/他19) | 5 | 1 | 0 | 0 | 9 | 15 | 57 |
| app/mypage/profile/profile.css | 376 | 22(青1/紺2/他19) | 5 | 4 | 0 | 1 | 6 | 11 | 49 |
| app/mypage/withdraw/withdraw.css | 311 | 21(青3/紺0/他18) | 4 | 2 | 1 | 0 | 4 | 5 | 37 |
| app/not-found.css | 222 | 3(青2/紺0/他1) | 3 | 2 | 2 | 0 | 3 | 4 | 17 |
| app/notifications/notifications.css | 230 | 23(青3/紺2/他18) | 11 | 7 | 2 | 1 | 6 | 11 | 61 |
| app/operator/chat/[id]/chat.css | 520 | 33(青7/紺1/他25) | 15 | 0 | 0 | 0 | 12 | 19 | 79 |
| app/operator/dashboard.css | 438 | 38(青8/紺2/他28) | 15 | 3 | 1 | 1 | 17 | 20 | 95 |
| app/operator/operator-auth.css | 51 | 1(青1/紺0/他0) | 1 | 0 | 0 | 0 | 0 | 2 | 4 |
| app/operator/operator-shared.css | 442 | 45(青13/紺2/他30) | 11 | 8 | 1 | 1 | 17 | 19 | 102 |
| app/operator/profile/profile.css | 879 | 59(青11/紺1/他47) | 19 | 5 | 1 | 1 | 12 | 22 | 119 |
| app/password-reset/password-reset.css | 165 | 11(青5/紺0/他6) | 1 | 3 | 0 | 0 | 2 | 4 | 21 |
| app/photo-guide/photo-guide.css | 275 | 21(青6/紺0/他15) | 5 | 1 | 0 | 0 | 2 | 7 | 36 |
| app/privacy/privacy.css | 84 | 1(青0/紺0/他1) | 0 | 0 | 0 | 0 | 0 | 2 | 3 |
| app/review/review.css | 180 | 20(青5/紺0/他15) | 4 | 7 | 1 | 0 | 9 | 10 | 51 |
| app/schedule/schedule.css | 442 | 29(青5/紺0/他24) | 2 | 0 | 1 | 0 | 11 | 16 | 59 |
| app/signup/signup.css | 38 | 4(青0/紺0/他4) | 2 | 2 | 0 | 0 | 2 | 2 | 12 |
| app/terms/terms.css | 56 | 4(青0/紺0/他4) | 0 | 0 | 0 | 0 | 1 | 2 | 7 |
| app/unsubscribe/unsubscribe.css | 50 | 1(青0/紺0/他1) | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| app/vendors/[id]/vendor.css | 336 | 21(青9/紺1/他11) | 9 | 4 | 0 | 1 | 13 | 18 | 66 |
| app/verify-email/verify-email.css | 190 | 9(青7/紺0/他2) | 2 | 1 | 1 | 0 | 4 | 5 | 22 |
| components/kdz/operator-header.css | 153 | 7(青1/紺0/他6) | 6 | 2 | 0 | 1 | 1 | 5 | 22 |
| **合計** | **8,510** | **568(青147/紺12/他409)** | **135** | **72** | **15** | **6** | **190** | **262** | **1,303** |

### 頻出ハードコード値トップ（横断複製の実例。同一値が複数ファイルに複製されている）
- `#fff`: **194箇所**（最頻出。単独最大の置換対象。ほぼ全31ファイルに分散）
- `rgba(31, 84, 222, *)`（ブランドブルー、表記ゆれ含む: スペース有無・小数点0省略）: **37箇所**（business/mypage/operator系に集中）
- `#f4f6fb`: 20箇所（chat系背景で複製） / `#fafbfe`: 15箇所 / `#e05c5c`（エラー赤）: 16箇所
- `#d1fae5`・`#86efac`（success系グリーン）: 13/10箇所 — operator-shared.css・profile.css に複製
- `#b8c8f0`: 10箇所（operator/profile.css 中心）
- `border-radius: 99px` 58件・`999px` 10件・`9999px` 1件（ピル型、角丸0への影響大）／`border-radius: 50%` 53件（円形要素、対象外判断が必要）／`var(--radius)` 48件・`var(--radius-s)` 40件（トークン化済み、**値自体の再定義で一括対応可能** — これが最優先の低コスト施策）

---

## B. TSX ファイル別棚卸し（Tailwind/インラインカラー、マッチ0件のファイルは非掲載・全75ファイル走査済み）

| ファイル | inline style色 | bg/text-brand-* | bg/text-kdz-* | rounded-{2xl,3xl,xl,full} | shadow-* | font-{black,bold,head} | 合計 |
|---|---:|---:|---:|---:|---:|---:|---:|
| app/admin/page.tsx | 0 | 3 | 0 | 3 | 1 | 9 | 16 |
| app/applications/page.tsx | 0 | 2 | 0 | 0 | 0 | 0 | 2 |
| app/business/page.tsx | 1 | 0 | 0 | 0 | 0 | 0 | 1 |
| app/cases/[id]/page.tsx | 0 | 5 | 0 | 8 | 0 | 8 | 21 |
| app/cases/page.tsx | 0 | 2 | 0 | 2 | 1 | 1 | 6 |
| app/chat/[id]/page.tsx | 5 | 0 | 0 | 0 | 0 | 0 | 5 |
| app/error.tsx | 1 | 0 | 0 | 0 | 0 | 0 | 1 |
| app/faq/page.tsx | 3 | 0 | 0 | 0 | 0 | 0 | 3 |
| app/layout.tsx | 0 | 1 | 0 | 0 | 0 | 0 | 1 |
| app/legal/page.tsx | 1 | 0 | 0 | 0 | 0 | 0 | 1 |
| app/mypage/page.tsx | 2 | 1 | 0 | 0 | 0 | 0 | 3 |
| app/mypage/profile/page.tsx | 4 | 0 | 0 | 0 | 0 | 0 | 4 |
| app/mypage/withdraw/page.tsx | 2 | 0 | 0 | 0 | 0 | 0 | 2 |
| app/not-found.tsx | 2 | 0 | 0 | 0 | 0 | 0 | 2 |
| app/notifications/page.tsx | 0 | 1 | 0 | 0 | 0 | 0 | 1 |
| app/opengraph-image.tsx | 1 | 0 | 0 | 0 | 0 | 0 | 1 |
| app/operator/cases/[id]/page.tsx | 3 | 2 | 0 | 0 | 0 | 0 | 5 |
| app/operator/cases/page.tsx | 1 | 1 | 0 | 0 | 0 | 0 | 2 |
| app/operator/chat/[id]/page.tsx | 5 | 0 | 0 | 0 | 0 | 0 | 5 |
| app/operator/page.tsx | 0 | 1 | 0 | 0 | 0 | 0 | 1 |
| app/operator/profile/page.tsx | 3 | 0 | 0 | 0 | 0 | 0 | 3 |
| app/operator/signup/page.tsx | 1 | 0 | 0 | 0 | 0 | 0 | 1 |
| app/operator/transactions/[id]/page.tsx | 12 | 1 | 0 | 0 | 0 | 0 | 13 |
| app/operator/transactions/page.tsx | 1 | 1 | 0 | 0 | 0 | 0 | 2 |
| app/page.tsx | 3 | 0 | 0 | 0 | 0 | 0 | 3 |
| app/password-reset/page.tsx | 3 | 0 | 0 | 0 | 0 | 0 | 3 |
| app/result/page.tsx | 0 | 2 | 0 | 0 | 0 | 0 | 2 |
| app/review/page.tsx | 2 | 2 | 0 | 0 | 0 | 0 | 4 |
| app/schedule/page.tsx | 7 | 0 | 0 | 0 | 0 | 0 | 7 |
| app/signup/page.tsx | 9 | 0 | 0 | 0 | 0 | 0 | 9 |
| app/unsubscribe/page.tsx | 2 | 0 | 0 | 0 | 0 | 0 | 2 |
| app/vendors/[id]/page.tsx | 4 | 1 | 0 | 0 | 0 | 0 | 5 |
| components/AuthCard.tsx | 0 | 1 | 0 | 3 | 1 | 1 | 6 |
| components/ChannelCard.tsx | 0 | 4 | 0 | 6 | 3 | 4 | 17 |
| components/ConditionCard.tsx | 0 | 3 | 0 | 4 | 1 | 1 | 9 |
| components/DefectUploader.tsx | 0 | 0 | 0 | 7 | 2 | 1 | 10 |
| components/Icon.tsx | 0 | 0 | 0 | 0 | 1 | 0 | 1 |
| components/PhotoGuide.tsx | 0 | 4 | 0 | 3 | 0 | 1 | 8 |
| components/Stepper.tsx | 0 | 5 | 0 | 3 | 0 | 1 | 9 |
| components/kdz/AppHeader.tsx | 2 | 0 | 1 | 0 | 0 | 0 | 3 |
| components/kdz/AppHeaderLogout.tsx | 0 | 0 | 1 | 0 | 0 | 0 | 1 |
| components/kdz/DisclosureNotice.tsx | 1 | 0 | 0 | 0 | 0 | 0 | 1 |
| components/kdz/HeaderNav.tsx | 0 | 3 | 0 | 1 | 1 | 0 | 5 |
| components/kdz/SiteHeader.tsx | 0 | 0 | 1 | 0 | 0 | 0 | 1 |
| components/kdz/Ui.tsx | 0 | 6 | 0 | 10 | 1 | 2 | 19 |
| components/landing/Comparison.tsx | 0 | 4 | 0 | 4 | 0 | 2 | 10 |
| components/landing/Faq.tsx | 0 | 3 | 0 | 2 | 1 | 1 | 7 |
| components/landing/Features.tsx | 0 | 2 | 0 | 2 | 2 | 3 | 9 |
| components/landing/ServiceIntro.tsx | 0 | 3 | 0 | 5 | 2 | 3 | 13 |
| components/landing/TrustStrip.tsx | 0 | 2 | 0 | 2 | 0 | 1 | 5 |
| **合計（マッチ0件ファイル除く）** | **75** | **59** | **3** | **60** | **17** | **38** | **271** |

### 特殊4ファイルの色指定（`apple-icon.tsx`／`opengraph-image.tsx`／`manifest.ts`／`layout.tsx`）
- `apple-icon.tsx:21` `linear-gradient(135deg, #1447e0 0%, #122a6b 100%)` ／ `:22` `#ffffff`
- `opengraph-image.tsx:27` `linear-gradient(135deg, #1447e0 0%, #122a6b 60%, #141f48 100%)` ／`:28,85` `#ffffff` ／`:96` `#a7f3d0` ／`:108` `#cbd5e1` ／`:46,62,117,118,127,128,137,138,147,148` `rgba(255,255,255,*)` 各種
- `manifest.ts:22` `background_color: "#f8fafc"` ／`:23` `theme_color: "#1447e0"`（PWA表示色。ホーム画面アイコン背景に直結、要最優先対応）
- `layout.tsx:66` `#1447e0`（`theme-color` meta相当）

---

## C. コピー記号 全件列挙（`src/app`・`src/components` の .tsx、JSX/文字列リテラル内。コード内 `!==`・`!isX` 等の否定演算子は0件確認＝除外不要）

### 全角カギ括弧的な二重引用符 " "（U+201C/201D）— 9箇所
| ファイル:行 | 前後文脈 |
|---|---|
| app/layout.tsx:25 | …登録業者が"買取総額"で競い合い、連絡が来るのは… |
| app/page.tsx:24 | …業者は1点ごとではなく"まとめ全体"の金額で入札します。… |
| app/page.tsx:65 | …登録業者が"買取総額"で競い合い、値がつかない物も… |
| app/page.tsx:112 | 片付け、こんな"めんどう"で止まっていませんか |
| app/page.tsx:181 | カタヅケは"家まるごと"の片付け向け。… |
| app/page.tsx:194 | …ではなく<strong>"まとめ全体"の金額で入札</strong>します。… |
| app/page.tsx:211 | 業者が"買取総額"で競うから、高くなりやすい。 |
| app/page.tsx:254 | "家まるごと"の片付けに |
| app/page.tsx:342 | 点数がそろうと<strong>"まとめて一括買取"</strong>の対象に… |

### ダッシュ（—／——）— 25箇所（うち5件はコード内コメント、8件は欠損値表示のフォールバック文字列 `?? "—"`、残り12件が本文コピー。実装時は種別で対応要否を判断）
| ファイル:行 | 種別 | 前後文脈 |
|---|---|---|
| app/business/page.tsx:278 | 本文コピー | 顧客も業者も無駄がなく、納得できる——だから安定する。 |
| app/cases/[id]/page.tsx:322 | フォールバック | `{caseData.housing_type ?? "—"} / {caseData.floor_plan ?? "—"}` |
| app/cases/[id]/page.tsx:323 | フォールバック | `${floorNumber}階` : "—"} / EV |
| app/cases/[id]/page.tsx:324 | フォールバック | `has_elevator == null ? "—" : ...` |
| app/create/page.tsx:637 | フォールバック | `${floorNumber}階` : "—"} / EV${hasElevator...` |
| app/layout.tsx:21 | 本文コピー(metadata) | default: "カタヅケ — 家まるごと、まとめて片付け買取。撮るだけ・待つだけ" |
| app/layout.tsx:44 | 本文コピー(metadata) | title: "カタヅケ — 家まるごと、まとめて片付け買取" |
| app/layout.tsx:47 | 本文コピー(metadata) | alt: "カタヅケ — 家まるごと片付け買取" |
| app/layout.tsx:51 | 本文コピー(metadata) | title: "カタヅケ — 家まるごと、まとめて片付け買取" |
| app/mypage/profile/page.tsx:4 | コードコメント | * 会員情報・設定（/mypage/profile）— 実配線済み。 |
| app/mypage/profile/page.tsx:15 | コードコメント | …の温存は禁止 — 2026-07-16 に一度 redirect 化… |
| app/mypage/withdraw/page.tsx:4 | コードコメント | * 退会・アカウント削除（/mypage/withdraw）— 実配線済み。 |
| app/mypage/withdraw/page.tsx:160 | 本文コピー | title: "アカウント情報 — 削除されます" |
| app/mypage/withdraw/page.tsx:165 | 本文コピー | title: "出品データ — キャンセル・住所情報削除" |
| app/mypage/withdraw/page.tsx:170 | 本文コピー | title: "取引・メッセージ履歴 — 業者側の記録として保持" |
| app/opengraph-image.tsx:12 | 本文コピー(alt) | alt = "カタヅケ — 部屋ごと撮るだけ、片付けと買取の見積もりが届く" |
| app/operator/cases/[id]/page.tsx:150 | フォールバック | `{caseData.housing_type ?? "—"} / {caseData.floor_plan ?? "—"}` |
| app/operator/cases/[id]/page.tsx:151 | フォールバック | `${floorNumber}階` : "階数—"} / EV |
| app/operator/cases/[id]/page.tsx:152 | フォールバック | `has_elevator == null ? "—" : ...` |
| app/operator/page.tsx:185 | フォールバック | `lot.topBid != null ? yen(lot.topBid) : "—"` |
| app/operator/page.tsx:596 | フォールバック | `¥{modalAmount ? yen(modalAmount) : "—"}` |
| app/page.tsx:359 | 本文コピー | …何から手をつけるかの迷い——その一つひとつが、最初の一歩を… |
| app/page.tsx:361 | 本文コピー | …<strong>顧客・業者・社会の三者に喜びと安心を</strong>——それが、… |
| app/review/page.tsx:51 | フォールバック | `if (!visitDate) return "—";` |
| app/review/page.tsx:174/177 | フォールバック | `txn.case?.purpose ?? "—"` |
| components/landing/Features.tsx:2 | コードコメント | * 特徴セクション — カタヅケが選ばれる 3 つの理由。 |
| components/PhotoGuide.tsx:2 | コードコメント | * PhotoGuide — 1 商品に対する推奨撮影アングルガイド。 |

### 全角感嘆符（！）— 7箇所（すべて本文コピー、完了・成功系メッセージに集中）
| ファイル:行 | 前後文脈 |
|---|---|
| app/create/complete/page.tsx:96 | `<h1 className="done-title">出品が完了しました！</h1>` |
| app/password-reset/page.tsx:278 | パスワードを変更しました！ |
| app/review/page.tsx:30 | `STAR_LABELS = [..., "良かった！", "最高でした！"]` |
| app/review/page.tsx:193 | `<div className="done-title">取引が完了しました！</div>` |
| app/review/page.tsx:330 | `<h2>評価を送信しました！</h2>` |
| app/signup/page.tsx:286 | `<h2>登録が完了しました！</h2>` |
| app/verify-email/page.tsx:80 | 確認しました！ |

半角行末「！」相当の和文直後半角 `!`（`!==`等の演算子除く）: **0箇所**（該当なし、対応不要）。

---

## D. 実装の分担案（4グループ）

| グループ | 内容 | ファイル数 | 行数合計 | 置換対象件数(A+B合算) |
|---|---|---:|---:|---:|
| ①コア | katazuke.css/katazuke-pages.css/globals.css/tailwind.config.ts/layout.tsx/providers.tsx/DESIGN_SYSTEM.md | 7 | 1,377 | 16 |
| ②ランディング＋共通クロム | app/page.tsx、components/landing/*(5)、components/kdz/*(13+css1) | 20 | 2,145 | 99 |
| ③マーケ/静的ページ群 | business/company/contact/examples/faq/photo-guide/privacy/terms/legal/not-found/unsubscribe/verify-email/password-reset/signup/login/operator-login/operator-signup/vendors[id]/apple-icon/opengraph-image/manifest/error + AuthCard.tsx のCSS+TSX | 49 | 8,254 | 444 |
| ④ログイン後アプリ画面群 | mypage系/operator系/chat/schedule/notifications/create/condition/analyzing/result/review/cases/applications/admin 他のCSS+TSX | 45 | 14,706 | 1,015 |
| **合計** | | **121** | **26,482** | **1,574**（+C: コピー記号41箇所） |

①は最小コストで全体トークンの土台を作れる最優先着手ポイント（globals.css内の変数再定義とtailwind.config.tsのbrand/kdzカラー定義変更だけで、`var(--radius)`系88件・Tailwindユーティリティ経由の大半に波及）。④が置換対象件数で全体の65%を占め最大工数、③がページ数最多でコピー変更（人の森トーン）と両輪の作業になる。

---

## 結論（3行）
1. CSS側ハードコード値は31ファイル・568色＋border-radius135＋box-shadow72＋translateY15＋backdrop-filter6＋font-family190＋font-weight262＝**1,303箇所**、TSX側Tailwind/インライン色は50ファイルに**271箇所**、合計**1,574箇所**が機械置換対象。
2. `#fff`(194)・ブランドブルー`rgba(31,84,222,*)`(37)・`var(--radius)`系(88)が横断複製の三大パターンで、globals.css/tailwind.config.tsのトークン定義変更が最大レバレッジ。
3. コピー記号（"" ／—／！）は`src/app`・`src/components`で**41箇所**（カギ括弧的引用符9・ダッシュ25・全角！7、半角行末！は0件）、人の森の明朝体トーンに合わせた言い回し変更が必要。

## 主要数値
- 走査ファイル数: CSS 31（総33中2除外）／TSX 75（マッチ0件19ファイルを含む全数走査）
- 置換対象総数: A=1,303／B=271／C=41／**総計1,615**
- グループ別件数: ①16 ②99 ③444 ④1,015（+C 41は横断のため未按分）

## 保存パス
`C:\Users\ko13h\Claude\Projects\ソクウリ\docs\design_hitonomori_alignment\INVENTORY.md`

## 未解決
- 色分類（青系/紺系/暖色グレー系/その他）はHSL色相の機械判定であり、デザイナー目視の意図分類（例: エラー赤の中の警告的トーン差）とは一致しない可能性がある。実装時は本表を一次資料に、最終色は目視確認を推奨。
- `border-radius: 50%`(53件)・`999px`系(69件)は形状用途（円形アバター・ピルボタン）であり「角丸0」方針の対象外か要方針確認（SPEC.mdに明記なければリーダーへエスカレーション）。
- コピー記号のうち「フォールバック文字列`"—"`」8件は表示上のダッシュであり文体変更ではなく仕様確認が必要（em-dashのまま許容か、"-"や"未登録"等に統一するか）。

## サマリ
✅達成: 全31 CSSファイル・75 TSXファイルを走査し、A/B/C/Dの棚卸し表をINVENTORY.mdへ保存完了。編集は未実施（調査専任の指示遵守）。
