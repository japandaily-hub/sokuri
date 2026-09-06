# r12 backend 是正レポート（決定1〜4）

## 結論
- 決定1〜3を実装、決定4は backend 変更なし（金額計算が backend に無いことを再確認）。
- `pytest -q` **864 passed / 0 failed**（着手時 855 → 新規9件。既存7件は仕様反転に合わせて更新）。
- alembic 単一ヘッド `0033_reminder_marks`（19文字・32文字制限内）。

## 決定1: 審査中業者の閲覧制限
`app/api/deps.py` に共通ゲートを新設し、各ハンドラの個別判定を廃止した。

- `OPERATOR_APPROVAL_REQUIRED_DETAIL = {"code": "approval_required", "message": "運営の承認後に案件を閲覧できます。"}`
- `OPERATOR_CASE_VIEW_STATUSES = {"active", "limited"}`（`pending` / `rejected` は 403）
- `assert_operator_case_access(operator)`: **停止判定を先に行う**ため、停止中の active 業者には従来どおり `account_suspended` が返る（`approval_required` に潰さない）。
- `get_case_viewer_actor`（Depends）: `GET /cases`・`GET /cases/{id}`・`GET /cases/{id}/bids` に適用。
- `get_optional_operator`（Depends）: `GET /files/{key}` 用の任意認証。トークン無し／壊れている／依頼者トークンは `None` を返し、**無認証 capability URL の互換を壊さない**。

`cases.py` の「pending にも公開案件を見せる」分岐は撤去済み（コメントも是正）。
`GET /files/{key}` は多層防御の位置づけ。一次防御は案件APIの403（未承認業者は storage_key 自体を受け取れない）で、DBを引くのは「業者トークン付き かつ 未承認/停止中」の稀な経路のみ（`case_photos.storage_key` は 0017 の一意索引で O(log n)）。無トークンの `<img>` 経路はクエリ0本のまま。

## 決定2: 入札額の他社非開示
他社額を返す経路を grep で全列挙し、以下の1経路のみだったことを確認した（`_to_masked_out`）。

- `CaseMaskedOut.top_bid_amount` を**スキーマごと削除**（フィールドを残すと将来復活しうるため型で塞ぐ）。
- `cases.py::_to_masked_out` の `out.top_bid_amount = max(...)` を削除。`bid_count` / `my_bid` は維持。
- `bids.py::list_bids` の業者分岐は元から自社入札のみ返しており変更不要（コメントで契約を明示）。
- 依頼者（`CaseOut` / `list_bids` の owner 分岐）・admin 分岐は未変更＝従来どおり全件。

## 決定3: リマインド定期処理
- alembic `0033_reminder_marks`: `transactions.overdue_reminded_at` / `cases.no_bid_reminded_at`（DateTime(timezone=True) NULL）＋**部分索引2本**（`ix_transactions_overdue_reminder` / `ix_cases_no_bid_reminder`、`... IS NULL` 条件）。送信済み行が積み上がっても走査対象が増えない設計。モデル側 `__table_args__` にも同一定義を置き、SQLite テストDBと autogenerate の乖離を防いだ。
- `app/services/reminders.py`（新規）: `run_reminders(session) -> {"overdue": n, "no_bid": n}`。
  - (a) `visit_date < 今日(JST)` かつ status ∈ {pending, visiting} かつ `overdue_reminded_at IS NULL` → 依頼者・業者の双方へ通知しマーク。
  - (b) `status="open"` かつ作成から3日超 かつ非取り下げ入札0 かつ `no_bid_reminded_at IS NULL` → 依頼者へ通知しマーク。
  - **N+1回避**: 依頼者は `IN (...)` で1回だけ一括取得（`_load_owners`）、業者は `selectinload(Transaction.bid → Bid.operator)`。
  - 退会・停止中の受信者はスキップ。宛先が無くてもマークは立てる（毎時同じ空クエリを繰り返さないため）。
