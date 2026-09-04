# r6 backend 修正（担当1: 案件AI背景化 / プール / readyz / 通知）— 2026-09-04

対象台帳: `.agent-state/audit/r6-backend.md`（H-1, H-3, H-4, M-5, M-7）、`r6-verify-backend.md`（ADD-1）、
`r6-web-quality.md` + `r6-verify-web.md`（H3 / H1 / H2 / A1 / A2）。
pytest: **784 passed**（変更前 753 → 新規 31）。`.venv\Scripts\python.exe -m pytest -q`。

---

## 1. [High] 案件作成の AI 解析を背景化（H-1 + ADD-1）

| 項目 | 実装 |
|---|---|
| 短いトランザクションで commit → 即応答 | `backend/app/api/v1/endpoints/cases.py:337-345`（旧: 解析を await してから commit）。作成時は `summary.build_fallback_summary`（`app/services/summary.py:85`）で暫定要約を埋める |
| 背景解析（新セッション） | `cases.py:114-206` `_run_case_ai_analysis`。`app/db/session.py:get_background_session_factory()` で **新しい** `AsyncSession` を開く（リクエストスコープのセッション・コネクションは既に返却済み） |
| 全体デッドライン 120 秒 | `cases.py:73` `_AI_ANALYSIS_DEADLINE_SEC = 120`、適用は `cases.py:139`（`async with asyncio.timeout(...)`） |
| 状態列 | `app/db/models/case.py:38-44`（`CASE_AI_STATUS_PENDING/DONE/FAILED`）、`case.py:85-94`（`ai_status` / `ai_failed_reason` / `idempotency_key`）。migration `backend/alembic/versions/0027_case_ai_status.py`（既存行は `UPDATE cases SET ai_status='done'`） |
| 失敗時 | `ai_status="failed"` + `ai_failed_reason`（型名+180字に切り詰め。SDK例外に画像/リクエストが混ざるため全文は載せない）。案件は `open` のまま有効、要約はフォールバック文が残る |
| 冪等キー | `cases.py:77` `_IDEMPOTENCY_WINDOW=10分`、`cases.py:89-112` `_find_idempotent_case_id`（窓判定は SQL でなく Python 側。SQLite naive / PG aware の型不一致で常時 False になるのを回避）、`cases.py:296-308` で **200** 返却 |
| 通知は解析を待たない | `cases.py:400-408`（notify を先に add_task → その後 AI 解析）。BackgroundTasks は逐次実行のため順序が意味を持つ |

テスト（`backend/tests/test_case_ai_background.py`）:
`test_create_case_returns_pending_and_completes_in_background` /
`test_ai_analysis_failure_marks_case_failed_but_keeps_case_usable` /
`test_ai_analysis_respects_overall_deadline` /
`test_create_case_notifies_via_dispatch_not_direct_mail` /
`test_same_idempotency_key_returns_existing_case_with_200` /
`test_idempotency_key_is_scoped_per_user` /
`test_without_idempotency_key_duplicate_posts_create_two_cases`。
既存テストの追随: `tests/test_case_items.py`（`_case_after_analysis` ヘルパを追加し、AI 由来フィールドは作成応答ではなく詳細取得で検証）、
`tests/test_line_integration.py:723`（patch 先を `app.services.notify.send_case_created` へ）、
`tests/conftest.py`（`db_session` が `app.db.session.AsyncSessionLocal` をテスト用エンジンへ差し替え＝背景セッションが本番 PG へ接続しにいくのを防ぐ）。

## 2. [High] 接続プール（ADD-1）

