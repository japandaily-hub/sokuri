# r7 修正の独立検証（r7-verify）

日時: 2026-09-05 / 対象: 未コミットの r7 修正（backend 10ファイル・web 1ファイル）
自己申告: `.agent-state/audit/r7-fix-backend.md` / `r7-fix-frontend.md`

## 総合判定: 合格（Critical/High 0・新規回帰 0）

## 実測
- `backend/.venv/Scripts/python.exe -m pytest -q` → **793 passed, 801 warnings in 202.72s**（申告 793 と一致）
- `web` `npx tsc --noEmit` → **エラー 0**
- `web` `npx eslint src` → **0 errors / 3 warnings**（notifications/page.tsx:196, operator/transactions/[id]/page.tsx:87, signup/page.tsx:59。いずれも今回の変更と無関係）

## 項目別判定

### (1) 背景解析の3段化と「解析中セッション0」 — 塞がった
- `backend/app/api/v1/endpoints/cases.py:190`（読み・即クローズ）/ `:222`（セッション無しで Gemini・`asyncio.timeout` はここに閉じる）/ `:257`（別セッションで書き戻し）/ `:292`（失敗記録）/ `:304`（3段の呼び出し）。`_CaseAnalysisInput` は frozen dataclass でプリミティブのみ（`cases.py:171-188`）、ORM を跨いで持ち越していない。
- **テストの証明力は本物**。`backend/tests/test_case_ai_background.py:208` が `db_session_module.AsyncSessionLocal` をカウント付きラッパへ差し替え、`cases.py:192/265/294` は `db_session_module.get_background_session_factory()` を毎回呼び、`backend/app/db/session.py:68` の `return AsyncSessionLocal` はモジュールグローバルを**呼び出し時に解決**する。よって差し替えは背景タスクの実 factory を確実に捕まえる（import 時束縛なし）。`:225` で `open == [0]`、`:230` で `opened_total >= 2`、`:231` で終了時 0 を検証。
- 書き戻しは位置ではなく id 突合（`cases.py:271-279`）、`tests/test_case_ai_background.py:240` が items 経路を担保。

### (2) 冪等キーの窓廃止 / UNIQUE / OpenAPI 200 — 塞がった
- `cases.py:153-169`：時刻条件なし、`user_id + idempotency_key` の一致で常に既存 id を返す。DB 制約 `uq_cases_user_id_idempotency_key`（`backend/app/db/models/case.py:64`・migration `0029_case_idempotency_unique.py:77`）と同じ恒久セマンティクスで整合。
- 409 は「制約違反かつ既存行が引けない」場合のみに縮小（`cases.py:547-563`）。
- OpenAPI 200 記載あり（`cases.py:412-417`）。回帰テスト `tests/test_case_ai_background.py:309`（created_at を30日前へ倒して 200）。

### (3) `suspend_user` の前状態比較 — 塞がった
- `backend/app/api/v1/endpoints/admin.py:804` で `prev_suspended` を退避、`:810` の `if prev_suspended and not body.suspended:` で停止→解除の遷移時のみ通知。業者側（`admin.py:399/403`）と対称。テスト `backend/tests/test_admin_notifications_r6.py:249`。

### (4) 0027 の `server_default` 張り替え — 塞がった（ただしテスト無し）
- `backend/alembic/versions/0027_case_ai_status.py:52-64`：`add_column(..., nullable=False, server_default="done")` → `alter_column(server_default="pending")`。PG11+ の add_column は既存行を書き換えないが**既存行の読み値は "done"** になるため、既存案件は起動時スイープ（`cases.py:129` `sweep_stale_pending_ai`）で failed に倒れない。新規 DB も同じチェーンで結果は同一。全行 UPDATE 廃止も確認（旧 `UPDATE cases SET ai_status='done'` は消滅）。
- 監査指示の「`WHERE ai_status IS NULL` を付ける」案は列が `nullable=False` のため無効（既存行が NULL になり得ず、全件 pending 残り→スイープで failed）。実装側の判断が正しい。

