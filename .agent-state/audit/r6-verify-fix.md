# r6 修正の独立検証（自己申告 vs 実コード）— 2026-09-05

対象コミット: `1b72a06`（作業ツリーは tracked file の差分なし＝申告された修正は全てこのコミットに含まれる）。
実測: `.venv/Scripts/python.exe -m pytest -q tests/test_0028_migration_dedup.py tests/test_case_ai_background.py` → **13 passed / 0 failed（5.27s）**。

## 総合判定: 条件付き合格（Critical 0 / High 0 / 新規 High 0）。High 3 件のうち H2・H3 は塞がった。H1 は**一部**。

---

## (1) H1 — web のページング追随: **一部**

塞がった:
- `web/src/lib/katadzuke-api.ts:1430-1443` に `LIST_DEFAULT_LIMIT=100` / `LIST_MAX_LIMIT=200` / `buildListPageQuery()` を新設。`listOpenCases`（同:1450-1452）・`listTransactions`（同:1534-1536）が常に `?limit=&offset=` を送る。backend 既定（`backend/app/api/v1/endpoints/cases.py:80-81` の 100/200）と一致。
- 「さらに読み込む」4 画面: `web/src/app/operator/cases/page.tsx:137-148,253-258`（offset=`cases.length`・`disabled={loadingMore}`・終端で非表示）、`web/src/app/operator/page.tsx:332-356,560-566,626-632,669-675`、`web/src/app/operator/transactions/page.tsx:54-63,126-131`。終端判定はいずれも `res.length === LIST_DEFAULT_LIMIT`（＝ちょうど 100 件時に1回空振りするだけで欠落はしない）。
- `/mypage` の集計は全件取得になっている: `web/src/app/mypage/page.tsx:184-190` が `LIST_MAX_LIMIT=200` 刻みで最大20ページ（4000件）まで回し、`res.length < LIMIT` で break。安全上限があり無限ループしない。

塞がっていない（申告どおり範囲外だが H1 の本体と同型の欠陥が残る）:
- `web/src/app/chat/[id]/page.tsx:128`、`web/src/app/operator/chat/[id]/page.tsx:122`、`web/src/app/notifications/page.tsx:127`、`web/src/app/schedule/page.tsx:98`、`web/src/app/mypage/withdraw/page.tsx:103`、`web/src/components/kdz/AppHeaderBell.tsx:81` は `listTransactions(token)` 引数なし＝`limit=100` 固定のまま。r6-review の **L5（未読ベルの数え落とし）は未解消**。
- ただし退会ガード自体は backend 側の COUNT（`backend/app/api/v1/endpoints/users.py:609-615`）で担保されており、`mypage/withdraw` の 100 件上限は**表示件数のみ**に影響する（実害 Low）。

フィルタとの併用: `operator/cases` の絞り込みは読込済み範囲が対象である旨を明記済み（同:123）。重複・欠落は下記 N3 を参照。

## (2) H2 — pending 放置の回収: **塞がった**

- 遅延回収 `_reap_stale_pending_ai`（`backend/app/api/v1/endpoints/cases.py:97-128`）と起動時スイープ `sweep_stale_pending_ai`（同:131-150）。窓は `_AI_STALE_PENDING_WINDOW = 10分`（同:89）、reason は `"stale"`（同:90）。
- **tz の扱いは正しい**: `_as_utc()`（同:92-94）が SQLite の naive `created_at` を UTC aware に補正してから比較する。起動時スイープは SQL 側の `Case.created_at < cutoff` 比較で、PG は timestamptz・SQLite は naive UTC のため実質一致する。
- **依頼者以外との一貫性は問題なし**: `ai_status` を返すのは `CaseOut` のみ（`backend/app/schemas_katadzuke.py:610`）。`CaseMaskedOut`（同:618-）は持たず、admin 側も `admin.py` に `ai_status` の参照が 0 件。よって回収を依頼者分岐（`cases.py:511-513`・`cases.py:552-554`）に限定したのは**正しい設計判断**であり、業者・admin から pending が見えることはない。
- **起動を止めない**: `backend/app/main.py:51-68` が `try/except Exception` で全例外を握り潰しログのみ。`lifespan` は `asyncio.create_task`（同:83）で fire-and-forget、`yield` 前に await しない＝スイープが遅延・失敗しても起動は完了する。
- `expire_on_commit=False`（`backend/app/db/session.py:49`）のため、GET 中の `session.commit()` 後も eager load 済み関連が失効せず MissingGreenlet は起きない（この修正の隠れた前提条件だが実際に満たされている）。
- 回帰テスト実在: `backend/tests/test_case_ai_background.py:312`（GET/一覧の遅延回収）・同:375（起動時スイープが stale のみ回収）。

