# backend 実装報告: 評価の2択化（P1・P2）— 2026-09-25（第2版: レビュー指摘対応・0040/0041 への振り直し）

## 結論
- DESIGN.md の (1)(2)(3)(6) のうち backend 分、レビュー指摘 1〜4、追加依頼 A〜D をすべて実装した。
- pytest の結果（最終）:
  - 共有ツリー（P1＋P2）: **1412 passed / 0 failed**。head は 0041 の1本。
  - HEAD＋P1 だけのコピー（旧アプリコードのまま）: **1396 passed / 0 failed**。
- 指示の前提と違った点が1つある。0004 が作る rating の CHECK の実名は、命名規約で `ck_reviews_ck_reviews_rating` になる（二重接頭辞）。「0004 の実名と一致」を優先してこの名前をモデルに宣言し、オフライン DDL との一致をテストで固定した（下の第2回・3）。

## 変更ファイル（最新）
### P1（マイグレーションとテストのみ。旧アプリコードのまま全件緑を確認済み）
- `backend/alembic/versions/0040_review_verdict.py`（新規。旧 0039_review_verdict を振り直した。revision は19字、down_revision=`0039_sessions_revoked_at`。ロジックは変えていない）
- `backend/tests/test_0040_review_verdict_migration.py`（新規。stamp 先は 0039_sessions_revoked_at。head の固定はしない）
- `backend/tests/test_0036_email_notify_opt_in_migration.py`（docstring 1行。head を検証する場所を「最新番号のテスト」と書いた）
- `backend/tests/test_0039_sessions_revoked_at_migration.py`（162行目だけ。`get_heads() == [_REVISION]` を「移設した旨のコメント＋`len(...) == 1`」に置き換えた）
### P2（アプリコードと、ずれ補正のマイグレーション）
- `backend/alembic/versions/0041_review_verdict_recount.py`（新規。revision は27字、down=`0040_review_verdict`。データ是正のみで DDL は使わない）
- `backend/tests/test_0041_review_verdict_recount_migration.py`（新規。`get_heads() == ["0041_review_verdict_recount"]` をここで固定）
- `backend/tests/test_review_model_constraints.py`（新規。モデルの制約名と 0004 のオフライン DDL の一致を検査）
- `backend/app/db/models/transaction.py`・`backend/app/db/models/operator.py`・`backend/app/schemas_katadzuke.py`・`backend/app/api/v1/endpoints/reviews.py`・`backend/app/services/review_stats.py`・`backend/app/api/v1/endpoints/operator_profile.py`・`backend/app/api/v1/endpoints/admin.py`（docstring のみ）
- `backend/tests/test_katadzuke_api.py`・`backend/tests/test_deleted_operator_token_revocation.py`
- 削除: 未コミットだった `0039_review_verdict.py` と `test_0039_review_verdict_migration.py`（振り直しで置き換えた）

## pytest 結果の推移
| 時点 | 対象 | 結果 |
|---|---|---|
| 第1回 P1 | HEAD＋P1（旧番号 0039） | 1270 passed |
| 第1回 P2 | HEAD＋P1＋P2 の隔離コピー | 1281 passed |
| 第2回 対象テスト | 移行系6ファイル＋test_katadzuke_api＋revocation | 126 passed |
| 第2回 P1 のみ | HEAD（624face 以降）＋P1 の4ファイル | **1396 passed / 0 failed** |
| 第2回 全件 | 共有ツリー（P1＋P2。別セッションの未コミット変更なし） | **1412 passed / 0 failed** |
- 差の16件は P2 の新規テスト（test_katadzuke_api の13件、0041 の2件、制約名の1件）。