`backend/app/db/session.py:20-43` — `pool_size` / `max_overflow` / `pool_timeout` を明示（既定 5 / 5 / 10、`config.py:47-56` の `DB_POOL_SIZE` `DB_MAX_OVERFLOW` `DB_POOL_TIMEOUT` で上書き可、`config.py:_validate_db_pool` で 0 以下を起動時に弾く）。
プール引数は `postgresql+asyncpg` の時だけ渡す（SQLite の StaticPool/NullPool は受け付けない）。
`render.yaml` 突合: 該当キーは未定義＝**コード既定値（5/5/10）が本番の実効値**。`render.yaml` の envVars は既存サービスへ同期されない既知事象があるため、変更したい場合は dashboard か `start.sh` の `${VAR:-既定}` で入れること。
長時間占有の解消は 1（AI 解析の背景化）で担保。認証依存性が掴んだコネクションは応答と同時に返る。

## 3. [High] /readyz の設定検証（H-4）＋ alerts の Task 強参照

- `backend/app/main.py:68-104` `_config_readiness(settings)` — **bool のみ**返す（payload は無認証で読めるため値は載せない）。`encryption_key` は `Fernet(key)` 構築まで試し、形式不正も False。
- `main.py:264-288` — payload に `config` と `degraded_config` を追加。**未設定があっても `status` は `ready` のまま**（起動中断・503 は「業者申込だけ500」を「API全断」に悪化させるため採らない）。欠落時は WARNING ログ。
- `app/services/alerts.py:40-46,182-186` — `fire_and_forget` の Task を `_inflight_tasks` で強参照保持（GC で消えて送信されない CPython の落とし穴）、完了時に `discard`。
- `alerts.send_alert`（`alerts.py:160-175`）— gather の引数順を LINE → Webhook → メールへ変更。3チャネルは並行実行のままなので、Brevo 障害時でも LINE/Webhook は独立して届く（順序は意図の明示）。

/readyz の新形状（追加分のみ）:
```json
{ "status": "ready",
  "config": { "encryption_key": true, "brevo": false, "line_push": true,
              "gemini": false, "admin_emails": true, "frontend_base_url": true },
  "degraded_config": ["brevo", "gemini"] }
```
テスト: `tests/test_admin_notifications_r6.py::test_config_readiness_flags_are_bool_only` /
`::test_readyz_reports_degraded_config_but_stays_ready`。

## 4. [High] 通知送信失敗の可視化（H-3）

- `app/services/notify.py:99-118` — `_send` の except で `logger.error` + `alerts.send_alert(severity="warning", key="notify_brevo_send_failed")`。
- `app/services/line_notify.py:72-90` — 同様に `key="line_notify_push_failed"`。
- 抑制は `alerts` の key 単位クールダウン（`ALERT_COOLDOWN_SECONDS` 既定 600 秒＝10分）。**宛先別ではなく固定キー**で束ねる（障害時に N 通出るのを防ぐ）。アラート本文に宛先・件名・line_user_id は載せない。
- アラート経路が Brevo 依存にならないことは 3 の gather で担保。

テスト: `test_mail_send_failure_fires_warning_alert` / `test_line_push_failure_fires_warning_alert`。

## 5. [High] 通知の追加（web-quality H3 / H1 / H2 / A1）

| イベント | 実装 | 送信経路 |
|---|---|---|
| 業者の入札可否切替 | `admin.py:360-372`（`verify_operator`） | `notify_dispatch.dispatch_operator_verified`（`notify_dispatch.py:102`）→ `line_notify.push_operator_verified` / `notify.send_operator_verified`。リンク: `/operator/cases`（active）・`/operator`（停止） |
| 停止解除（業者） | `admin.py:396-407`（`suspend_operator`。`suspended=false` の時のみ） | `dispatch_account_unsuspended`（`notify_dispatch.py:116`）。リンク `/operator` |
| 停止解除（依頼者） | `admin.py:799-810`（`suspend_user`。同上） | 同上。リンク `/mypage` |
| 本人確認 承認 | `admin.py:1353-1366` | `dispatch_identity_document_reviewed`（`notify_dispatch.py:134`）。リンク `/mypage/identity` |
| 本人確認 却下 | `admin.py:1439-1450`（理由つき） | 同上。LINE 側は却下理由を `_sanitize_inline` で1行化（改行での偽案内行の捏造防止） |
| 案件登録完了（A1） | `cases.py:396-406`（`notify` 直呼びを撤去） | `dispatch_case_created`（`notify_dispatch.py:85`）→ LINE 専用ユーザーにも届く |

