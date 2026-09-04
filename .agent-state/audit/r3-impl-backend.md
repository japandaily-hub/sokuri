# R3 バックエンド実装（リリース必須9項目）— 実装台帳

実施日: 2026-09-04 / 実装者: backend実装セッション
対象根拠: `.agent-state/audit/r3-vendor.md` `r3-verify-vendor.md` `r3-operator.md` `r3-verify-operator.md` `r3-crosscut.md` `r3-verify-crosscut.md`
禁止ファイル（別セッション編集中のため未変更）: `backend/app/config.py` `backend/app/main.py` `backend/app/core/alert_middleware.py` `backend/app/services/alerts.py` `backend/tests/test_alerts.py` `.github/workflows/uptime-alert.yml` `web/` 配下全て。

---

## 1. R3-vendor H2: 減額申請の承認／却下が業者に通知されない

- 対応内容: `decide_reduction` に `BackgroundTasks` を追加し、承認/却下いずれも `notify_dispatch.dispatch_reduction_decided`（新設）で業者へLINE優先→メールフォールバック通知する。
- 変更ファイル:行
  - `backend/app/api/v1/endpoints/reductions.py:38-42`（`_TXN_LOAD` に `selectinload(Transaction.bid).selectinload(Bid.operator)` を追加）、`:107-108,135-158`（`decide_reduction` に `background` 追加・commit前にプリミティブ値抽出・`dispatch_reduction_decided` 呼び出し）
  - `backend/app/services/notify_dispatch.py`（`dispatch_reduction_decided` 新設）
  - `backend/app/services/notify.py`（`send_reduction_decided` 新設）
  - `backend/app/services/line_notify.py`（`push_reduction_decided` 新設）
- テスト名: `tests/test_katadzuke_api.py::test_decide_reduction_notifies_operator`

## 2. R3-verify-vendor ADD-1: 成約キャンセルが相手方に一切通知されない

- 対応内容: `cancel_transaction` に `BackgroundTasks` を追加。キャンセルした側の逆（ユーザーがキャンセル→業者へ／業者がキャンセル→ユーザーへ）に `notify_dispatch.dispatch_transaction_cancelled`（新設）で通知する。
- 変更ファイル:行
  - `backend/app/api/v1/endpoints/transactions.py:254-306`（`cancel_transaction` シグネチャに `background` 追加、commit前に相手方の line_user_id/email を解決、`dispatch_transaction_cancelled` 呼び出し）
  - `backend/app/services/notify_dispatch.py`（`dispatch_transaction_cancelled` 新設）
  - `backend/app/services/notify.py`（`send_transaction_cancelled` 新設）
  - `backend/app/services/line_notify.py`（`push_transaction_cancelled` 新設）
- テスト名: `tests/test_katadzuke_api.py::test_cancel_transaction_notifies_operator_when_user_cancels` / `::test_cancel_transaction_notifies_user_when_operator_cancels`

## 3. R3-verify-vendor ADD-2: 減額申請の送信も依頼者に通知されない

- 対応内容: `create_reduction` に `BackgroundTasks` を追加し、commit後に案件所有ユーザーを取得して `notify_dispatch.dispatch_reduction_requested`（新設）で通知する。リンク先は依頼者が実際に閲覧できる `/cases/{case_id}`。
- 変更ファイル:行
  - `backend/app/api/v1/endpoints/reductions.py:55-95`（`create_reduction` に `background` 追加・所有ユーザー取得・`dispatch_reduction_requested` 呼び出し）
  - `backend/app/services/notify_dispatch.py`（`dispatch_reduction_requested` 新設）
  - `backend/app/services/notify.py`（`send_reduction_requested` 新設）
  - `backend/app/services/line_notify.py`（`push_reduction_requested` 新設）
- テスト名: `tests/test_katadzuke_api.py::test_create_reduction_notifies_case_owner`

## 4. R3-operator H1: /contact がバックエンド未配線

- 対応内容: `POST /contact` を新設（認証不要）。契約どおり `{name, email, category, message}` を受け、`get_settings().admin_emails` の各宛先へ `notify.send_contact_received`（新設）を `BackgroundTasks` で送信。`admin_emails` が空ならWARNINGログを出し202は維持。
- 変更ファイル:行
  - `backend/app/api/v1/endpoints/contact.py`（新規ファイル）
  - `backend/app/api/v1/router.py`（`contact_router` 登録）
  - `backend/app/schemas_katadzuke.py`（`ContactCreateRequest` / `ContactCreateResponse` 追加）
  - `backend/app/services/notify.py`（`send_contact_received` 新設）
