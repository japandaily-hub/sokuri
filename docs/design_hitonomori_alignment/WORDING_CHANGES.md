# 言葉の作法 変更記録（全担当統合・2026-09-03）

コピーの意味は不変。記号（“ ”／——／！）の作法のみを人の森サイトに揃えた。欠損値フォールバックの「—」とコードコメントは据え置き。

## 担当 A


SPEC-4-decisions.md §4.3 の作法に基づく記号のみの正規化。**コピーの意味・語は一切変えていない。**
対象は担当Aの所有ファイル（§4.4 A列）のみ。

| ファイル:行 | 変更前 | 変更後 | 根拠 |
| :-- | :-- | :-- | :-- |
| `web/src/app/layout.tsx:21` | `カタヅケ — 家まるごと、まとめて片付け買取。撮るだけ・待つだけ` | `カタヅケ｜家まるごと、まとめて片付け買取。撮るだけ・待つだけ` | metadata/title の ` — ` は `｜` |
| `web/src/app/layout.tsx:25` | `登録業者が“買取総額”で競い合い、` | `登録業者が買取総額で競い合い、` | metadata 文字列内は引用符を外す（`“ ”` は使わない） |
| `web/src/app/layout.tsx:44` | `カタヅケ — 家まるごと、まとめて片付け買取`（openGraph.title） | `カタヅケ｜家まるごと、まとめて片付け買取` | 同上 |
| `web/src/app/layout.tsx:47` | `alt: "カタヅケ — 家まるごと片付け買取"` | `alt: "カタヅケ｜家まるごと片付け買取"` | 同上 |
| `web/src/app/layout.tsx:51` | `カタヅケ — 家まるごと、まとめて片付け買取`（twitter.title） | `カタヅケ｜家まるごと、まとめて片付け買取` | 同上 |
| `web/src/app/manifest.ts:16` | `カタヅケ — 部屋ごと撮るだけAI片付け査定` | `カタヅケ｜部屋ごと撮るだけAI片付け査定` | 同上（PWA の name はホーム画面に露出する） |
| `web/src/app/opengraph-image.tsx:14` | `alt = "カタヅケ — 部屋ごと撮るだけ、片付けと買取の見積もりが届く"` | `alt = "カタヅケ｜部屋ごと撮るだけ、片付けと買取の見積もりが届く"` | 同上 |

## 据え置いた箇所（§4.3 の例外）

- **コードコメント・CSS のセクション見出しコメント内の `—`**（例: `katazuke.css` の `/* HERO — … */`）。
  §4.3 で「コードコメント内は据え置き」と確定済み。ユーザーに露出しない。
- **`opengraph-image.tsx` の見出し文言**（`部屋ごと撮るだけ。` / `片付けと買取が、まとめて片づく。`）。
  記号を含まないため変更なし。
- **`chrome.tsx` / `SiteHeader.tsx` のリンク文言・フッター文**。`“ ”` `—` `！` を含まないため変更なし。
- 欠損値フォールバックの `"—"` は担当Aの所有ファイルには存在しない。

## 担当 B


担当B。§4.3 の記号ルールに従い、コピーの意味は変えず記号のみ変換した。行番号は編集後ファイルの行。