## 第2回（レビュー指摘への対応）
1. **reviews.py の assert を廃止した**。`if verdict / elif rating / else` にし、else は 422「評価（よかった／伸びしろ）を選んでください。」を返す（python -O で assert が消えても素通りしない）。
2. **try が flush・集計・commit を囲むようにした**。IntegrityError は rollback して 409「既にレビュー投稿済みです。」を返し、あわせて WARNING `review_create_conflict transaction=… reviewer_type=… error=<ドライバの例外名>` を出す。例外の本文には SQL のパラメータ（口コミ本文）が含まれうるため、ログに出さない。rollback すると ORM の属性が失効するので、ログにはリクエスト値とローカル変数だけを使っている。
   - **取引行のロックは採用した**（`lock_transaction_rows`: Case → Transaction。減額申請・完了・キャンセルと同じ規約）。理由と影響はコード内のコメントに残した。
     - ロック後に読み直すため、二重送信の後発はアプリ層の 409 になる。
     - 集計の業者行ロックはその後に取るので、順序は Case → Transaction → Operator になる。transactions.cancel と同じ順序なので、新たなデッドロックは作らない。
     - SQLite は FOR UPDATE を出力しないため、テストの挙動は変わらない。
     - ロックを取らない書き手（デプロイ切替中の旧コード）と重なった場合は、一意制約から 409 になる。
3. **Review モデルの `__table_args__` に制約を宣言した**。命名規約の自動変換を受けないよう、3つとも `conv()` で名前を確定させている。
   - `UniqueConstraint("transaction_id","reviewer_type", name=conv("uq_reviews_transaction_reviewer"))`
   - `CheckConstraint("rating >= 1 AND rating <= 5", name=conv("ck_reviews_ck_reviews_rating"))`
   - `CheckConstraint("verdict IN ('good','improve')", name=conv("ck_reviews_verdict"))`
   - **判明したこと**: 0004 を `--sql`（PostgreSQL 方言）でオフライン生成すると、0004 の CHECK は全て `ck_<表>_ck_<表>_<名>` になる（reviews の rating / reviewer_type、bids / cases / transactions / reduction_requests / cancellations の各 CHECK）。原因は2つある。alembic の op も target_metadata の命名規約を使うこと。命名規約は初回コミット（2026-05-26）からあり、0004（06-12）より前だったこと。一意制約・FK・PK は規約に constraint_name トークンが無いため、書いた名前のまま作られる。
   - 本番の実名も同じである可能性が高い [要確認]。確認用の SQL: `SELECT conname FROM pg_constraint WHERE conrelid = 'reviews'::regclass;`
   - 0042 への影響: 既存の CHECK を落とす・作り直すときは、実名を `op.f()` で渡すこと。0040 が作った `ck_reviews_verdict` も `op.f("ck_reviews_verdict")` で扱うこと。素の文字列を渡すと、名前がさらに二重化する。
4. **テストを追加した**（test_katadzuke_api.py）。
   - (a) T6 に★3 の行（verdict 列 NULL）を足した。SQL 側の式が CASE の else 分岐で improve を返すことを、`select(Review.verdict)` の実値と集計 (1,1,2) の両方で確認している。
   - (b) T3 に `{"verdict":"good","rating":9}` → 422 を追加した。
   - (c) T2 で `review_legacy_rating_payload transaction=… reviewer_type=user rating=…` の INFO を caplog で固定した。T3 では、verdict のある投稿がこのログを出さないことを固定した。
   - (d) `test_operator_to_user_legacy_rating_only_payload` を追加した。業者→依頼者の★3（rating のみ）が improve で保存され、rating は3のまま残る。ログは reviewer_type=operator で出て、業者の集計には入らない。
   - (e) `test_review_unique_violation_at_flush_returns_409_and_leaves_nothing` を追加した。before_flush で同じ評価を割り込ませ、SQLite の本物の一意制約違反を flush 時に起こす。確認内容は、409、conflict ログ、ロールバック後に評価0件・集計 (0,0,0) のままであること、その後の正常投稿が通ること。
5. **振り直し（A〜C）**
   - 0039 → 0040、0041 の新設、番号の付け替えを行った。コメントの「評価の2択化＝0040」「contract＝0042」、テスト名 `…_until_0042` を含む。
   - 別セッションの 0039（sessions_revoked_at）を指す記述は変えていない。

