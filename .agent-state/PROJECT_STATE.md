# PROJECT_STATE — カタヅケ（ソクウリ）

更新: 2026-09-03（Claude・深夜）

## 現在フェーズ
- **2026-09-04 3視点導線監査（依頼者／業者／運営）＋レスポンシブ是正をローカルコミット済み（未push）。** 台帳: `.agent-state/audit/`（user-journey / vendor-journey / operator-crosscut / verify-* / review-qa / round2 は戻り値のみ）。High 21件→CONFIRMED 19・PARTIAL 2、追加発見 6、第2周で回帰 3 を捕捉し全て修正。web のみ 33 ファイル。tsc 0・eslint 0 error・`next build` 成功。
  - 意図的未対応（backend 変更が要る）: 業者停止解除 API 無し／承認 API が許可証未提出を拒否しない（フロントのみガード）／案件一覧のエリアフィルタ未実装（案内文は実態に合わせ是正済み）／katadzuke-api.ts の 422 detail 配列握り潰し（入札額は事前検証で回避）。
  - push は保留: ローカル main に別セッションの cancel_case 実装（83ca245・03ca239）が未 push で載っており、一緒に本番へ出るため。push 可否はユーザー判断。
- 人の森整合テーマ（明朝・角丸0・影0・額装フレーム）は全41ルートへ適用済み・**push 済み・本番反映済み**。
  ただし主色はユーザー指示で **苔色 → ブルー #1447e0** へ変更済み（a492bc9）。かたちは人の森整合のまま、色相のみブルー。
- LP図版はフォトリアル3Dレンダー29点＋クレイ調3Dアイコン24点へ差し替え済み（7ca3c4d / 3743e4e）。
- **入札取り下げ（withdraw）機能は push 済み・本番稼働確認済み（2026-09-03 22:48 JST 頃）**。
  /health commit=ab37163、/readyz alembic_version=0020_bid_withdrawal_fk_restrict=expected_head。3環境（Vercel / sokuuri / Render）とも ab37163 で success。

## 現行ハッシュ
- origin/main = 4269223（別 Claude セッションのヒーローバッジ削除）→ 本番 3 環境 success・/health commit=4269223・alembic_version=0021。
- main = 7e87149（QA Low 対応）→ origin より 1 コミット先行（push 予定）。
- **注意: 別 Claude セッションが同じ作業ツリーで「業者の入札取り下げ」を廃止し「依頼者の出品取り下げ（cancel_case）」へ置換中（未コミット）。** 対象: backend bids.py/cases.py/case_lock.py/test_case_cancel.py、web cases/[id]/page.tsx・operator/cases/[id]/page.tsx・operator-shared.css・katadzuke-api.ts。これらは触らないこと。
  その方針だと 0019〜0021 の bid_withdrawals 監査テーブルと append-only トリガーは不要になる可能性がある（トリガーはテーブル DROP で自動消滅、関数 bid_withdrawals_reject_mutation は残るので DROP FUNCTION を migration に含めること）。

## gate_status（出品取り下げ）
- backend pytest: 562 passed（test_case_cancel 15件・legacy 9件含む）。web `tsc --noEmit` エラー0。
- セキュリティ/QA レビュー: Critical/High 0。Medium 3件（token ガード・ロック順序回帰テスト・コメント陳腐化）全て対応済み。
- 本番の業者画面での目視は未実施（業者ログイン必要）。

## gate_status（withdraw 機能・廃止済み）
- backend pytest: 564 passed（withdraw 26件含む）。web `tsc --noEmit` エラー0。
- セキュリティレビュー: Critical/High 0。Medium 2 → M-1（commit の IntegrityError→409）対応済み。
  M-2（bid_withdrawals への UPDATE/DELETE を DB ロール権限で REVOKE）は **運用タスクとして未対応**（Render の DB ダッシュボード作業。コードでは対応不可）。
- QA レビュー: Critical/High 0。Medium 2 → M-2（bid_id 一意制約）対応済み。
  M-1（operator-shared.css が /operator/transactions 系にも波及）は差分目視で「テーマ整合のみ」と判断、実機スクショ未実施。
- alembic: 単一ヘッド（0020_bid_withdrawal_fk_restrict）。

## 未解決ブロッカー
- なし（push はユーザー判断）。

## 次アクション
- P1: 別セッションの cancel_case 置換が終わったら、本番で依頼者ログイン後の案件詳細に出品取り下げボタンが出ることを目視（業者ログインが必要な検証は Claude 側では不可＝パスワード入力禁止。ユーザー実施）。
- P1': 完了。M-2 は REVOKE ではなく append-only トリガー（0021）で対応、本番適用済み。
- P2: 完了（決定）。主色ブルーと現行の青×白素材は整合。再生成しない。
- P3: 正式ロゴの受領（ブルー版）→ `KdzLogo` ワードマーク差し替え。
- P4: 完了（7e87149）。残警告 4 件（未使用変数）は放置可。
- P5: bid_withdraw のレート制限が sensitive_account（5回/15分）流用。業者が短時間に多数取り下げる運用が出たら専用値を新設。

## 決定ログ
| 日時 | 何を | なぜ | 結果 |
| :-- | :-- | :-- | :-- |
| 2026-09-03 | 書体を next/font/google で自己ホスト | セキュリティ High（CSP不在で外部CSS読込／訪問者IPの第三者送信） | 外部リクエスト0を実機確認 |
| 2026-09-03 | 主色を苔色からブルー #1447e0 へ | ユーザー指示 | 成功色 --green は別系統緑で独立。LINE緑は据え置き |
| 2026-09-03 | Codex 実装の withdraw 機能を Claude 側でレビュー・補強して [claude] コミット | Codex セッションが未コミットのまま終了。AGENTS.md 3 に従い意味単位でコミット | 一意制約・IntegrityError変換・テスト1件追加 |
| 2026-09-03 | withdrawn 後の再入札は不可（uq_bids_case_operator） | 設計確定済み（取り下げは終端状態） | テストで担保 |
| 2026-09-03 | 業者の入札取り下げを廃止し、出品者の出品取り下げへ置換 | ユーザー指示 | API/UI/通知/レート制限を撤去。スキーマは本番適用済みのため残置（0021 での巻き戻しは監査証跡を消す破壊的操作になるため不採用） |
| 2026-09-03 | 出品取り下げの業者通知は既存 bid_lost（「今回は成約に至りませんでした」）を流用 | 文言が中立で新関数不要（DRY） | Cancellation に cancelled_by=user・transaction_id=NULL で記録 |
| 2026-09-03 | 検証を worktree `.claude/worktrees/kdz-verify`（port 3102）へ隔離 | Codex の `next build` が正本 web/.next を消し dev サーバーが 500 化 | 全ルート検証・本番ビルド成功 |
| 2026-09-03 | M-2 を REVOKE でなく DB トリガーで実装（0021） | Render 管理 PG はアプリ＝オーナーロールで REVOKE が無効 | 本番 /readyz で 0021 確認 |
| 2026-09-03 | 青×白の画像素材は維持 | 主色ブルー #1447e0 と整合 | 再生成しない |
| 2026-09-03 | ヒーロー写真は円形にしない／LINE緑据え置き／入力値はゴシック | デザイナー査読（CRITIQUE.md）の18件を採用 | SPEC-4-decisions.md に確定 |
