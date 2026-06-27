# カタヅケ デザインハンドオフ実装プラン（/loop 自走 DoD チェックリスト）

**目的**: 新デザインハンドオフ（`docs/design_handoff_katazuke/` 33ページ・高忠実度）を、稼働中の
Next.js 15 + Tailwind アプリ（`C:\sokuri\web`）へピクセル忠実に実装し、**リリース寸前**まで仕上げる。

**ブランチ**: `feat/design-handoff-katazuke`（main=本番には触れない／デプロイはユーザー承認操作）
**正本**: `C:\sokuri`（OneDrive 側はソース脱水の空殻＝編集禁止）

## 実装方針（確定）
- デザインCSSは `src/app/katazuke.css` に移植し `@import "./katazuke.css" layer(components)` で取り込み（Tailwind utilities が常に上書き可）。
- トークンは `tailwind.config.ts` に橋渡し（`text-kdz-navy` `bg-pale` `shadow-kdz-m` `rounded-kdz` 等）。
- フォント = Zen Kaku Gothic New + Noto Sans JP（globals.css の `@import url()` で実行時ロード・ビルド非依存）。
- 共通部品: `src/components/kdz/`（Icons / interactions[Reveal,PhImg,FaqAccordion,ScrollProgress] / SiteHeader / chrome[SiteFooter,Dock] / SiteChrome / Logo）。
- 画像は未投入（ハンドオフに同梱なし）。`PhImg` がプレースホルダ表示で堅牢化。実アセットは**[要ユーザー提供]**。
- 既存バックエンド配線（login/signup/create/result/operator/admin）は流用。新規ページは高忠実UI＋クライアント状態で実装し配線ポイントを残す。

## 検証DoD（各ページ共通）
1. `npx tsc --noEmit` クリーン
2. `npm run build` 緑（lint含む）
3. 主要ブレークポイント（1140/980/860/560）で崩れない構造
4. デザインの主要コンポーネント（ヘッダー/ボタン/カード/フォーム/モーダル）と視覚的一致

## ページ進捗（design → route）

### 基盤
- [x] デザイントークン / フォント / 共通CSS移植 / 共通部品 / 共通クロム
- [x] `/` トップLP（カタヅケ.html）— **build緑・要・視覚QA**

### 認証・フロー（bare chrome／独自ヘッダー）
- [x] `/login` ← ログイン.html（再スキン済・signIn配線維持・LINEは準備中トースト）
- [ ] `/signup` ← 新規登録.html（3ステップ・既存・要再スキン）
- [ ] `/verify-email` ← メール確認完了.html（新規・confetti）
- [ ] `/password-reset` ← パスワードリセット完了.html（新規・3ステップ）
- [ ] `/create` ← 出品登録.html（多ステップ出品・既存・要再スキン）
- [ ] `/create/complete` ← 出品完了.html（新規）

### ユーザーアプリ
- [x] `/applications` ← 申し込み状況.html（タブ/状態/チャットパネル/早期終了モーダル）
- [ ] `/result` ← 査定結果.html（3状態・既存・要再スキン）⏳複雑既存配線
- [x] `/vendors/[id]` ← 業者詳細.html（評価分布/口コミ/固定CTA）
- [x] `/chat/[id]` ← chat.html（独自ヘッダー/送信・日程確定デモ）
- [x] `/schedule` ← 訪問日程調整.html（カレンダー/時間帯/確定）
- [x] `/review` ← 取引完了・評価.html（スター/タグ/公開トグル）
- [x] `/mypage` ← マイページ.html（タブ/サマリー/カウントダウン）
- [x] `/notifications` ← 通知・お知らせ一覧.html
- [x] `/mypage/profile` ← プロフィール編集.html（変更検知/保存バー）
- [x] `/mypage/withdraw` ← 退会・アカウント削除.html（3チェック）

### 業者（operator）
- [x] `/business` ← 業者向け.html（独自ヘッダー/登録フォーム）
- [~] `/operator` ← 業者ダッシュボード.html（クラスタ5実装中）
- [~] `/operator/chat/[id]` ← 業者チャット.html（クラスタ5実装中）
- [~] `/operator/profile` ← 業者プロフィール.html（クラスタ5実装中）
- [ ] `/operator/login`・`/operator/signup` ← 既存auth・新auth部品で軽再スキン（任意・ハンドオフ対象外）

### 残・複雑な既存配線（最後に個別丁寧に）
- [x] `/signup` ← 新規登録.html（3ステップ・signupUser→signIn→/create 配線維持・commit 709e628）
- [x] `/create` ← 出品登録.html（4ステップ・useToken/uploadCasePhoto/createCase→/cases/{id} 配線維持・commit 67c9f8b）
- [x] `/result` ← 査定結果.html（業者入札選択3状態・旧AssetWise置換・commit e474612）

## ✅ 全33ページ完了（2026-06-28）
- build緑(41ルート) / tsc クリーン
- セキュリティ+QAレビュー実施・指摘是正済（commit 4817cd9）: オープンリダイレクト対策・虚偽成功断定の是正・BlobURLリーク・business.cssスコープ化・メール検証強化・aria
- **リリース前にユーザー対応が必要な残項目**（設計実装の範囲外）:
  1. 🔴 `/company`・`/legal` の架空事業者情報を実値へ（task_b62c0b43）
  2. 実画像アセット（ロゴ/写真/カテゴリ）投入（現状PhImgプレースホルダ）
  3. 新規モックページ（mypage/applications/notifications/chat/schedule/review/vendors/operator dashboard等）の実バックエンド配線 + これらを保護する場合は middleware matcher 追加
  4. LINE認証のバックエンド実装（現状は準備中トースト）
  5. contact/password-reset の送信処理配線
  6. デプロイ（ユーザー承認操作）: main へマージ→Vercel

### コンテンツ・法務（standard chrome）
- [x] `/company` ← 会社概要.html ⚠️**架空サンプル値（古物商番号/代表者/資本金/実績）要差替**
- [ ] `/faq` ← よくある質問.html（新規）
- [ ] `/photo-guide` ← 撮影ガイド.html（新規）
- [ ] `/examples` ← 成約事例.html（新規）
- [x] `/contact` ← contact.html（フォームはデモ・送信未配線）
- [x] `/terms` ← 利用規約.html（タブ式・TermsTabs.tsx）
- [x] `/privacy` ← プライバシーポリシー.html
- [x] `/legal` ← 特定商取引法.html ⚠️**事業者情報がモック準拠・実値要確認**
- [x] `not-found` ← 404.html

## /loop 実行順（クラスタ）
1. ✅ 基盤 + `/`（本イテレーション）
2. 視覚QA(`/`) + 認証/フロー クラスタ（login/signup/verify-email/password-reset/create/create-complete）
3. コンテンツ/法務 クラスタ（faq/photo-guide/examples/company/contact/terms/privacy/legal/404）
4. ユーザーアプリ クラスタ（mypage/applications/result/notifications/profile/withdraw/vendors/chat/schedule/review）
5. 業者 クラスタ（business/operator/operator-chat/operator-profile）
6. 全体ビルド + セキュリティレビュー + 視覚一斉QA → リリース寸前完成

各クラスタ後に `npm run build` 緑を確認し、本ファイルのチェックボックスと PROJECT_STATE を更新する。