| ファイル:行 | 変更前 | 変更後 |
| :-- | :-- | :-- |
| page.tsx:24 (FAQ_ITEMS a) | `業者は1点ごとではなく“まとめ全体”の金額で入札します。` | `業者は1点ごとではなく<span className="mk">まとめ全体の金額で入札</span>します。`（文字列→ReactNode化、引用符除去） |
| page.tsx:67 (hero-sub) | `登録業者が“買取総額”で競い合い、` | `登録業者が<span className="mk">買取総額</span>で競い合い、` |
| page.tsx:114 (empathy h2) | `片付け、こんな“めんどう”で` | `片付け、こんな<span className="mk">めんどう</span>で` |
| page.tsx:185 (bundle h2 style) | `style={{ color: "var(--blue)" }}` | `style={{ color: "var(--primary)" }}` |
| page.tsx:186 (bundle lead p) | `カタヅケは“家まるごと”の片付け向け。` | `カタヅケは<span className="mk">家まるごと</span>の片付け向け。` |
| page.tsx:199 (bundle-c key p) | `<strong>“まとめ全体”の金額で入札</strong>` | `<strong className="mk">まとめ全体の金額で入札</strong>`（引用符除去のみ、strongは既存） |
| page.tsx:217 (auction h2) | `業者が“買取総額”で競うから、` | `業者が<span className="mk">買取総額</span>で競うから、` |
| page.tsx:260 (scenes h2) | `“家まるごと”の片付けに` | `<span className="mk">家まるごと</span>の片付けに` |
| page.tsx:337 (cat icon style) | `style={{ fontSize: 32, color: "var(--blue)", strokeWidth: 1.8 }}` | `style={{ fontSize: 32, color: "var(--primary)", strokeWidth: 1.8 }}` |
| page.tsx:350 (cats-note p) | `<strong>“まとめて一括買取”</strong>` | `<strong className="mk">まとめて一括買取</strong>`（引用符除去のみ、strongは既存） |
| page.tsx:367 (founder-copy p) | `何から手をつけるかの迷い——その一つひとつが、` | `何から手をつけるかの迷い。その一つひとつが、`（——→。） |
| page.tsx:369 (founder-copy p) | `顧客・業者・社会の三者に喜びと安心を</strong>——それが、` | `顧客・業者・社会の三者に喜びと安心を</strong>。それが、`（——→。） |

## 追加した実要素（§4.2、記号変換ではないが構造変更として記録）
- `.hero` 直下先頭に `<div className="hero-blob" aria-hidden="true" />` を1件追加（page.tsx:54）。
- `#bundle` `#auction` の `<section>` 直下先頭に `<span className="vt" aria-hidden="true">…</span>` を各1件追加（page.tsx:177, 213）。見出し文言をそのまま使用、`<br>`/`<span>` は含めない。

## 検証
- `“` `”` `——` `！`（全角）の残存は 0 件（page.tsx全体、node正規表現で最終確認）。
- `var(--blue)` インライン color の残存は 0 件（`--blue` は katazuke.css 側のトークンエイリアスとしては温存、tsx内のインラインスタイルのみ置換）。
- `components/landing/*.tsx`（Comparison/Faq/Features/ServiceIntro/TrustStrip）は page.tsx から未import・未使用を確認済み。スコープ外につき無変更。

## 担当 C


§4.3 記号変換の適用実績。コピーの意味は不変、記号のみ変更。

| ファイル:行 | 変更前 | 変更後 |
| :-- | :-- | :-- |
| web/src/app/business/page.tsx:278 | 顧客も業者も無駄がなく、納得できる——だから安定する。 | 顧客も業者も無駄がなく、納得できる。だから安定する。 |
| web/src/app/verify-email/page.tsx:80 | 確認しました！ | 確認しました。 |
| web/src/app/password-reset/page.tsx:278 | パスワードを変更しました！ | パスワードを変更しました。 |
| web/src/app/signup/page.tsx:286 | 登録が完了しました！ | 登録が完了しました。 |

担当ファイル全体（business/company/contact/examples/faq/photo-guide/privacy/terms/legal/unsubscribe/verify-email/password-reset/signup/login/vendors/not-found/error/AuthCard）を
Perl スクリプトで走査（`\x{201C}\x{201D}\x{2014}\x{2013}！` の4パターン）した結果、上記4件が全件。
“強調語” のカギ括弧化・引用符変換の対象は0件（INVENTORY.md §C の該当行は page.tsx／landing 配下＝B担当のため対象外）。
metadata の ` — ` は本担当ファイル内に0件（layout.tsx・opengraph-image.tsx はA担当）。

## 担当 D1


SPEC-4-decisions.md §4.3 準拠。コピーの意味は不変、記号のみ変更。

