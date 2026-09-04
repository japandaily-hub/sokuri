# PROJECT_STATE — カタヅケ（ソクウリ）

更新: 2026-09-03（Claude・深夜）

## 現在フェーズ
- **2026-09-04 3視点導線監査（依頼者／業者／運営）＋レスポンシブ是正をローカルコミット済み（未push）。** 台帳: `.agent-state/audit/`（user-journey / vendor-journey / operator-crosscut / verify-* / review-qa / round2 は戻り値のみ）。High 21件→CONFIRMED 19・PARTIAL 2、追加発見 6、第2周で回帰 3 を捕捉し全て修正。web のみ 33 ファイル。tsc 0・eslint 0 error・`next build` 成功。
  - 2026-09-04 push 済み（4a03154・3環境 success・/health commit=4a03154）。続けて backend: `PATCH /admin/operators/{id}/suspend`（停止／解除）新設と、承認 API の許可証ゲート（pending/limited→active は has_license_image 必須・409）を追加。/admin に停止／解除ボタン・「停止中」フィルタ・停止中は承認操作不可。pytest 569 件通過。
  - 2026-09-04 業者目線の実機PDCA 3周（ローカル: run_local_e2e.py + seed_local_e2e.py、ブラウザペインで業者A/入札/日程提案/減額申請/プロフィール保存/ログアウトを実操作）。修正: 業者ルート全てにタブ名（layout.tsx）／「落札管理」→「取引」表記統一／チャットのモバイルヘッダー潰れ・空状態案内・手数料予定額・候補日リスト表示・日付例の動的化／ダッシュボードの集計ラベル・ヒント2行化・タブ折返し・品目要約見出し／案件詳細の入札完了通知／案件一覧の品目要約とエリア・未入札絞り込み。
    - 検証環境の再現手順: `cd backend && .venv/Scripts/python.exe run_local_e2e.py`（8000）→ `.venv/Scripts/python.exe seed_local_e2e.py`（テスト口座は同ファイル冒頭）→ web は port 3000（ALLOWED_ORIGINS の都合で 3000/3100/3101 のみ）。ブラウザペインでは form_input/type が React の制御 input に効かないことがあるので、ネイティブ setter + input イベントで値を入れ requestSubmit する。
  - 2026-09-04 依頼者目線・審査中業者・管理者の実機PDCA（seller / pending / e2e-admin）。依頼者側で実操作: 入札の見比べ→選定（成約）→候補日の確定→減額申請の却下→作業完了→評価投稿→出品の取り下げ、通知設定・プロフィール設定・退会画面の閲覧。修正: 依頼者ルート全てにタブ名（mypage/cases は template 継承）／業者公開プロフィールのカテゴリが英字キー表示→日本語名（lib/categories.ts で編集画面と共有）／訪問予定の日付二重表示（案件詳細・評価ページ・backend の確定メッセージ）→ formatVisitSchedule に統一／入札一覧に「最高額」バッジと業者プロフィール導線／マイページのタブ「終了」→「成約・終了」と品目要約見出し／日程調整ページの「¥…円」二重表記。審査中業者: 承認待ちバナーを「許可証画像の提出が必要」に具体化（ApprovalPendingNotice）。管理者: 承認ガード・停止／解除・検索連動バッジ・許可証モーダルを実機確認、/admin にタブ名。
  - 2026-09-04 追加: 公開プロフィールの承認バッジを is_approved（vendor_status）基準に、取り下げ済み案件に案内文（cf1ebce）。業者連絡先メールの案件詳細表示は「成約後のみ・事業用連絡先」として据え置き（決定）。
  - 残る意図的未対応: 案件一覧のエリアフィルタ未実装（案内文は実態に合わせ是正済み）／katadzuke-api.ts の 422 detail 配列握り潰し（入札額は事前検証で回避）／停止解除で旧トークンが再有効化する（トークン世代カウンタ未実装・セキュリティ Medium）／招待コード登録は許可証未提出でも active（運用前提・要判断）。
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