- 流用したレート制限キー: `RateLimitGuard("public_read")`（無認証の公開エンドポイント向け既存スコープ。IP軸・全リクエストカウント。config.py への新規キー追加なし）
- テスト名: `tests/test_contact.py::test_contact_success_sends_mail_to_admin_emails` / `::test_contact_without_admin_emails_still_returns_202` / `::test_contact_validation_errors_422`（パラメタライズ6件）

## 5. R3-operator H2: admin に案件・成約の横断閲覧手段がない

- 対応内容: `GET /admin/cases` / `GET /admin/transactions` を新設。`get_current_admin` 必須。`q`（前方一致=ID／部分一致=依頼者メール・業者名）・`status`・`limit`（既定50・上限200）・`offset` に対応。新しい順。SQLインジェクション対策としてORM（`ilike`/`cast`）のみ使用、生SQL文字列結合なし。N+1回避のため依頼者メールはバッチ取得（`User.id.in_(...)`）。
- 変更ファイル:行 `backend/app/api/v1/endpoints/admin.py`（`admin_list_cases` / `admin_list_transactions` 新設。`_ADMIN_CASE_TXN_DEFAULT_LIMIT=50` `_ADMIN_CASE_TXN_MAX_LIMIT=200`）、`backend/app/schemas_katadzuke.py`（`AdminCaseListItem/Response` `AdminTransactionListItem/Response` 追加）
- **admin一覧APIの最終レスポンス仕様**（web側次波の実装契約として確定）:
  - `GET /admin/cases?q=&status=&limit=&offset=` → `{ "items": AdminCaseListItem[], "total": int }`
    - `AdminCaseListItem`: `id, status, created_at, purpose, prefecture, city, user_email, company_name, amount, visit_date`
    - `amount`/`company_name`/`visit_date` は成約済み（selected bid）の場合のみ非null。`user_email` はマスクなし（admin専用）。
    - 遷移先: `GET /cases/{id}`（既存、role==admin許容済み）
  - `GET /admin/transactions?q=&status=&limit=&offset=` → `{ "items": AdminTransactionListItem[], "total": int }`
    - `AdminTransactionListItem`: `id, case_id, status, created_at, user_email, company_name, amount, visit_date`
    - 遷移先: `GET /transactions/{id}`（既存、role==admin許容済み）
  - 補足（設計上の逸脱・意図）: Block2 原文は case/transaction 共通で「業者名・金額・訪問予定日」を挙げているが、案件（Case）は成約前は業者・金額が定まらないため nullable とした。また案件一覧に `purpose/prefecture/city` を追加した（依頼者ヒアリング前に案件を識別するための最小限の追加情報。amount/company_nameと違い常にコストゼロで取得済みのため）。
- テスト名: `tests/test_katadzuke_api.py::test_admin_list_cases_and_transactions` / `::test_admin_list_cases_respects_limit_and_offset`

## 6. R3-verify-operator M2: admin一覧APIに件数上限が無い

- 対応内容: `list_invites` `list_operators` `list_operator_applications` `list_identity_documents` に `limit`（既定100・上限500）・`offset` を追加。既定値でクエリ省略時は従来どおり動作（後方互換）。新しい順は既存の `order_by(...desc())` を維持。
- 変更ファイル:行 `backend/app/api/v1/endpoints/admin.py:161-185`（invites/operators）、`:333-347`（operator-applications）、`:522-556`（identity-documents。`_DEFAULT_LIST_LIMIT=100` `_MAX_LIST_LIMIT=500`）
- テスト名: `tests/test_katadzuke_api.py::test_admin_invites_and_operators_list_accept_limit_offset_and_default_unchanged`

## 7. R3-verify-operator ADD-1: POST /analyze が無認証・レート制限なし

- 対応内容: `get_current_user` による認証必須化 + `RateLimitGuard("analyze")` を追加。既存の無認証テスト（`test_api.py`）を認証付きに修正し、401テストを追加。
- 変更ファイル:行 `backend/app/api/v1/endpoints/analyze.py`（`user: User = Depends(get_current_user)` 追加、`request.state.rate_limit.hit_account(...)` 呼び出し追加）
- 流用したレート制限キー: 新スコープ `"analyze"` を `backend/app/api/rate_limit_deps.py` の `_scope_spec`/`_SCOPE_MESSAGES` に追加したが、**ルール実体は既存の `case_create_ip`/`case_create_account`（`RateLimitConfig`。config.pyに新規キー追加なし）をそのまま流用**（AI呼び出しを伴う同種のコストDoSプロファイルのため）。
- テスト名: `tests/test_api.py::test_analyze_requires_authentication_401`（既存4件も認証付きに修正: `test_analyze_200` 等）、`tests/test_vision_retry.py::test_retry_exhaustion_maps_to_503_via_analyze_endpoint`（認証付きに修正）