| ファイル:行 | 変更前 | 変更後 |
| :-- | :-- | :-- |
| web/src/app/create/complete/page.tsx:96 | `出品が完了しました！` | `出品が完了しました。` |
| web/src/app/review/page.tsx:193 | `取引が完了しました！` | `取引が完了しました。` |
| web/src/app/review/page.tsx:330 | `評価を送信しました！` | `評価を送信しました。` |
| web/src/app/review/page.tsx:30 (STAR_LABELS) | `"良かった！", "最高でした！"` | `"良かった", "最高でした"` |
| web/src/app/mypage/withdraw/page.tsx:160 | `title: "アカウント情報 — 削除されます"` | `title: "アカウント情報：削除されます"` |
| web/src/app/mypage/withdraw/page.tsx:165 | `title: "出品データ — キャンセル・住所情報削除"` | `title: "出品データ：キャンセル・住所情報削除"` |
| web/src/app/mypage/withdraw/page.tsx:170 | `title: "取引・メッセージ履歴 — 業者側の記録として保持"` | `title: "取引・メッセージ履歴：業者側の記録として保持"` |

## 据え置き（対象外・確認済み）
- `review/page.tsx:114,124,277` の「良かった点」「評価を送信しました」（！なし）: 変更不要（元々感嘆符なし）。
- `cases/[id]/page.tsx` 等のフォールバック `?? "—"`: SPEC §4.3 により据え置き。
- コードコメント内の `—`: 据え置き。

## 保存パス
`C:\Users\ko13h\Claude\Projects\ソクウリ\docs\design_hitonomori_alignment\WORDING_CHANGES_D1.md`

## 担当 D2


担当ファイル（`web/src/app/{operator,admin}/**`、`web/src/components/kdz/{AppHeader,AppHeaderLogout,OperatorHeader,HeaderNav,Ui,DisclosureNotice,auth}.tsx`、`operator-header.css`）を
SPEC-4-decisions.md §4.3 の記号（`"..."` → `<span className="mk">` または「」／本文の `——`・`—` → 句点区切り／`！` → `。`）に照らして全文走査した。

## 走査結果: 対象0件

Node スクリプトで U+201C（"）・U+201D（"）・U+FF01（！）・U+2014（—）・U+2015（―）の
Unicode コードポイントを担当 `.tsx` 全ファイル（`operator/**`・`admin/**`・`components/kdz/{AppHeader,AppHeaderLogout,OperatorHeader,HeaderNav,Ui,DisclosureNotice,auth}.tsx`）で走査した結果、
ヒットしたのは以下 5 件のみで、いずれも SPEC §4.3 が明示的に**据え置き対象**と定める「欠損値フォールバック文字列 `"—"`」であり、本文コピーではない。

| ファイル:行 | 内容 | 判定 |
| :-- | :-- | :-- |
| `app/operator/cases/[id]/page.tsx:178` | `{caseData.housing_type ?? "—"} / {caseData.floor_plan ?? "—"}` | フォールバック（据え置き） |
| `app/operator/cases/[id]/page.tsx:179` | `` `${floorNumber}階` : "階数—"} / EV `` | フォールバック（据え置き） |
| `app/operator/cases/[id]/page.tsx:180` | `has_elevator == null ? "—" : ...` | フォールバック（据え置き） |
| `app/operator/page.tsx:185` | `lot.topBid != null ? yen(lot.topBid) : "—"` | フォールバック（据え置き） |
| `app/operator/page.tsx:596` | `¥{modalAmount ? yen(modalAmount) : "—"}` | フォールバック（据え置き） |

本文コピー中の `"強調語"`（引用符）・`"会話"`・本文 `——`・完了文言の `！` は D2 担当範囲に**0件**。
コードコメント内のダッシュ・演算子 `!==` 等も本走査対象外（該当なし）。

## 結論
D2 担当範囲での言葉の作法（記号）変更は **0件**。上記5件は据え置きのまま変更していない。

## 追記（QAレビュー反映・2026-09-03）

| ファイル:行 | 変更前 | 変更後 | 備考 |
| :-- | :-- | :-- | :-- |
| web/src/app/opengraph-image.tsx（旧67行） | ピル「AI査定 × リユース」 | 直角・緑細枠チップ「AI査定 × リユース」として復元 | 描き直し時に欠落していたものを QA 指摘で復元。文言不変 |
| web/src/app/opengraph-image.tsx:121,131,141,151 | `●完全無料` 等（先頭 ● 付き 4件） | `完全無料` 等 | 記号のみ削除（人の森の作法＝装飾記号を使わない）。文言不変 |