### (5) `main.py` の起動スイープ factory と WARNING 抑制 — 塞がった
- `backend/app/main.py:50`（seed）/ `:72`（スイープ）とも `get_background_session_factory()()` 経由。import 時束縛なし。
- `/readyz` の WARNING は `main.py:318-327` で「内容変化時のみ」。

### (6) `tests/test_case_items.py` の期待値厳格化 — 塞がった
- `backend/tests/test_case_items.py:389` が `ai_status == "done"` ちょうど（`in ("done","failed")` の空振りを排除）。`:499` に `ai_condition is not None` を追加し「解析は走った上で検出名だけ落ちた」を担保。

### (7) web 冪等キー再発行と60秒タイムアウト — 塞がった
- `web/src/app/create/page.tsx:415-437`：署名 `JSON.stringify(casePayload)` の対象は purpose / prefecture / city / address_detail / housing_type / floor_plan / floor_number / has_elevator / items（name・sort_order・photos の storage_key）/ photos（storage_key）。**写真キー・品目・住所・目的をすべて含む**。写真の storage_key は `uploadedKey` にキャッシュされるため（`:388-412`）同一内容の再試行では署名が一致＝同一キー使い回し、編集後は不一致＝`crypto.randomUUID()` で再発行。
- `:440-444` で `createTimeoutSignal(60_000)` を付与、`:450-460` で TimeoutError 判定 → 指定文言表示 + `setSubmitting(false)` により再送信可能。
- 唯一の不正確: `page.tsx:428` のコメントが「備考」を挙げるが、本フォームに備考項目は存在しない（機能影響なし・文言のみ）。

## 新規回帰（High 以上）
なし。

## 未解決リスク
1. **`db_pool_timeout` 10→30 秒への戻し**（`backend/app/config.py:67`, `backend/app/db/session.py:36-40`）。長時間占有は消えたが、真にプールが枯渇した際の挙動は「10秒で 500」から「最大30秒ブロック」へ変わる。Render のプロキシタイムアウト次第では 500 が 502/504 と長時間のスレッド滞留に置き換わる。PG 実機での同時実行実測は未実施。
2. **0027 の自動テストが無い**。`backend/tests/test_0028_migration_dedup.py:9-20` の通り 0006 に PG 専用 raw SQL があり SQLite で全チェーンを回せないため、「既存行が done になる」は静的読解のみの担保。本番 PG での 0027〜0029 実適用は未検証。
3. **`dict(zip(item_ids, item_results))` の暗黙切り捨て**（`cases.py:271`）。Gemini 側が items より少ない結果を返すと、余った品目は AI 欄 NULL のまま `ai_status="done"` になり、失敗として検知されない。件数不一致の検証・ログが無い。
4. **タイムアウト後に内容を編集して再送信すると二重案件になりうる**（`web/src/app/create/page.tsx:432-434`）。サーバー側で案件が作られていても署名が変われば新キーを発行するため、冪等では吸収できない。設計上の割り切りだが利用者には見える。
5. **`/readyz` 初回の余計な INFO**（`main.py:318-327`）。初期値 `None` と「未設定なし＝`[]`」が不一致のため、健全な構成でも起動後の初回アクセスで「解消しました」を1回出す。ログノイズのみ。

## サマリ
- ✅ (1) 3段化・テストの証明力（factory 差し替えが実経路を捕捉）
- ✅ (2) 冪等窓廃止 / UNIQUE 整合 / OpenAPI 200
- ✅ (3) suspend_user 前状態比較　✅ (4) 0027 新規/既存 DB とも正　✅ (5) 起動 factory・WARNING 抑制
- ✅ (6) test_case_items 厳格化　✅ (7) web 署名・60秒タイムアウト
- ⚠️ pool_timeout 30秒 / 0027 未テスト / zip 切り捨て / 編集後再送信の二重案件 / readyz 初回 INFO
- ❌ なし
