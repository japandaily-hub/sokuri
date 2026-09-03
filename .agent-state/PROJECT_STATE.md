# PROJECT_STATE — カタヅケ（ソクウリ）

更新: 2026-09-03（Claude・夜）

## 現在フェーズ
- 人の森整合テーマ（明朝・角丸0・影0・額装フレーム）は全41ルートへ適用済み・**push 済み・本番反映済み**。
  ただし主色はユーザー指示で **苔色 → ブルー #1447e0** へ変更済み（a492bc9）。かたちは人の森整合のまま、色相のみブルー。
- LP図版はフォトリアル3Dレンダー29点＋クレイ調3Dアイコン24点へ差し替え済み（7ca3c4d / 3743e4e）。
- **入札取り下げ（withdraw）機能は push 済み・本番稼働確認済み（2026-09-03 22:48 JST 頃）**。
  /health commit=ab37163、/readyz alembic_version=0020_bid_withdrawal_fk_restrict=expected_head。3環境（Vercel / sokuuri / Render）とも ab37163 で success。

## 現行ハッシュ
- origin/main = main = ab37163（withdraw 機能 + PROJECT_STATE 更新）。分岐なし。

## gate_status（withdraw 機能）
- backend pytest: 564 passed（withdraw 26件含む）。web `tsc --noEmit` エラー0。
- セキュリティレビュー: Critical/High 0。Medium 2 → M-1（commit の IntegrityError→409）対応済み。
  M-2（bid_withdrawals への UPDATE/DELETE を DB ロール権限で REVOKE）は **運用タスクとして未対応**（Render の DB ダッシュボード作業。コードでは対応不可）。
- QA レビュー: Critical/High 0。Medium 2 → M-2（bid_id 一意制約）対応済み。
  M-1（operator-shared.css が /operator/transactions 系にも波及）は差分目視で「テーマ整合のみ」と判断、実機スクショ未実施。
- alembic: 単一ヘッド（0020_bid_withdrawal_fk_restrict）。

## 未解決ブロッカー
- なし（push はユーザー判断）。

## 次アクション
- P1: 本番で業者ログイン後の案件詳細に取り下げボタンが出ること、/operator/transactions の見た目を目視（デプロイ自体は確認済み）。
- P1': Render DB でアプリロールから bid_withdrawals の UPDATE/DELETE を REVOKE（セキュリティ M-2・ユーザーのダッシュボード作業）。
- P2: 画像素材の色方針の再確認。主色がブルーになったため PROJECT_STATE 旧版の「青系素材を苔色へ再生成」は前提が崩れている。現状の青×白素材は主色と整合しており、このまま維持で良いかユーザー確認。
- P3: 正式ロゴの受領（ブルー版）→ `KdzLogo` ワードマーク差し替え。
- P4: QA Low 6 件（`.arw` デッドクラス・未使用コンポーネント退避・ESLint flat config・フォーカスグロー統一）。
- P5: bid_withdraw のレート制限が sensitive_account（5回/15分）流用。業者が短時間に多数取り下げる運用が出たら専用値を新設。

## 決定ログ
| 日時 | 何を | なぜ | 結果 |
| :-- | :-- | :-- | :-- |
| 2026-09-03 | 書体を next/font/google で自己ホスト | セキュリティ High（CSP不在で外部CSS読込／訪問者IPの第三者送信） | 外部リクエスト0を実機確認 |
| 2026-09-03 | 主色を苔色からブルー #1447e0 へ | ユーザー指示 | 成功色 --green は別系統緑で独立。LINE緑は据え置き |
| 2026-09-03 | Codex 実装の withdraw 機能を Claude 側でレビュー・補強して [claude] コミット | Codex セッションが未コミットのまま終了。AGENTS.md 3 に従い意味単位でコミット | 一意制約・IntegrityError変換・テスト1件追加 |
| 2026-09-03 | withdrawn 後の再入札は不可（uq_bids_case_operator） | 設計確定済み（取り下げは終端状態） | テストで担保 |
| 2026-09-03 | 検証を worktree `.claude/worktrees/kdz-verify`（port 3102）へ隔離 | Codex の `next build` が正本 web/.next を消し dev サーバーが 500 化 | 全ルート検証・本番ビルド成功 |
| 2026-09-03 | ヒーロー写真は円形にしない／LINE緑据え置き／入力値はゴシック | デザイナー査読（CRITIQUE.md）の18件を採用 | SPEC-4-decisions.md に確定 |