## 8. R3-verify-operator ADD-3: admin昇格経路がサインアップ時のみ

- 対応内容: `auth.py` に `_promote_to_admin_if_listed(user)` を新設。パスワードログイン（`user_login`）・LINEログイン（`line_exchange` の既存User紐付け経路）の両方で、`email in get_settings().admin_emails` かつ `role != "admin"` なら昇格して保存する（降格はしない一方向）。
- 変更ファイル:行 `backend/app/api/v1/endpoints/auth.py:56-68`（`_promote_to_admin_if_listed` 新設）、`:151-155`（`user_login`）、`:612-616`（`line_exchange` 既存Userブランチ）
- テスト名: `tests/test_katadzuke_api.py::test_login_promotes_existing_user_to_admin_when_email_listed`

## 9. R3-verify-crosscut M7/M8: 落選通知に案件情報が無い／メールに事業者名・所在地・問い合わせ先が無い

- M7対応: `send_bid_lost`/`push_bid_lost`/`dispatch_bid_lost` のシグネチャに `prefecture, city, purpose` を追加し、本文に「{都道府県}{市区町村}／{用途}」と `/operator/cases/{case_id}` へのリンクを追加。呼び出し元2箇所（`select_bid` の落選通知・`cancel_case` の却下通知）も更新。案件の品目要約関数（AI要約）は同期的に呼ぶには重すぎるため、既存カラムの `prefecture/city/purpose` で代替（設計判断）。
- M8対応: `notify._wrap` のフッターに「カタヅケ運営事務局（神奈川県横浜市）」「お問い合わせ: katazuke.info@gmail.com」を追加。値は `web/src/app/legal/page.tsx` の記載と同一（web側は今回未変更・grep確認のみ）。
- 変更ファイル:行
  - `backend/app/services/notify.py`（`_wrap` フッター、`send_bid_lost` シグネチャ変更）
  - `backend/app/services/line_notify.py`（`push_bid_lost` シグネチャ変更）
  - `backend/app/services/notify_dispatch.py`（`dispatch_bid_lost` シグネチャ変更）
  - `backend/app/api/v1/endpoints/bids.py:281-284,306-314`（`select_bid` 呼び出し元更新）
  - `backend/app/api/v1/endpoints/cases.py:438-441,454-462`（`cancel_case` 呼び出し元更新）
- テスト名: `tests/test_contact.py::test_send_bid_lost_includes_case_context_and_link` / `::test_mail_footer_includes_operator_org_name_address_and_contact`
- 既存テスト回帰修正: `tests/test_line_integration.py`（`dispatch_bid_lost` 直接呼び出し2件・`_fake_lost` シグネチャ更新）

---

## 未対応と理由

- **R3-operator H1の修正案(2)（フォーム撤去）は不採用**、案(1)（バックエンド配線）を実装した。web側のフォーム自体（完了画面文言・エラーハンドリング）は `web/` 配下のため対象外（次波でweb担当が実装）。
- **fee_amount（8%手数料）の実装（R3-crosscut M4）は未対応**。verify台帳の判断（β期間中は無料が方針、実装するとβ無料方針と矛盾する）を踏襲し、リリースには不要と判断。今回のBlock2指示9項目にも含まれていない。
- **R3-operator ADD-2（依頼者の停止手段の完全欠如）・ADD-3以外の管理者関連（本タスクADD-3は「昇格経路」のみ）は対象外**。Block2の9項目に含まれていないため未着手（次波候補）。
- **/admin/cases・/admin/transactions のweb側UI実装**は`web/`配下のため対象外（次波でweb担当が実装。レスポンス契約は本ドキュメント冒頭に確定済み）。
- **クーリングオフ告知・特商法表記等の法務系指摘（H3〜H9等）**はBlock2の9項目に含まれず、文言修正であり`web/`配下のため対象外。

---

## pytest 結果

`.venv\Scripts\python.exe -m pytest -q` — 677 passed, 0 failed（既存659件 + 新規実装分約18件。既存の回帰修正=analyze系4件・dispatch_bid_lost系3件を含む）。