**停止（suspended=true）側は通知しない**（r6-verify-web H1 の指摘どおり、理由開示は運用ポリシーの選択であり既定にしない。解除のみ確実に通知）。
A2 の指摘どおり全て「LINE優先→未連携/失敗時にメール」の排他フォールバック（振込先変更のみが併用、という既存規約は変えていない）。
テスト: `tests/test_admin_notifications_r6.py::test_verify_operator_notifies_operator` /
`::test_unverify_operator_notifies_with_inactive_flag` /
`::test_operator_unsuspend_notifies_but_suspend_does_not` /
`::test_user_unsuspend_notifies` /
`::test_identity_document_approve_and_reject_notify_user`。

## 6. [Medium] M-5 / M-7

- **M-5**: `cases.py:415-431` に `limit`（既定 100・上限 200）/`offset` を追加し、**業者分岐のみ**に適用（`cases.py:456-466`）。依頼者側は「自分の案件が全件見えること」を優先し従来どおり全件。並びは `created_at desc, id desc`（同時刻のページ跨ぎ重複/取りこぼし防止）。応答形状は list のまま。
  テスト: `test_operator_case_list_supports_limit_and_offset` / `test_operator_case_list_rejects_limit_over_max` / `test_user_case_list_is_not_paginated`。
- **M-7**: `admin.py:174-196` に `_get_application_for_update_or_404`（`session.get(..., with_for_update=True)`）を新設し、`approve`（`admin.py:1084`）と `reject`（`admin.py:1148`）だけに適用。参照系の `_get_application_or_404` はロック無しのまま（r6-verify-backend の注意点どおり共有ヘルパを無条件で書き換えない）。SQLite では `FOR UPDATE` が生成されず no-op。
  テスト: `test_operator_application_approve_uses_row_lock`。

---

## web 契約（フロント側の変更が必要）

1. `POST /cases` リクエスト: `idempotency_key?: string`（最大64文字。web が送信ごとに UUID を生成し、**リトライでは同じ値を再送**すること）。
2. `POST /cases` レスポンス: 新規作成は **201**、冪等キー一致の再送は **200**（body は同じ `CaseOut`）。
3. `CaseOut.ai_status: "pending" | "done" | "failed"`（`GET /cases/{id}` にも含まれる）。作成直後は必ず `pending`。web は `pending` の間だけ `GET /cases/{id}` をポーリングし、`done`/`failed` で停止する。`failed` でも案件は有効で `ai_summary` にフォールバック文が入っているため、エラー表示ではなく「AI 解析なし」相当の扱いにすること。
4. `GET /cases`（業者）: `?limit=`（既定 100・上限 200・超過は 422）/`?offset=`。応答は従来どおり配列。**業者一覧画面にページングを入れないと 101 件目以降が存在しないように見える**ため、web 側の追随が必須。依頼者の一覧は変更なし。
5. `CaseMaskedOut`（業者向け）には `ai_status` を追加していない（業者は解析完了後の案件しか実質見ないため。必要になれば追加）。

## 未対応 / 別担当 / ユーザー判断

- H-2（写真が Render 一時ディスクで消える）・M-1〜M-4・M-6・ADD-2（`GET /transactions` の LIMIT）は別担当ないし別スコープ。0028（`0028_txn_state_integrity`）が 0027 の後段に既に積まれており、alembic ヘッドは単一。
- M2（入札ゼロ放置リマインド）は未実装の新機能のため本修正に含めない。
- [要確認] 本番の Cloudflare 応答待ち上限は未計測。デッドライン 120 秒は「解析品質を落とさず、かつ冪等キーで重複が防げる」前提で置いた値。
- [要確認] `DB_POOL_SIZE=5` は Render 無料 PG の接続上限を明示確認したものではない（無料枠の同時接続上限は公開値が変動するため）。`/readyz` が 503 を返し始めたら真っ先に見る値。
