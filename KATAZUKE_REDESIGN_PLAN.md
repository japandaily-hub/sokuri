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
- [ ] `/applications` ← 申し込み状況.html（新規・タブ/状態）
- [ ] `/result` ← 査定結果.html（3状態・既存・要再スキン）
- [ ] `/vendors/[id]` ← 業者詳細.html（新規）
- [ ] `/chat/[id]` ← chat.html（新規）
- [ ] `/schedule` ← 訪問日程調整.html（新規）
- [ ] `/review` ← 取引完了・評価.html（新規）
- [ ] `/mypage` ← マイページ.html（新規）
- [ ] `/notifications` ← 通知・お知らせ一覧.html（新規）
- [ ] `/mypage/profile` ← プロフィール編集.html（新規）
- [ ] `/mypage/withdraw` ← 退会・アカウント削除.html（新規）

### 業者（operator）
- [ ] `/business` ← 業者向け.html（新規・登録フォーム付きLP）
- [ ] `/operator` ← 業者ダッシュボード.html（既存・要再スキン/拡張）
- [ ] `/operator/chat/[id]` ← 業者チャット.html（新規）
- [ ] `/operator/profile` ← 業者プロフィール.html（新規）

### コンテンツ・法務（standard chrome）
- [ ] `/company` ← 会社概要.html（新規）
- [ ] `/faq` ← よくある質問.html（新規）
- [ ] `/photo-guide` ← 撮影ガイド.html（新規）
- [ ] `/examples` ← 成約事例.html（新規）
- [ ] `/contact` ← contact.html（新規）
- [ ] `/terms` ← 利用規約.html（既存・要再スキン）
- [ ] `/privacy` ← プライバシーポリシー.html（既存・要再スキン）
- [ ] `/legal` ← 特定商取引法.html（既存・要再スキン）
- [ ] `not-found` ← 404.html（既存・要再スキン）

## /loop 実行順（クラスタ）
1. ✅ 基盤 + `/`（本イテレーション）
2. 視覚QA(`/`) + 認証/フロー クラスタ（login/signup/verify-email/password-reset/create/create-complete）
3. コンテンツ/法務 クラスタ（faq/photo-guide/examples/company/contact/terms/privacy/legal/404）
4. ユーザーアプリ クラスタ（mypage/applications/result/notifications/profile/withdraw/vendors/chat/schedule/review）
5. 業者 クラスタ（business/operator/operator-chat/operator-profile）
6. 全体ビルド + セキュリティレビュー + 視覚一斉QA → リリース寸前完成

各クラスタ後に `npm run build` 緑を確認し、本ファイルのチェックボックスと PROJECT_STATE を更新する。
