# r12 backend 修正 第2弾（High 3 / Medium / Low / 横展開）— 2026-09-06

結論: r12-review の backend 指摘（H-1/H-2/H-3・M-5/M-6/M-7/M-8・L-1/L-3）を全て修正し、
PG 同時実行検証で見つかった「rollback 後の ORM 属性参照」を 6 箇所へ横展開した。
pytest 867 passed（従来 864 + 新規 3）。web/ は別担当のため未着手。

## H-1 デプロイ直後の一斉通知（0033 の埋め戻し＋窓＋LIMIT）
- `alembic/versions/0033_reminder_marks.py`: `upgrade()` 末尾に `_backfill_existing_rows_as_sent()` を追加。
  - `transactions`: `overdue_reminded_at IS NULL AND visit_date IS NOT NULL AND visit_date < 今日(JST)` → 適用時刻でマーク。
  - `cases`: `no_bid_reminded_at IS NULL AND status='open' AND created_at < now-3日` → 適用時刻でマーク。
  - ダイアレクト依存関数（PG `now()` / SQLite `datetime()`）を使わず、Python 側で確定した値を
    **型付き `sa.column`** 経由のバインドで渡す（SQLite の DateTime/Date バインド処理が効く＝両対応）。
  - 索引作成の**後**に UPDATE（部分索引に乗せる）。将来対象になりうる行（未来の訪問日・入札済み・作成直後）は NULL のまま。
- `app/services/reminders.py`: `REMINDER_LOOKBACK_DAYS=14` / `REMINDER_BATCH_LIMIT=200` を導入。
  - 訪問日超過: `今日(JST)-14日 <= visit_date < 今日(JST)`。入札ゼロ: `作成 3〜17 日前`。いずれも `order_by ... limit(200)`。

## H-2/M-5 claim → commit → 通知
- 抽出を `UPDATE ... WHERE reminded_at IS NULL AND id IN (SELECT ... ORDER BY ... LIMIT 200) RETURNING id` に変更。
  外側 WHERE にも `reminded_at IS NULL` を残し、同時実行の相手が先にマークした行を UPDATE 時点の再評価で弾く。
- claim を **commit してから** 宛先をプリミティブ値で読み出し（`_load_overdue_targets` / `_load_no_bid_targets`）、
  読み取り Tx も commit で閉じてから通知（外部 HTTP をトランザクション内で待たない）。
- 通知失敗は `_dispatch_or_warn` が捕捉 → 構造化ログ + `alerts.send_alert(severity="warning", key="reminder_dispatch_failed")`。
  マーカー確定済みのため**再送しない**（同じ催促が何通も飛ぶ害 > 1通の取りこぼし）。運用再送は列を NULL に戻す。

## H-3 依頼者向けリンク
- `line_notify.push_visit_overdue` / `notify.send_visit_overdue` の依頼者側 URL を `/transactions/{id}` → `/chat/{id}`。
  web に `/transactions/{id}` は無く 404 だった（r10 O-H-1 の統一から漏れていた唯一の箇所。業者側 `/operator/transactions/{id}` は現状維持）。

## M-6 / M-7 / M-8 / L-1 / L-3
- M-6: `Settings._clamp_reminder_interval_seconds`（`config.py`）で 60 秒未満を 60 へクリップ＋warning ログ。
  起動失敗にはしない（補助機能の設定ミスで API 全体を落とさない）。`config.py` に `logger` を追加。
- M-7: `docs/ops/admin-operations.md` に「自動リマインド」節（対象・毎時/起動直後・14日窓/200件・手動 `POST /admin/jobs/reminders`・
  キルスイッチは Render ダッシュボードの `REMINDERS_ENABLED`（render.yaml は既存サービスへ同期されない）・spin-down 中は走らない・再送方法）。
- M-8: `docs/TODO.md` 01-8(a) の前提を「r12 で他社の入札額は業者に非開示。業者に見えるのは入札件数と自社入札のみ」に更新。
- L-1: `GET /files/{key}` は未承認/停止業者トークンなら **key の素性に関わらず 403**（案件写真判定の DB クエリを削除＝オラクル解消・O(1) 化）。
- L-3: 新テスト2本（下記）。

## 横展開: rollback 後の ORM 属性参照（MissingGreenlet 同型）
| 箇所 | 結果 |
| --- | --- |
| `operator_license.py:146-149` | **バグ有り→修正**。`operator_id = operator.id` を commit 前に写し取り、except 節のログはそれを使う。 |
| `operator_profile.py:470-473`（退会 409 経路） | **問題なし**。rollback 直後に raise しているのはモジュール定数 `_OPERATOR_DELETE_ACTIVE_TRANSACTION` で ORM に触れない。ただし同関数 488-491（commit 失敗経路）に同型バグが有り、`deleted_operator_id` を写し取る形へ修正。 |
| `bids.py:170-176` | **問題なし**。rollback 後は静的 detail の 409 を raise するのみ（`await session.refresh(bid)` 以降は成功経路）。変更なし。 |

全 25 箇所の `session.rollback()` を機械的に走査し、同型を追加で 4 箇所発見・修正:
`users.py:300/346/707`（口座 PUT/DELETE・退会）、`user_identity.py:305`。いずれも rollback 後に `user.id` を参照していた
（発生時は本来の例外がログに残らないまま MissingGreenlet で 500 になる）。

## 変更ファイル
- backend: `app/services/reminders.py`（全面改稿）、`alembic/versions/0033_reminder_marks.py`、`app/config.py`、
  `app/services/line_notify.py`、`app/services/notify.py`、`app/api/v1/endpoints/case_photos.py`、
  `app/api/v1/endpoints/operator_license.py`、`operator_profile.py`、`users.py`、`user_identity.py`
- tests: `tests/test_r12_backend_fixes.py`（+2）、`tests/test_0033_reminder_backfill.py`（新規）
- docs: `docs/ops/admin-operations.md`、`docs/TODO.md`

## テスト
- 新規: 0033 の埋め戻し回帰（過去分は埋まる／未来・入札済み・作成直後は NULL のまま・部分索引の実在）、
  pending + JST 境界 + 遡り窓（`visit_date == today_jst` は対象外・`-1日` は対象・`-15日` は対象外）、
  claim 先行の実証（dispatch の内側から DB を読み、その時点でマーカー確定済みであることを検証）＋通知失敗でも再送しない＋warning アラート発火。
- `pytest -q` → **867 passed**（4分42秒）。alembic は単一ヘッド 0033 のまま（新規リビジョン無し）。

## 未対応 / 申し送り
- `/files` は依然として無認証 capability URL（署名付き短命 URL 化は別タスク）。
- spin-down 中にリマインドが走らない点は文書化のみ（外部 cron からの `POST /admin/jobs/reminders` は未設計）。
- 通知失敗分の**自動**再送は無い（設計判断）。運用は DB 列を NULL に戻す手動作業。
- `users.py:54` の `from app.services import notify` が未使用（ruff F401）。本タスク前から存在する指摘で、
  並行作業との衝突を避けるため未修正。リポジトリ全体では ruff 34 件（大半がテストの未使用 import）で、今回の変更による増加は 0。
- web 側（M-1〜M-4・L-2・L-4）は別担当。