## (3) H3 — 0028 の重複行での停止: **塞がった**

- `_assert_no_duplicates`／`RuntimeError` は消滅。`backend/alembic/versions/0028_txn_state_integrity.py:60-79`（`_dedupe_cancellations`: `ROW_NUMBER() OVER (PARTITION BY transaction_id ORDER BY created_at ASC, id ASC)` で最古1行残し DELETE）・同:82-104（`_reject_duplicate_pending_reductions`: 最古以外を rejected へ UPDATE）。件数はいずれも `logger.info` に出力。
- **PG / SQLite 両対応**: ウィンドウ関数は SQLite 3.25+ / PG 双方が解する。`op.batch_alter_table("cancellations")`（同:130-133）は SQLite でのみコピー＆リネームへ切り替わり PG では通常の `ALTER TABLE ADD CONSTRAINT` のまま＝両対応として正しい使い方。部分一意索引は `postgresql_where` と `sqlite_where` を併記（同:141-142）。
- **downgrade も対称**（同:151-157）: index 2 本を drop し、`batch_alter_table` 経由で `drop_constraint(type_="unique")`。ただし downgrade は一度も実行検証されていない（下記 R4）。
- **`tests/test_0028_migration_dedup.py` は実際に upgrade を回している**: `command.stamp(cfg, "0027_case_ai_status")` → `command.upgrade(cfg, "0028_txn_state_integrity")`（同:99-121 相当）を実行し、その後 raw sqlite3 で「最古1行のみ残存」「重複 pending が rejected」「`uq_reduction_requests_pending` / `ix_transactions_bid_id` の実在」「3件目 INSERT が IntegrityError」を検証。**モックではなく実マイグレーション実行**であることを確認済み（実測 13 passed）。
- ただし 0001〜0027 の実チェーンは回しておらず、`cancellations` は FK・他カラムを削ぎ落とした合成スキーマ（同ファイルの `_PRE_0028_SCHEMA_SQL`）。本番 PG での実行は未検証（R1）。

## (4) Medium 7 件の対応状況

| # | 判定 | 根拠 file:line |
|---|---|---|
| M1 認可前ロック | **未対応** | `backend/app/api/v1/endpoints/transactions.py:301,303` / `:342,344` / `:580,582` — `_lock_txn_rows` が `_assert_party` より前のまま。3遷移とも順序不変。 |
| M2 idempotency_key の DB 一意制約 | **未対応** | `backend/app/db/models/case.py:94` は `index=True` のみ（unique なし）。0027 も `create_index(..., unique=False)`。同時2リクエストで2件作成は残る。 |
| M3 /readyz の config 無認証開示 | **未対応** | `backend/app/main.py:308-309` が `config` / `degraded_config` を無認証 payload に含める。同:288 のコメントが「無認証で読める」と自認したまま。 |
| M4 状態不変時の重複通知 | **未対応** | `backend/app/api/v1/endpoints/admin.py:356-369`（verified 前値を退避せず常に add_task）・同:394-404（`if not body.suspended` のみで前値比較なし）。 |
| M5 誤ったコメント | **未対応** | `backend/app/api/v1/endpoints/reductions.py:106` に「部分一意索引は PostgreSQL 専用で SQLite のテストでは発火しない」が残存。0028:141-142 の `sqlite_where` と矛盾。 |
| M6 アラート抑制の永続化 | **未対応** | `backend/app/config.py:96` は `alert_cooldown_seconds: int = 600` のまま、`backend/app/services/alerts.py:153` はプロセス内 dict 比較のまま。 |
| M7 再試行時の孤児 storage オブジェクト | **対応不要（レビュー側の誤検知）** | `web/src/app/create/page.tsx:379-390,400-405` が `photo.uploadedKey` をキャッシュし `if (!key)` のときだけ再アップロードする。`git show HEAD~1` でも `uploadedKey` は5箇所存在＝r6 以前からの既存実装で、レビューの前提「再試行はアップロードからやり直す」が事実と異なる。 |

対応不要と判断してよいもの: **M7 のみ**（実装が既に要件を満たしているため）。M1〜M6 は実害の説明が成立しており、未対応のまま残っている。

## 新規回帰

High 以上: **0 件**。以下は新規に持ち込まれた Medium。

