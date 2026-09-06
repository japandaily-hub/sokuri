# r12 — PostgreSQL 実機での同時実行チェック（行ロック / 部分一意索引 / 冪等制約の実証）

実施日: 2026-09-06 / 実施者: backend（自動）
環境: Docker `postgres:16`（`kdz-pg`, host 55432）＋ `alembic upgrade head`（head=`0033_reminder_marks`）
      ＋ `backend/scripts/run_pg_e2e.py`（uvicorn :8001, `RATE_LIMIT_ENABLED=false`）
検証: `backend/scripts/pg_concurrency_check.py`（各シナリオ 3 ラウンド。**API 応答コードと
      DB の実行後状態の両方**を毎回照合。DB は asyncpg で直結して count する）

## 背景

第6〜8周で入れた直列化（`app/services/case_lock.py` の `SELECT ... FOR UPDATE`）と
0028/0029 の一意制約は、pytest が SQLite のため **`FOR UPDATE` が no-op** で一度も
実証されていなかった。本ラウンドで実 PG 上での実挙動を確認した。

## 結果（6/6 PASS。run_id=1da85c35）

| # | シナリオ | 応答コード（3ラウンド共通） | DB の実行後状態 | 判定 |
| --- | --- | --- | --- | --- |
| S1 | 同一案件への同時 `select_bid`（2業者の入札を依頼者が同時選定） | `[201, 409]` | `transactions=1` / `bids.status='selected'=1` | PASS |
| S2 | 業者退会 `DELETE /operator/me` と同時の `select_bid` | `select=409` / `delete=204` | `operators.deleted_at=set` / 進行中 `transactions=0` | PASS |
| S3 | 同一取引への減額申請 同時3連投 | `[201, 409, 409]` | `reduction_requests(pending)=1`、続く逐次で 2件目=201 / 3件目=409・総数2 | PASS |
| S4 | 取引キャンセルの同時2連投 | `[200, 409]` | `cancellations=1` / `transactions.status='cancelled'` | PASS |
| S5 | 同一 `idempotency_key` の `POST /cases` 同時2連投 | `[200, 201]`（**修正後**） | `cases=1` / 返却 id は1種 | PASS |
| S6 | `PATCH /admin/transactions/{id}/cancel` と依頼者 `complete` の同時実行 | `admin_cancel=200` / `complete=409` | `status='cancelled'` / `cancellations=1` | PASS |

補足:
- S2 は 3ラウンドとも退会側がロックを先取りした（`select_bid` が 409）。逆順
  （`delete=409` / `select=201`）も許容される正解で、判定は「両方成功しないこと」＋
  「退会済み業者に進行中成約が残らないこと」で行っている。
- S3 の「2件まで」はアプリ層のカウント（`MAX_REDUCTION_REQUESTS_PER_TRANSACTION`）が担い、
  **同時**投入に対しては部分一意索引 `uq_reduction_requests_pending` が pending 1件を保証する
  という 2 層構成であることを実挙動で確認した（同時3連投では 201 は1件のみ）。

## 修正（初回実行で検出した実バグ 1件）

**S5 が `[201, 500]` を返した（3ラウンド中2ラウンド）。** データ整合（案件1件）は
0029 の一意制約で守られていたが、2本目のリクエストが 200 ではなく **500** になっていた。

- 原因: `app/api/v1/endpoints/cases.py` の `create_case` で、`IntegrityError` を捕まえた後の
  `await session.rollback()` が **全 ORM インスタンスを失効させる**（`expire_on_commit=False`
  とは無関係にロールバックは常に expire する）。その直後に `user.id` へ触れるため同期の
  遅延ロードが走り、非同期エンジンでは接続チェックアウト（pre-ping）が greenlet の外に出て
  `sqlalchemy.exc.MissingGreenlet` → 500 になっていた。
- なぜ SQLite で出なかったか: aiosqlite ではチェックアウト時に実 IO を伴わず、失効属性の
  再ロードが偶然素通りしていた。**PG 実機でしか出ない典型的なクラス**。
- 修正: commit 前に `user_id = user.id` をプリミティブへ写し取り、except 節では ORM に
  触れない（`bids.py` / `reductions.py` が既に採っている「commit 前にプリミティブへ」規約に統一）。
- 再実行で S5 は `[200, 201]`・`cases=1` に是正。`pytest -q` は **864 passed**（回帰なし）。

## 未解決 / 次にやること

- **同種の「rollback 後の ORM 属性アクセス」が他にも残っている可能性**（静的に見つけた候補）:
  `app/api/v1/endpoints/operator_license.py:146→149`（`operator.id`）、
  `app/api/v1/endpoints/operator_profile.py:470→473`（`operator.id`／退会の409パス）、
  `app/api/v1/endpoints/bids.py:170→176`。いずれも本ラウンドのシナリオでは踏んでおらず未検証。
  次周で `create_case` と同じ「commit 前にプリミティブへ」を横展開し、PG 実機で叩くこと。
- 本チェックは 2〜4 並列・3ラウンドで、勝ち負けの分布までは追っていない（S2 は毎回同じ順序に
  なった）。ロック順序の逆パターンを強制する検証は未実施。
- `alembic upgrade head` は**初回だけ 0008 で失敗し、2回目で自己回復する**のが仕様
  （`alembic/env.py` が `alembic_version.version_num` を VARCHAR(255) へ拡幅する。2026-07 全断の恒久対策）。
  手順に「失敗したらもう一度流す」を明記済み。

## 環境面のメモ（再実行時にハマる点）

- `alembic -c alembic.ini` は Windows 日本語ロケールで `UnicodeDecodeError: 'cp932'` になる。
  alembic は ini を `encoding="locale"` で読むため **`PYTHONUTF8=1` / `-X utf8` では回避できない**
  （PEP 686: `encoding="locale"` は UTF-8 モードの影響を受けない）。
  → `backend/scripts/pg_alembic_upgrade.py`（非 ASCII を落とした一時 ini を `-c` で渡す）を用意した。
- Docker Desktop が `%LOCALAPPDATA%\Docker\run\dockerInference` と
  `%LOCALAPPDATA%\docker-secrets-engine\engine.sock` の**孤児 unix ソケット**で起動時クラッシュしていた
  （`backend crashed: initializing Inference manager / Secrets Engine: ... remove ...: The file cannot be
  accessed by the system`）。当該ディレクトリを退避（`*.stale-<epoch>` にリネーム）して復旧。
  プロセスを force kill するとまた孤児が残るため、**復旧後は force kill しない**こと。
  併せて `%APPDATA%\Docker\settings-store.json` の `EnableDockerAI` を `false` にした（要ユーザー確認・戻して可）。