## 0041_review_verdict_recount の要点
- R0: PostgreSQL のみ `SET LOCAL lock_timeout = '10s'` を設定する。
- R1: verdict が NULL の行を 0040 の U2 と同じ式で補完する。
- R2: good / improve / review_count のいずれかが再計算値とずれている業者を数える。
- R3: 全業者を相関サブクエリで再計算する。母集団は review_stats と同じで、verdict は `COALESCE(r.verdict, ★由来)` で数える。
- R4: INFO「0041: verdict が未設定だった評価を N 件補完しました（…）。業者 M 件の集計を再計算（件数のずれの補正 f 件）。」を出し、f>0 なら WARNING も出す。
- 閾値の4は int 定数を SQL に直接埋め込んでいる。1つの文の中で同じ値を何度も参照するため、名前付きパラメータを使い回すと asyncpg の paramstyle に依存する。それを避けるための選択で、外部入力は混ざらない。
- 集計の相関サブクエリでは、reviews 側の列を必ず `r.` で修飾している（operators にも rating 列があるため）。
- テストで確認した内容: 補完4件・補正2件・WARNING が出ること。★の値が不変であること。整合済みの業者の値が変わらないこと。downgrade が no-op であること。2回目は補完0件・補正0件で WARNING が出ないこと。

## 設計から逸れた点（第1回からの継続分を含む）
1. CHECK の名前は `op.f()` と `conv()` で確定させた。命名規約で名前が二重化するため（上記の3）。
2. rating の CHECK の名前は、指示にある `ck_reviews_rating` ではなく、実際に作られる `ck_reviews_ck_reviews_rating` にした（上記の3）。
3. 集計は1クエリにまとめ、★平均も同じクエリで取る（2クエリ構成）。
4. 設計に無い最小の追加が2つある。旧形式の証跡ログ（INFO）と、競合の記録（WARNING）。
5. T7 は業者行を DB に直接作る。GET /vendors の並び替え用の索引は追加していない（稼働中の業者だけが対象で件数が小さいため）。
6. SQLite の batch では、名前付きの CHECK・FK は残る。ただし FK 句の途中に改行があると、SQLite の読み取り（反映）が名前と ON DELETE を落とす。テストのスキーマは1行で書いた。

## 未解決・申し送り
1. [要確認] 本番の制約の実名。上の SQL で確かめる。`ck_reviews_rating` だった場合は、モデルとテストの期待値をその名前に直す。
2. デプロイの切替中に残る隙間 [推測]: 0041 を適用してから旧インスタンスが止まるまでの間に旧コードが書いた行は、次の投稿か非表示の操作で直る。0042 で NOT NULL にする前に、0041 と同じ補完と再計算をもう一度流すこと。
3. docstring が実態と合わなくなった箇所が2つある。どちらも別セッションの管理ファイルなので、指示どおり触っていない。
   - `test_0037_0038_migrations.py`: head を検証する場所として `test_0039_sessions_revoked_at_migration.py` を挙げている。
   - `test_0039_sessions_revoked_at_migration.py`: 関数の docstring が「単独の head として」と書いている。
4. PostgreSQL での実行は未検証 [要確認]。SQL は標準の構文だけで書いている。P1 と P2 の各デプロイ後、Render のログで「0040: reviews.verdict を…」「0041: …補完…補正…」の件数を確認すること。
5. reviewer_type の CHECK（実名 `ck_reviews_ck_reviews_reviewer_type`）はモデルに宣言していない（依頼の範囲外）。同じ方法ですぐに足せる。
6. `alembic heads` の CLI は、この環境では alembic.ini を cp932 で読むため使えない。head は ScriptDirectory とテストで確認した。

## 第3回（QA 再レビュー Low 2点・セキュリティ差分 Low-1/Low-2）— 最終
- **作業場所**: 編集もテストも本体ツリー `C:\Users\ko13h\Claude\Projects\ソクウリ\backend` で行った。検証用の worktree（`.claude\worktrees\review-verdict`）は照合のために読んだだけで、編集していない。照合の結果、中身は本体と同一で、transaction.py の改行コードだけが違った。
- **pytest（本体ツリー）**:
  - 対象の8ファイル: 129 passed。
  - 全件（`PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest -q`）: **1415 passed / 0 failed**。
  - P1 のファイルは今回変えていないため、第2回の「HEAD＋P1 のみで 1396 passed」はそのまま有効。
