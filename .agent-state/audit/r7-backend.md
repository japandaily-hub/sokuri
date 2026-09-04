# r7 backend 回帰監査 — caaca3a → HEAD（1b72a06 / f5ffdc5 / db32ddd）

対象: `git diff caaca3a HEAD -- backend/`（27 files, +3277/-81）。観点は**回帰のみ**（新機能の是非は対象外）。
既知・意図的未対応（`docs/TODO.md` 03）と `r6-verify-fix.md` で既報の M3/M5/N2/N3・web ページング残件は再指摘しない。
実測: 呼び出し元の全列挙は grep 済み。**既存関数のシグネチャ変更は 0 件**（notify.py / notify_dispatch.py / line_notify.py はいずれも新規関数の追加のみ。既存呼び出しの未更新は無い）。
レート制限スコープは `git diff caaca3a HEAD -- backend/app/core/rate_limit.py backend/app/api/rate_limit_deps.py` が**空**＝既定値の変更なし。
必須化された応答フィールドも 0 件（`ai_status`/`operator_suspended`/`unread_count` はすべて既定値付き＝旧クライアントの 422 は起きない）。
alembic revision id は 18/24/28 字で `alembic_version` VARCHAR(32) 以内。

## High（1件）

### H-1 AI 解析が DB コネクションを最長120秒掴んだまま、プールは 15→10 に縮小・待ち時間は 30→10 秒
- 箇所: `backend/app/api/v1/endpoints/cases.py:194`（`async with session_factory() as session:`）→ `:195`（`session.scalar(...)` で PG のトランザクション開始）→ `:212`（`asyncio.timeout(120)` 配下で Gemini へ HTTP 呼び出し）→ `:261`（ようやく `await session.commit()`）。
  併せて `backend/app/config.py:59-61`（`db_pool_size=5` / `db_max_overflow=5` / `db_pool_timeout=10`）、`backend/app/db/session.py:31-36`。
- 事象: 解析は「別セッション」にはなったが**同一プールの1接続を解析完了まで保持し続ける**（PG では `idle in transaction`）。r6 以前は SQLAlchemy 既定 `pool_size=5 + max_overflow=10 = 15` / `pool_timeout=30` だったのが、いま最大 10 接続・待ち 10 秒。占有時間は 120 秒のまま短縮されていない。`config.py:56-58` のコメント「案件作成の AI 解析は BackgroundTasks 化済みのため、1 本のコネクションを長時間占有する経路は無い」は実装と矛盾しており、この誤った前提の上でプールを縮小したのが回帰。
- 再現: 案件作成を 10 件同時に投げる（解析対象写真ありで各 30〜120 秒）→ 10 接続が全て解析側に張り付く → 以後の任意の API（ログイン・案件一覧・/readyz の DB 検査を含む）が 10 秒待って `TimeoutError: QueuePool limit ... reached` → 500。r6 以前は 15 並列まで耐え、待ちも 30 秒だった＝**同時実行耐性が下がり、かつ失敗が早くなった**。
- 修正案: `_run_case_ai_analysis` を3段に割る — (a) 短いセッションで Case と写真参照を読んで **close**、(b) セッション無しで AI 解析、(c) 書き戻し用に新しいセッションを開いて `UPDATE`。最低限でも `session.scalar(...)` 直後に `await session.commit()`（接続返却）を挟む。加えて解析専用に `NullPool` の別エンジンを持つか、`db_max_overflow` を 10 に戻す。

## Medium（7件）

### M-1 冪等キーの有効窓（10分）と DB 一意制約（恒久）が不整合で、恒久 409 の袋小路が出来る
- 箇所: `backend/app/api/v1/endpoints/cases.py:454-469`（IntegrityError → `_find_idempotent_case_id` が None なら 409）、`backend/app/db/models/case.py:63-65`（`uq_cases_user_id_idempotency_key` は期限なし）、`web/src/app/create/page.tsx:411-415`（`idempotencyKeyRef` は成功時以外リセットされない）。
- 事象: 同じキーの案件が **10分より古い**と `_find_idempotent_case_id` は None を返すのに DB 制約は残っているため、INSERT は必ず IntegrityError → 既存案件も見つからず 409「新しい冪等キーで再送信してください」。web は ref を作り直さないので、ページを再読み込みするまで**何度押しても 409**。
- 再現: /create で送信 → 500 等で失敗 → 写真を撮り直す等で 10 分以上経過 → 再送信 → 恒久 409。
- 修正案: 409 を返す前に `_find_idempotent_case_id` を窓なしで引き直して既存案件を 200 で返す（＝制約と同じ「恒久」セマンティクスに寄せる）。または web 側で 409 受信時に `idempotencyKeyRef.current = null` にして再発行する。