## 依頼者マイページ拡張（2026-09-04）
- 実装済み・ローカルコミット済み・未 push: 本人情報（生年月日・職業）／住所（郵便番号〜建物名、都道府県→エリア自動同期）／
  本人確認書類（運転免許証・マイナンバーカード表面のみ・パスポート・在留カード・健康保険証。DB BYTEA 保存・本人/admin のみ配信・
  admin 審査 /admin/identity-documents）／振込口座（Fernet 暗号化・下4桁表示・パスワード再確認。LINE 専用ユーザーは
  直近10分以内のトークンのみ許可・LINE Push + メール通知）／ダッシュボードの入力状況カード。
- alembic: 0021（bid_withdrawals 追記専用トリガー）→ 0022（users PII 列）→ 0023（user_identity_documents）。
- レビュー: セキュリティ High 1（口座変更の再認証なし）→ 是正、再レビューで LINE 専用ユーザーの穴 → step-up + 通知で是正。
  QA Medium 4 → 全て対応。backend 651 passed、web tsc エラー0。
- スコープ外（未実装）: eKYC 顔照合、業者への開示範囲変更、振込実行、admin による依頼者口座の復号開示、書類の法定保存期間バッチ。
- 運用: 本番の APP_ENCRYPTION_KEY が Render に設定済みかは口座保存の実機で確認する（未設定なら 500）。

## 未解決ブロッカー
- なし（push はユーザー判断）。

## 次アクション
- **P1: 障害・異常時アラート基盤 — 完了（2026-09-04）。** 外形監視 `.github/workflows/uptime-alert.yml`（5分毎）＋アプリ内 `app/core/alert_middleware.py`。通知先は運営用 LINE 公式アカウント「カタヅケ運営」（@854kzrrb・Channel ID 2011424972・顧客向け【公式】カタヅケとは別チャネル）。GitHub Secrets と Render 環境変数（ALERT_LINE_CHANNEL_ACCESS_TOKEN / ALERT_LINE_USER_IDS / ALERT_MAIL_FROM）は `scripts/setup_alerts.py` で登録済み、Actions の疎通テスト success、LINE push は HTTP 200 で到達確認。メール（Brevo）と Webhook は未設定（必要になったら `.env.alerts` に追記して同スクリプトを再実行）。GitHub PAT（katadzuke-alerts）は30日期限＝2026-10-04 に失効するが、登録済み Secrets はそのまま有効で監視は継続する（再登録時のみ再発行が必要）。
- P1: 別セッションの cancel_case 置換が終わったら、本番で依頼者ログイン後の案件詳細に出品取り下げボタンが出ることを目視（業者ログインが必要な検証は Claude 側では不可＝パスワード入力禁止。ユーザー実施）。
- P1': 完了。M-2 は REVOKE ではなく append-only トリガー（0021）で対応、本番適用済み。
- P2: 完了（決定）。主色ブルーと現行の青×白素材は整合。再生成しない。
- P3: 正式ロゴの受領（ブルー版）→ `KdzLogo` ワードマーク差し替え。
- P4: 完了（7e87149）。残警告 4 件（未使用変数）は放置可。
- P5: bid_withdraw のレート制限が sensitive_account（5回/15分）流用。業者が短時間に多数取り下げる運用が出たら専用値を新設。
- P6（構想・2026-09-04 ユーザー起票）: 商品が少ない場合やその他の事情で業者の訪問引き取りが成立しにくいケース向けに、大手輸送会社等による引き取り導線を検討する（候補: ヤマト運輸・佐川急便・軽貨物業者）。訪問査定を前提とした現行フロー（入札→上位3社から選択→訪問査定→引き取り→プラットフォーム経由入金）との整合・料金負担・査定方法（写真のみ／到着後）は未定。

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