- **変更ファイル**: すべて P2 に入る（`0041_review_verdict_recount.py`・`test_0041_review_verdict_recount_migration.py`・`reviews.py`・`test_katadzuke_api.py`）。

### QA Low
1. **0040→0041 の連続適用** — `test_0040_then_0041_in_one_upgrade_leaves_0040_results_unchanged` を test_0041 側に追加した。
   - 手順: stamp 0039_sessions_revoked_at → 1回の upgrade で 0040 と 0041 を続けて流す。
   - 確認: ログの順が 0040 INFO → 0040 WARNING（ずれの補正）→ 0041 INFO（補完0件・再計算0件・更新0件）であること。値が 0040 の変換結果のままであること。
   - upgrade の目標は、指示の head ではなく `0041_review_verdict_recount` を明示した。0042 以降が足されても、このテストが確かめる範囲を 0040→0041 に保つため。
2. **明示の 422 分岐** — `test_create_review_rejects_payload_bypassing_validator_with_explicit_422` を追加した。`ReviewCreateRequest.model_construct(verdict=None, rating=None)` で create_review を直接呼び、HTTPException(422)・文言・行が作られないことを固定した。

### セキュリティ Low-1（0041）
- PostgreSQL のときだけ、R0 の `SET LOCAL lock_timeout = '10s'` の直後、R1 より前に `LOCK TABLE reviews IN SHARE MODE` を取るようにした。
  - ロック順は reviews → operators で、旧コードの投稿・非表示と同じ順。
  - 自分の R1 の UPDATE は同じトランザクションなので衝突しない。
  - 読み取りは止めない。
  - 理由は docstring に書いた。あわせて「表ロックを取らない」という旧記述を訂正した。
- R2 と R3 は同じ条件 `_DRIFTED_OPERATOR_SQL` を使い、R3 は `WHERE` でずれている業者だけを更新する。
- ログの文言を「件数がずれていた業者 N 件の集計を再計算しました（更新 M 件）」に変えた。「更新」は R3 で実際に書き換えた行数。
- テストで確かめたこと:
  - Engine の before_cursor_execute で実行された SQL を捕捉し、SQLite では LOCK TABLE と lock_timeout が出ないこと（捕捉できていることも確認）。
  - トリガーで更新された業者行を記録し、ずれていない業者の行は UPDATE されないこと。2回目は更新が0件であること。
  - 期待するログ文言も更新した。

### セキュリティ Low-2（reviews.py）
- 処理を次の順に変えた。
  - (1) ロックの前に、ロック無しの軽量照会（`select(Case.user_id, Bid.operator_id, Transaction.status)` の1クエリ）で 404 → 403 → 409（未完了）を返す。
  - (2) `lock_transaction_rows` でロックする。
  - (3) `populate_existing=True` で読み直し、同じ判定と重複判定をやり直す。
- 判定は `_reviewer_type_if_allowed()` に1本化し、ロックの前後で同じ判定・同じ文言・同じ順序を使う。transactions.py には触れていない。
- `test_review_non_party_and_invalid_state_return_before_taking_the_lock` を追加した。ロック関数を monkeypatch で観測し、次を固定した。
  - 第三者（依頼者・業者）の 403、存在しない取引の 404、未完了の 409 ではロックを取らない。
  - 当事者の投稿ではロックを1回だけ取る。

### Low-3
- 現状維持（IntegrityError はすべて 409）。

### 残り
- [要確認] 実際の PostgreSQL での表ロックの挙動（待ち・lock_timeout）は、この環境では検証できない。P2 デプロイ時に Render のログで「0041: …」が出ていることと、ロック待ちでの失敗が無いことを確認する。
- 0041 の実行中（数ms〜、既に書き込み中のトランザクションを待つ場合は最大 lock_timeout の 10s）は、口コミの投稿・非表示が待たされる。