### M-2 `suspend_user` だけ前状態を比較せず、`suspended=false` を送るたびに解除通知が飛ぶ
- 箇所: `backend/app/api/v1/endpoints/admin.py:809-816`（`if not body.suspended:` のみ）。対する `suspend_operator` は `:403`（`if prev_suspended and not body.suspended:`）、`verify_operator` は `:365`（`prev_vendor_status != operator.vendor_status`）で前値比較済み。
- 事象: f5ffdc5 の「状態不変時の重複通知抑止」（r6-verify-fix M4）が業者側 2 経路にしか入っておらず、依頼者側だけ取り残された非対称。一度も停止したことのない依頼者に対して管理画面で `suspended=false` を押すと「アカウントの利用制限を解除しました」が LINE / メールで届く。二度押しでも毎回届く。
- 再現: `PATCH /admin/users/{id}/suspend` に `{"suspended": false}` を 2 回送る → 通知 2 通。
- 修正案: `target.is_suspended` を更新前に `prev_suspended` へ退避し、`if prev_suspended and not body.suspended:` に揃える。

### M-3 `/readyz` が無認証で本番構成の充足状況を返し、未充足時は監視ポーリングごとに WARNING を出す
- 箇所: `backend/app/main.py:304-309`（`logger.warning` を毎回）、`:320-321`（`config` / `degraded_config` を payload へ）。
- 事象: `/readyz` は外形監視が定期ポーリングする無認証エンドポイント。値そのものは出さないものの「Brevo 未設定 / 暗号鍵未設定 / LINE Push 未設定」という攻撃者に有用な運用状態が誰でも読める。加えて未設定が 1 つでも残る間、ポーリング周期ぶん WARNING がログを埋め、Render 無料枠のログ保持 7 日を圧迫して障害時の追跡を妨げる。回帰: この差分以前の `/readyz` は DB とスキーマの状態しか返していなかった。
- 再現: `curl https://<api>/readyz` → `config`・`degraded_config` が素で見える。
- 修正案: `config` / `degraded_config` は `DIAG_TOKEN` 一致時のみ payload へ入れる（診断ログと同じゲート）。WARNING は起動時 1 回＋値変化時のみに落とす（`alerts` の key クールダウンを流用）。

### M-4 冪等再送は 200 を返すのに、ルート宣言は `status_code=201` のまま
- 箇所: `backend/app/api/v1/endpoints/cases.py:328`（`status_code=status.HTTP_201_CREATED`）に対し `:371` と `:464` が `response.status_code = status.HTTP_200_OK`。
- 事象: OpenAPI 上 `POST /cases` の成功は 201 のみ。`201` を厳密判定する既存クライアント・生成 SDK・E2E は再送時に失敗扱いになる。`backend/tests/test_case_items.py` も `assert r.status_code == 201` しか検証していない（200 経路の回帰テストが無い）。
- 再現: 同一 `idempotency_key` で `POST /cases` を 2 回 → 2 回目は 200。スキーマには記載が無い。
- 修正案: デコレータに `responses={200: {"model": CaseOut, "description": "冪等キー一致（既存案件）"}}` を追加し、200 経路の回帰テストを 1 本足す。

### M-5 0027 が `WHERE` 無しで全行 UPDATE し、PG で不要なテーブル再書き込みを起こす
- 箇所: `backend/alembic/versions/0027_case_ai_status.py:52`（`op.execute("UPDATE cases SET ai_status = 'done'")`）。
- 事象: `add_column(server_default=...)` は PG11+ なら既存行を書き換えないのに、直後の無条件 UPDATE が全行を dead tuple 化して実質テーブル倍増＋全行分の WAL を発生させる。0028・0029 が同一 upgrade 実行の中で続くため、`cases` が育った将来のデプロイではこの1文だけでロック保持と再試行時間が伸びる（start.sh は失敗しても uvicorn を起動する設計＝新コード×旧スキーマの degraded 窓が延びる）。
- 再現: 行数の多い `cases` に対し 0027 を適用し `pg_stat_user_tables.n_dead_tup` を観測。
- 修正案: `server_default="done"` で列を足してから `op.alter_column("cases","ai_status", server_default="pending")` に置き換え、UPDATE 文自体を削除する。

### M-6 起動時スイープが `AsyncSessionLocal` をモジュール束縛で使い、`get_background_session_factory()` の差し替え規約を回避している
- 箇所: `backend/app/main.py:30`（`from app.db.session import AsyncSessionLocal, engine`）＋ `:60`（`async with AsyncSessionLocal() as session:`）。対する `backend/app/db/session.py:54-67` は「import 時に束縛しない」ことを差し替え可能性の根拠として明記し、`cases.py:193` は `db_session_module.get_background_session_factory()` 経由になっている。
- 事象: `backend/tests/conftest.py:69` の `monkeypatch.setattr("app.db.session.AsyncSessionLocal", ...)` は main.py が import 時に掴んだ参照には効かない。将来 lifespan をテストで回した瞬間に本物の `DATABASE_URL`（PG）へ接続を試みる。現在は ASGITransport が lifespan を起動しないため顕在化していない潜在バグ。
- 再現: `LifespanManager` 等で lifespan を有効化したテストを追加する → 起動スイープだけテスト用 SQLite を向かない。
- 修正案: `main.py` でも `get_background_session_factory()()` を使う（`sweep_stale_pending_ai` の import と同じく関数越しに解決する）。

