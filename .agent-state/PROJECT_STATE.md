# PROJECT_STATE — カタヅケ（ソクウリ）

更新: 2026-09-03（Claude）

## 現在フェーズ
人の森サイト整合テーマ（明朝・苔色 #527e52・角丸0・影0・額装フレーム）を web 全41ルートへ適用済み。**main にローカルコミット済み・未 push**（push = Vercel 自動デプロイのためユーザー承認待ち）。

## 現行ハッシュ
main = 本ファイルと同時にコミットした最新（`git log --oneline -6` の [claude] 一連: c5462fd 本採用 → 6a0f062 フォント自己ホスト+a11y → b572685 QA指摘 → 35f8963 OGチップ → 認証画面調整）。

## gate_status
- ビルド: `npm run build` 成功（隔離 worktree で実行、全ルート生成）。`tsc --noEmit` エラー0。
- セキュリティレビュー: High 2 / Medium 2 / Low 3 → **全件対応済み**（CSP ヘッダー自体は未導入・外部オリジン依存は解消）。
- QA レビュー: High 2 / Medium 5 / Low 6 → High/Medium 対応済み（装飾アニメーションは reduced-motion 尊重で据え置き）、Low 6 件は次回整理。
- デザイン独立審査: 2.5 → 2.7 / 4（合格ライン 3）。残要因は青系素材（写真/3D）と認証画面の版面（後者は対応済み・未再審査）。

## 未解決ブロッカー
- なし（push はユーザー判断）。

## 次アクション
- P1: ユーザーが `git push origin main` を承認 → Vercel デプロイ → 本番 `/faq` `/` `/login` の目視確認（`document.fonts` に Noto Serif JP が載ること）。
- P2: 青系画像素材（`public/img/step-*.png` `bundle-3d.png` 等）を苔色・生成り系で再生成（gpt-image スキル）。DESIGN_SYSTEM.md §10 に素材ガイドライン（青禁止・彩度上限）を追記。
- P3: 正式ロゴの緑版をユーザーから受領し `KdzLogo` の文字ワードマークを差し替え（または文字ワードマークを確定）。
- P4: QA Low 6 件（`.arw` デッドクラス・未使用コンポーネント退避・ESLint flat config・フォーカスグロー統一）。

## 決定ログ
| 日時 | 何を | なぜ | 結果 |
| :-- | :-- | :-- | :-- |
| 2026-09-03 | 書体を next/font/google で自己ホスト | セキュリティ High（CSP不在で外部CSS読込／訪問者IPの第三者送信） | 外部リクエスト0を実機確認 |
| 2026-09-03 | Codex 並行作業（入札取り下げ: katadzuke-api.ts / operator/cases/* / operator-shared.css / backend alembic 0018）を自分のコミットから除外 | AGENTS.md 同時編集禁止・帰属追跡 | Codex 側が [codex] でコミットする想定。operator-shared.css と operator/cases/* の再デザイン分もそこに同居 |
| 2026-09-03 | 検証を worktree `.claude/worktrees/kdz-verify`（port 3102）へ隔離 | Codex の `next build` が正本 web/.next を消し dev サーバーが 500 化 | 全ルート検証・本番ビルド成功 |
| 2026-09-03 | ヒーロー写真は円形にしない／LINE緑据え置き／入力値はゴシック | デザイナー査読（CRITIQUE.md）の18件を採用 | SPEC-4-decisions.md に確定 |
