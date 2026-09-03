# QAレビュー（人の森整合テーマ差分・2026-09-03）

独立レビュアー（読み取り専用・立案文脈なし）の所見。件数: Critical 0 / High 2 / Medium 5 / Low 6。
合格項目: クラス契約（TSX↔CSS）／旧トークン残存 0／`tsc --noEmit` エラー 0／`width:100vw` 0／`.btn-line-auth` 99px 維持／`:focus-visible` リング維持。
**対応状況は末尾の表を参照。**

## High
| ファイル:行 | 事象 | 根拠 | 修正案 |
| :-- | :-- | :-- | :-- |
| `opengraph-image.tsx:67`(旧) | OG画像のピル「AI査定 × リユース」が要素ごと削除され代替なし | 全44 TSX の可視テキスト照合で唯一の消失 | 直角・緑細枠チップで復活し、WORDING_CHANGES に記録 |
| mypage/page.tsx:233,344 / mypage/profile/page.tsx:246,280 / mypage/withdraw/page.tsx:225,269,317 / notifications/page.tsx:390 / signup/page.tsx:184,233 / vendors/[id]/page.tsx:143 | インライン `fontWeight: 700` が11箇所。継承書体が明朝のため合成太字で滲む | §4.1「明朝は 400/600 のみ」 | 全11箇所を 600 へ |

## Medium
| ファイル:行 | 事象 | 修正案 |
| :-- | :-- | :-- |
| `tailwind.config.ts` boxShadow/borderRadius | 独自キーのみ上書きで Tailwind 既定の `rounded-md〜3xl` `shadow-sm〜lg` が生存 | `theme.borderRadius` / `theme.boxShadow` をフラットに上書き（`full` のみ据え置き） |
| `layout.tsx:105` | スキップリンクに `focus:rounded-md`（6px） | `focus:rounded-none` |
| `Stepper.tsx:42` / `kdz/Ui.tsx:156` / `ChannelCard.tsx:30` | ステップ番号・入札順が `rounded-full` 丸ベタ | 直角へ。`Stepper.tsx` は `Ui.tsx` の複製 |
| `tailwind.config.ts:35-45` + DefectUploader/PhotoGuide | `accent`＝エメラルドがパレット外 | 苔色系へ寄せる |
| `not-found.css`(nf-float) / `verify-email.css`(confetti-fall) | 装飾アニメーション残存（トーン不整合） | 静止化 or reduced-motion 尊重 |

## Low
| ファイル:行 | 事象 | 修正案 |
| :-- | :-- | :-- |
| TSX 19箇所 | `.arw` が CSS から消えデッドクラス残存（視覚回帰なし） | TSX 側も除去 |
| `components/landing/*` / Stepper / ChannelCard / ConditionCard / DefectUploader / PhotoGuide | どこからも import されていない未使用コンポーネント | 削除 or 退避 |
| business.css:275,280 / contact.css:136,142 / faq.css:48 | フォーカスグロー `box-shadow` 5件 | 共通 `:focus-visible` へ一本化 |
| `opengraph-image.tsx:121,131,141,151` | チップ先頭の `●` 削除が未記録 | WORDING_CHANGES に追記 |
| `web/`（eslint.config.* 不在） | ESLint v10 で flat config が無く静的検査不可 | `eslint.config.mjs` 追加 |
| `signup/page.tsx:184,233` | 旧名エイリアス `var(--blue)` のインライン残存（値は同一） | `var(--primary)` へ統一 |

## 文言変更の照合結果（内容不変の検証）
全44 TSX の JSX 日本語テキスト差分を機械抽出。記号変換（“ ”→「」/.mk、——→。、！→。、｜、X：Y）・構造追加（`.hero-blob` `.vt`＝aria-hidden）・移動のみ・alt→テキストノード移行はすべて「文言不変」を確認。唯一の消失が上記 High-1（対応済み）。

## 対応状況（2026-09-03）
| 所見 | 対応 |
| :-- | :-- |
| High-1 OG チップ | **対応済み**: 直角・緑細枠チップで復元、WORDING_CHANGES に追記 |
| High-2 明朝 700 | **対応済み**: 11箇所を 600 へ |
| Medium: Tailwind 既定角丸・影 | **対応済み**: `theme.borderRadius` / `theme.boxShadow` をフラット上書き（`full` のみ 9999px） |
| Medium: スキップリンク角丸 | **対応済み** |
| Medium: 丸ベタ番号 | **対応済み**: 3箇所を直角へ |
| Medium: accent エメラルド | **対応済み**: 苔色系の値へ置換 |
| Medium: 装飾アニメーション | **据え置き**: `globals.css` の `prefers-reduced-motion` で全アニメーションが停止する。紙吹雪は色を苔色系へ変更済み。完全静止化は要ユーザー判断 |
| Low ×6 | **据え置き**（視覚・機能回帰なし。`.arw` デッドクラス・未使用コンポーネント・ESLint flat config は次回の整理タスク） |