### M-7 テスト側の期待が緩められ、AI 解析が全滅しても通る回帰テストが 1 本ある
- 箇所: `backend/tests/test_case_items.py:373-386`（`_case_after_analysis` が `assert detail["ai_status"] in ("done", "failed")`）＋ `:484-491`（`test_poisoned_detected_name_not_persisted` が `assert case["items"][0]["ai_detected_name"] is None`）。
- 事象: `_run_case_ai_analysis` が例外で丸ごと落ちると `ai_status="failed"` かつ `ai_detected_name` は None のままになるため、**このテストは解析が一切走らなくても緑になる**（「毒入りの検出名が保存されないこと」ではなく「解析が動かなかったこと」を通してしまう）。他 3 本（`:402` / `:430` / `:459`）は検出名の実値を見るので空振りしない＝この 1 本のみ。なお `test_line_integration.py:723` のパッチ先を endpoint から `app.services.notify.send_case_created` へ移した変更は**より広い**検証で、緩和ではない。conftest の追加も緩和なし。
- 再現: `_run_case_ai_analysis` の冒頭で例外を投げるよう改変しても `test_poisoned_detected_name_not_persisted` は pass する。
- 修正案: `assert detail["ai_status"] == "done"` に締めるか、当該テストで `ai_summary` に毒文字列が入らないことに加え「他の item の `ai_detected_name` が非 None」を併せて検証する。

## 回帰なしを確認した箇所（根拠）

- 呼び出し元の未更新: `notify.py` / `notify_dispatch.py` / `line_notify.py` は追加のみ（既存 def の変更 0）。新規 `dispatch_*` の呼び出し元（admin.py:365,403,809,1364,1451 / cases.py:486 / users.py:697）は全て引数数・順序が定義と一致。`Operator.line_user_id`（operator.py:34）・`User.line_user_id`（user.py:46）は実在。
- lazy-load 起因の 500: 新規に `bid.operator.is_suspended` を読む `bids.py:67` の全呼び出し元（`:98,:99,:102`）は `bids.py:39` の `selectinload(Case.bids).selectinload(Bid.operator)` 配下。`transactions.py:307` の `txn.bid.operator` も `_TXN_LOAD`（`:147`）で eager load 済み。
- `expire_on_commit=False`（`db/session.py:49`）のため、GET 中に `_reap_stale_pending_ai` が `commit()` しても eager load 済み関連は失効せず MissingGreenlet は起きない。
- タイムゾーン: `TimestampMixin.created_at`（`db/base.py:37-40`）・`user_last_read_at`/`operator_last_read_at`（`transaction.py:62-63`）は全て `DateTime(timezone=True)`。`_unread_counts`（`transactions.py:114-138`）の比較は SQL 内で完結し PG で型不一致にならない。
- lifespan と起動シーケンス: `main.py:22` が既に `api_router` を module top で import しているため `:29` の `cases` 追加 import は新たな失敗経路を作らない。`:83-89` の起動タスクは `yield` 前に await せず全例外を握るため `/health`・`/readyz` を止めない。`start.sh:68` は `uvicorn`（`--workers` 無し＝単一プロセス）なので seed / sweep の多重実行も無い。alembic 失敗時も `start.sh:57` が uvicorn を起動し、`/readyz` の `expected_head` 比較で degraded を返す既存挙動を維持。
- alembic の PG 適用: 0028/0029 の `batch_alter_table` は `recreate="auto"` のため PG では素の `ALTER TABLE ... ADD CONSTRAINT` になり再構築しない（コピー＆リネームは SQLite のみ）。部分一意索引は `postgresql_where`（0028:141）が PG で有効、`sqlite_where`（同:142）は PG では単に無視される。`uq_cancellations_transaction_id` は NULL 同士を重複扱いしないため退会時の `transaction_id=None`（`users.py:509-516` 相当）は従来どおり複数行入る。ORM 側のインデックス名（`ix_transactions_bid_id` / `ix_cases_ai_status` / `ix_cases_idempotency_key`）は migration の `op.f(...)` と一致し、autogenerate の差分は出ない。downgrade は 0029→0028→0027 の順で制約→索引→列を落とすため参照順序の破綻なし（ただし自動是正の巻き戻しは無い＝片道、これは各ファイルに明記済み）。

## 未解決 / 検証できなかったこと

- 本番 PostgreSQL での 0027〜0029 実適用は未検証（テストは SQLite の合成スキーマ）。H-1 の枯渇再現も PG 実機の同時実行測定が要る（`docs/TODO.md` 03 の「PG での同時実行実測」と同じ枠）。
- M-1 の web 側再現は `create/page.tsx:411-415` のコード読みに基づく。実機（10 分放置後の再送信）は未実施。