- **N1（Medium）** `backend/app/main.py:81,83` — `asyncio.create_task()` の戻り値を保持していない。イベントループはタスクへ弱参照しか持たないため、実行途中で GC され黙って消えうる。**同じ差分の `backend/app/services/alerts.py:44,183-185` では明示的に強参照を保持してこの問題を潰しており**、起動スイープだけ同じ罠を再導入している。実害: H2 の (b) 経路が無言で不発になりうる。
- **N2（Medium）** `web/src/app/operator/page.tsx:626-632,669-675` — 「交渉中」「成約済み」の2タブが同一の `hasMoreTxns` / `loadMoreTxns` を共有する。片方のタブで押した追加読み込みが全て他方のステータスだった場合、行が1件も増えないのにボタンだけ残り「押しても何も起きない」ように見える。
- **N3（Medium）** offset ページングの窓ずれ — `backend/app/api/v1/endpoints/cases.py:521-525` は `created_at desc, id desc` で安定順序だが、ページ1取得後に新規案件が挿入されると offset が1件ずれ、100件目がページ2で**重複表示**される（React の key 重複）。逆に案件が削除・成約されると1件**欠落**する。総件数を返していないため web 側では検知不能。

## 未解決リスク

1. **0028 は PostgreSQL で一度も実行されていない。** テストは FK も他カラムも無い合成 SQLite スキーマ（`backend/tests/test_0028_migration_dedup.py` の `_PRE_0028_SCHEMA_SQL`）。本番 `cancellations` は `case_id` / `transaction_id` の FK を持つ実テーブルであり、`DELETE` が RESTRICT 系 FK に触れないことも、`ALTER TABLE ADD CONSTRAINT` が長時間 ACCESS EXCLUSIVE ロックを取らないことも未実証。r6-review H3 の事前確認 SQL 2本は依然未実行。
2. **`backend/start.sh:52-63` の「alembic 3回失敗しても uvicorn を起動する」は未変更。** 0028 が RuntimeError で止まらなくなっただけで、別の理由（ロック競合・権限・接続断）で 0028 が落ちれば依然として「制約が無いのに起動する degraded 状態」に入る。H3 の根本原因のうち*停止しない側*は塞がっていない。監視は `/readyz` の `expected_head` 不一致のみが頼り。
3. **`web/src/app/cases/[id]/page.tsx:272-289` のポーリングは 180 秒で打ち切るが、遅延回収の窓は 10 分。** その差の約7分間、画面は `ai_status="pending"` のまま「この画面は自動で更新されます」（同:548-553）と表示し続けるが実際には更新されない＝**文言が事実と食い違う**。r6-review が提案した「180 秒到達時の『更新する』ボタン」は未実装で、手動リロード以外の回復導線がない。
4. **0028 の downgrade は一度も実行されていない。** SQLite での `batch_op.drop_constraint("uq_cancellations_transaction_id", type_="unique")` は、コピー＆リネームで張られた制約名が `PRAGMA index_list` 上 `sqlite_autoindex_*` になる（テスト自身が同ファイルのコメントで認めている）ため、名前解決に失敗して落ちる可能性がある。ロールバック手段が机上のままである点は変わらない。
5. **r6-review の未解決リスク 1〜3（PG 同時実行の実測 / DB_POOL_SIZE の妥当性 / AI 120秒デッドラインと Gemini セマフォの相互作用）は本修正で一切触れられておらず、そのまま残存。** 特に N3 の窓ずれと 1 の PG 未実測が重なるため、「ページングが本番で正しく動くこと」は現時点で実証されていない。
6. **`next build` は依然未実行**（r6-review 未解決リスク5）。今回追加した「さらに読み込む」4画面は tsc / eslint のみの検証で、実ブラウザでの動作は未確認。

## サマリ

⚠️ 条件付き合格。H2・H3 は実コードで塞がっており、回帰テストがモックでなく実マイグレーション／実 GET を通していることを実測（13 passed）で確認した。H1 は主要4画面で塞がったが、通知・スケジュール・チャット・未読ベルの6箇所は 100 件上限のまま（L5 未解消）。新規 High 0、新規 Medium 3（起動タスクの弱参照、タブ間で共有された追加読み込み、offset 窓ずれ）。Medium 7 件のうち実質未対応は M1〜M6 の6件で、M7 のみレビュー側の誤検知。**本番デプロイのブロッカーは 0028 の PG 事前確認 SQL 未実行（未解決リスク1）が残る。**