- `main.py`: lifespan で `_run_reminder_loop`。**起動直後に1回走らせてから待つ**（Render 無料枠のスピンダウンで1周も完了しない事態を避ける。マーカーで冪等なので再デプロイ連発でも重複送信なし）。毎周ごとに `get_background_session_factory()` で新セッションを開いて即閉じ、待機中はDB接続を借りない。例外は握って `alerts.send_alert(severity="warning", key="reminders_loop_failed")`。shutdown時は `cancel()` して待つ。
- `config.py`: `REMINDERS_ENABLED`（既定 true・キルスイッチ）/ `REMINDER_INTERVAL_SECONDS`（既定 3600）。
- 通知テンプレは既存の3層構造を踏襲: `line_notify.push_visit_overdue` / `push_no_bid_reminder`、`notify.send_visit_overdue` / `send_no_bid_reminder`、`notify_dispatch.dispatch_visit_overdue` / `dispatch_no_bid_reminder`（LINE優先→メールフォールバック、`@_best_effort`）。

## 決定4: 手数料の税区分
backend に金額計算ロジックが無いことを再確認（`fee_amount` は入力値の保持のみ）。変更なし。

## web への契約（固定）
1. **403 の判別**: 未承認業者 → `detail.code === "approval_required"` / `detail.message === "運営の承認後に案件を閲覧できます。"`。停止中 → 従来の `account_suspended`。対象は `GET /cases`、`GET /cases/{id}`、`GET /cases/{id}/bids`、`GET /files/{key}`（案件写真かつ業者トークン付き時のみ）。
2. **削除フィールド**: `CaseMaskedOut.top_bid_amount` は**応答に存在しない**（`undefined` になる）。`bid_count`・`my_bid` は継続。ダッシュボードの「うち首位 n 件」は算出根拠が無くなるため表示を撤去すること。`my_bid.amount` は従来どおり自社分のみ返る。
3. **新規 API**: `POST /api/v1/admin/jobs/reminders`（admin のみ・body 不要）→ `200 {"overdue": number, "no_bid": number}`。2回目以降は 0 が正常（冪等）。依頼者トークンは 403、業者トークンは 401。

## 未対応 / 申し送り
- `/files/{key}` は依然として無認証 capability URL（`<img>` が Authorization を送れないため）。今回のゲートは「業者トークンを明示的に付けた場合」にのみ効く二次防御で、URL を控えていた未承認業者が**トークン無し**で叩けば取得できる。恒久対策は署名付き短命 URL 化で、別タスク。
- `limited` は閲覧可・入札不可のまま（レガシー値）。運用上ゼロ件の想定だが、実データに残っていないかは要確認 [要確認]。
- リマインドの再送手段（マーカーを NULL に戻す admin API）は未実装。必要時は DB 直接操作。
- 決定3(a) の対象 status に `pending` を含めたのは、`visit_date` が入ったまま状態が戻された行を取りこぼさないため。現行フローでは日程確定で `visiting` になるため実質 `visiting` のみ。

## 変更ファイル
backend/app/api/deps.py, backend/app/api/v1/endpoints/{cases,bids,case_photos,admin}.py,
backend/app/schemas_katadzuke.py, backend/app/config.py, backend/app/main.py,
backend/app/db/models/{case,transaction}.py, backend/alembic/versions/0033_reminder_marks.py,
backend/app/services/{reminders(新規),case_view,notify,line_notify,notify_dispatch}.py,
backend/tests/test_r12_backend_fixes.py（新規9件）,
backend/tests/{test_katadzuke_api,test_bid_withdrawn_legacy,test_case_ai_background}.py（仕様反転に追随）

## サマリ
- ✅ 決定1（承認ゲート・4経路 + 停止中の区別）
- ✅ 決定2（他社額・順位の全経路非開示。grep で経路は1箇所と確定）
- ✅ 決定3（0033・定期ループ・手動実行・二重送信防止）
- ✅ 決定4（backend 変更なしを確認）
- ✅ pytest 864 passed / alembic 単一ヘッド 0033
- ⚠️ `/files/{key}` の無認証取得は残存（署名付きURL化は別タスク）
- ⚠️ `limited` の実データ残存有無が未確認
- ⚠️ リマインドの手動再送（マーカー戻し）API 無し
