# backend 実装報告: 0042 contract（★の撤去・評価の2択化の後片付け）— 2026-09-25

## 結論
- DESIGN-0042.md の段A（マイグレーション 0042）と段B（コード）を実装した。作業は worktree `C:\Users\ko13h\Claude\Projects\ソクウリ\.claude\worktrees\rv-0042`（ブランチ feat/review-verdict-contract・起点 1f9bdcf）の中だけで行った。本体ツリーは編集していない。git 操作もしていない。
- pytest の結果:
  - 段A（アプリコードは未変更）: **1432 passed / 0 failed**
  - 段B: **1429 passed / 0 failed**
- 実行方法: 本体の venv（`C:/Users/ko13h/Claude/Projects/ソクウリ/backend/.venv`）を使い、worktree の backend から `TZ=Asia/Tokyo PYTHONUTF8=1` を付けて実行した。`import app` が worktree 側（`.claude\worktrees\rv-0042\backend\app`）に解決されることは最初に確認した。

## 段A のファイル（マイグレーションとテストのみ。現行コード 1f9bdcf と両立する）
- `backend/alembic/versions/0042_review_verdict_contract.py`（新規。revision は28字、down=`0041_review_verdict_recount`。app は import しない）
  - PostgreSQL のみ: `SET LOCAL lock_timeout = '10s'` → `LOCK TABLE reviews IN ACCESS EXCLUSIVE MODE`。upgrade と downgrade で共通のヘルパーにした。
  - R1: verdict が NULL の行を補完する。
  - R2: batch で verdict を NOT NULL、rating を NULL 可にする。
  - R3: 0041 と同じく、ずれている業者だけを再計算する（verdict は素の列で数える）。
  - INFO「0042: verdict を N 件補完し NOT NULL 化、rating を NULL 可に変更。件数がずれていた業者 M 件を再計算（更新 K 件）。」を出し、M>0 なら WARNING も出す。
  - downgrade: rating が NULL の行を互換値（good=5／improve=2）で埋めてから、rating を NOT NULL、verdict を NULL 可へ戻す。件数は INFO に出す。
- `backend/tests/test_0042_review_verdict_contract_migration.py`（新規・2テスト）
  - 事前スキーマの制約名は本番の実名（`ck_reviews_ck_reviews_rating` 等）にした。
  - 確認内容:
    - NULL の verdict が補完されること。
    - PRAGMA で verdict が NOT NULL、rating が NULL 可になること。
    - 表の作り直し後も名前付き制約・FK（CASCADE）・索引が残ること。
    - verdict が NULL の INSERT は拒否され、段B 形式（rating NULL）の INSERT は通ること。
    - ずれていない業者の行が UPDATE されないこと（トリガーで記録）。
    - SQLite では LOCK TABLE と lock_timeout を発行しないこと（SQL を捕捉して確認）。
    - INFO と WARNING が出ること。
    - downgrade で段B の行が 5 と 2 で埋まり、制約が戻ること。
    - 往復の2回目は補完0件・再計算0件で、WARNING が出ないこと。
    - `get_heads()==["0042_review_verdict_contract"]`、down_revision、32字以内。
- `backend/tests/test_0041_review_verdict_recount_migration.py`: :379 の head 固定を外し、`len(get_heads()) == 1` と移設の旨のコメントにした（test_0037_0038 / test_0039 と同じ流儀）。関数名は `test_0041_is_chained_from_0040_on_a_single_head` に変え、module docstring も直した。
- `backend/tests/test_0040_review_verdict_migration.py`: docstring の「head を固定するテスト」の参照先を test_0042 に更新した（1行）。

## 段B のファイル（コード。段A の本番適用を確認してから出す）
- `backend/app/core/limits.py`: `REVIEW_COMMENT_MAX_LENGTH = 300` を追加した（唯一の定義。web の REVIEW_COMMENT_MAX と同じ値）。
- `backend/app/db/models/transaction.py`: 互換用の `LEGACY_GOOD_MIN_RATING`・`COMPAT_RATING_BY_VERDICT`・`verdict_from_rating`・ハイブリッド・`_verdict` を撤去した。
  - `verdict: Mapped[str]`（NOT NULL）にした。
  - `rating: Mapped[int | None]`（NULL 可）は「撤去済み・DB 列は残置し書き込まない」とコメントしてマップしたまま残した。
  - `__table_args__`（一意制約・rating の CHECK・verdict の CHECK）はそのまま。
  - 不要になった import（ColumnElement / case / func / hybrid_property）を削除した。
- `backend/app/db/models/operator.py`: rating はマップしたまま「撤去済み（0042）・更新しない」とコメントした。review_count のコメントも直した。
- `backend/app/schemas_katadzuke.py`:
  - ReviewCreateRequest: verdict を必須にし、rating と model_validator を撤去した。口コミの上限は Field と `_sanitize_free_text` の両方で `REVIEW_COMMENT_MAX_LENGTH` を参照する。
  - rating を7つの応答から削除した: ReviewOut・PublicReviewOut・OperatorPublicOut・OperatorProfileOut・OperatorPublicProfileOut・OperatorPublicListItemOut・OperatorOut。
- `backend/app/api/v1/endpoints/reviews.py`: 旧形式の経路・互換値・`review_legacy_rating_payload` ログ・到達しない 422 の分岐を撤去した。`Review(verdict=body.verdict, …)` とし、rating は渡さない。ロック前の当事者確認、ロック後の読み直し、IntegrityError→409（とその WARNING）はそのまま残した。
- `backend/app/services/review_stats.py`: AVG(rating) と operator.rating の更新を撤去した（件数は1クエリのまま、最新の口コミは変えていない）。
- `backend/app/api/v1/endpoints/operator_profile.py`: `rating=operator.rating` の3か所と、docstring の「rating等」を撤去した。
- `backend/app/api/v1/endpoints/admin.py`: hide_review の docstring から「互換の rating」を外した。
- `backend/tests/test_katadzuke_api.py`:
  - 評価の区画を差し替えた。
    - T1: rating が NULL で保存され、応答に rating が無いこと。
    - T2: rating だけの投稿は 422。依頼者・業者の2パターンを確認し、その後の verdict での投稿は通る。
    - T3: 未知の verdict は 422、併せて送られた rating は無視されて NULL で保存される。
    - 口コミ 300 字は通り、301 字は 422。
    - T8 を反転: 7種の応答と `/auth/me` の operator に rating が無いこと。
  - 撤去した分岐のテストを削除した: T6（ハイブリッドでの読み出し）、旧形式から verdict を導くテスト、業者の旧形式のテスト、到達しない 422 の直接呼び出しのテスト。
  - 既存の rating のアサーションは件数に置き換えた。最初の一連の流れのテストは、admin 一覧の `rating == 5.0` から公開プロフィールの件数 (1,0,1) に変えた。
- web: 変更なし。`git grep rating web/src web/e2e` に出るのは CSS のクラス名（rating-summary 等）だけで、API の項目を読む箇所は無い。

## pytest の件数
| 時点 | 対象 | 結果 |
|---|---|---|
| 段A 移行系 | test_0036〜0042・test_review_model_constraints | 14 passed |
| 段A 全件 | worktree（アプリコードは未変更） | **1432 passed / 0 failed** |
| 段B 対象 | test_katadzuke_api・revocation・制約名・0040〜0042 | 122 passed |
| 段B 全件 | worktree | **1429 passed / 0 failed** |
- −3 の内訳は、撤去6件（旧形式から導くテスト3パラメータ、業者の旧形式、T6、到達しない 422）と、追加3件（rating だけの投稿 422 を2パラメータ、300/301 字）。

## 設計から逸れた点・補足
1. 口コミ上限の定数は `app/core/limits.py` に置いた（既に「数量上限の一元定義」の置き場所になっているため）。設計は「1か所」とだけ指定していた。
2. verdict が無いときの 422 の文言は、日本語の独自文言（model_validator）から pydantic 標準の missing（`loc=["body","verdict"]`）に変わる。設計どおり model_validator を撤去した結果で、ステータスコードは 422 のまま。現行の web は verdict を必ず送るので画面への影響は無い。
3. `{"verdict": …, "rating": 9}` は、これまで 422（rating の範囲外）だったが、今後は 201 になる（rating は入力モデルに無い項目として無視）。pydantic の既定（extra="ignore"）による。拒否したい場合は `model_config = ConfigDict(extra="forbid")` にすれば 422 にできるが、既存の他モデルと扱いが揃わなくなるため今回は入れていない。
4. 設計に無い小さな追加が3つある。0042 の downgrade で件数を INFO に出すこと。0042 のテストで、SQLite で PostgreSQL 専用の文を発行しないことを確かめること。トリガーで、ずれていない業者の行を更新しないことを確かめること（0041 のテストと同じ方法）。
5. PostgreSQL 上のロック順も確認した。アプリの経路はどれも reviews に触れてから operators の行を掴む（投稿・非表示の集計）。退会（`lock_operator_row`）と admin の経路は、operators の行を握ったまま reviews を読まない。設計の「循環しない」の前提は成り立つ。

## 未解決・申し送り
1. **反映順を必ず守る**: 段A（0042 だけ）を本番に反映し、/readyz で 0042 が head であることと、Render ログの「0042:」を確認してから段B を出す。逆順だと、段B のコードが rating に NULL を書いて NOT NULL 違反＝投稿が 500 になる。
2. [要確認] PostgreSQL での実際の挙動（ACCESS EXCLUSIVE の取得待ち、SET NOT NULL の全件検査）はこの環境では検証できていない。reviews は極小なので数ミリ秒の想定。
3. 開いたままの旧タブが★だけで投稿すると 422 になる（ユーザー指示「猶予は取らない」により受け入れ済み）。web 側では一般的なエラー表示になる [推測]。
4. DB の★列（reviews.rating・operators.rating）は残置する。operators.rating は段B 以降更新されず古い値のまま残る。0042 を downgrade して旧コードへ戻した場合、★平均は次の投稿か非表示の操作で再計算されるまで古いまま。
5. reviewer_type の CHECK（実名 `ck_reviews_ck_reviews_reviewer_type`）は、今回もモデルに宣言していない（依頼の範囲外）。

## レビュー指摘の修正（最終）— M-1・L-1・QA Low
### 結果
- pytest:
  - 対象の6ファイル: 125 passed。
  - worktree の全件（段A＋段B）: **1432 passed / 0 failed**。
  - 段A のファイルだけの全件: **1433 passed / 0 failed**。HEAD 1f9bdcf を scratchpad に展開し、段A の4ファイルを重ねて実行した。`import app` がコピー側に解決されることを確認済み。
- 今回変えたファイル:
  - 段A: `0042_review_verdict_contract.py`・`test_0042_review_verdict_contract_migration.py`
  - 段B: `reviews.py`・`test_katadzuke_api.py`
- worktree の外（本体ツリー・web・DESIGN-0042.md）は触っていない。

### M-1（reviews.py: 409 にするのは一意制約の違反だけ）
- 判定の根拠はソースで確かめた（推測で書いていない）。
  - venv の SQLAlchemy 2.0.50 の `sqlalchemy/dialects/postgresql/asyncpg.py` の `AsyncAdapt_asyncpg_connection._handle_exception`（781–797 行）は、元の asyncpg 例外を `raise translated_error from error` で `__cause__` に付け、`translated_error.pgcode = translated_error.sqlstate = error.sqlstate` を設定する。
  - asyncpg 0.31.0 は、サーバの 'n' フィールドを例外の `constraint_name` に入れる（`exceptions/_base.py` の `_field_map`）。
- `_classify_integrity_error()` は (一意制約の違反か, sqlstate, 制約名) を返す。
  - PostgreSQL: sqlstate が `23505`、かつ `orig.__cause__.constraint_name == "uq_reviews_transaction_reviewer"` のときだけ一意制約の違反とみなす。
  - SQLite: 文言に `UNIQUE constraint failed: reviews.transaction_id, reviews.reviewer_type` を含むかで判別する。
- 一意制約の違反は従来どおり WARNING を出して 409。それ以外は、rollback → `logger.error("review_create_integrity_error transaction=… reviewer_type=… error=<型名> sqlstate=… constraint=…")` → HTTPException(500)「評価の保存に失敗しました。時間をおいて再度お試しください。」。口コミ本文・SQL・パラメータはログに出さない。
- 例外を送出し直さず HTTPException(500) にした理由:
  - alert_middleware の未処理例外アラートは本文に `str(exc)[:300]`（SQL とパラメータ＝口コミ本文）を載せるため、送出し直すと運営の通知先へ本文が漏れる。
  - 500 の応答は alert_middleware の 5xx 集計（`status >= 500`）に数えられるので、監視を素通りしない。
  - 既存の流儀（operator_profile の初期化失敗 → HTTPException(500)）とも揃う。
  - 注: 500 が1件出ただけでは即時アラートにならず、5xx バーストの閾値に従う。即時に知らせたい場合は、本文を含めない `alerts.send_alert` を足す案がある（未実施・判断待ち）。
- テスト:
  - 既存の「本物の一意制約違反 → 409」は維持した。
  - 新規 `test_review_non_unique_integrity_error_returns_500_without_leaking_the_comment`: before_flush で verdict を NULL にして本物の NOT NULL 違反を起こす。確認内容は、500、error ログの完全一致、どのログにも口コミ本文が無いこと、行が作られないこと、件数が不変であること。
  - 新規 `test_classify_integrity_error_by_asyncpg_sqlstate_and_constraint_name`: 実クラス（`asyncpg.exceptions.PostgresError.new` が返す UniqueViolationError 等と、`AsyncAdapt_asyncpg_dbapi.IntegrityError`）で、アダプタと同じ形を組み立てて判別を固定した。

  | 入力 | 判定 |
  |---|---|
  | 23505＋uq_reviews_transaction_reviewer | 一意制約の違反（409） |
  | 23505＋pk_reviews | それ以外（500） |
  | 23502（NOT NULL） | それ以外（500） |
  | 23514（CHECK） | それ以外（500） |
  | SQLite の3種の文言 | 一意制約の列の組を含むものだけ 409 |

### L-1（0042 の LOCK の待ち時間）
- PostgreSQL のみ、`SET LOCAL lock_timeout = '3s'` → `LOCK TABLE reviews IN ACCESS EXCLUSIVE MODE` → `SET LOCAL lock_timeout = '10s'` の順にした（upgrade と downgrade で共通のヘルパー）。理由は docstring に書いた: ACCESS EXCLUSIVE を待つ間は後から来た読み手もその後ろに並ぶため、待ちを短くし、取れなければ start.sh の再試行に任せる。
- 「SQLite では出ない」テスト（SQL の捕捉）はそのまま。
- 追加 `test_0042_waits_for_the_reviews_lock_at_most_3s_only_on_postgresql`: 実 PostgreSQL が無い環境でも文の順序を固定するため、マイグレーションの `op` を差し替えて、PostgreSQL は3文を上の順に、SQLite は何も発行しないことを確かめる。

### QA Low（test_0042）
- (a) ★3・verdict NULL の行（業者→依頼者。件数に影響しない別の取引に置いた）が improve に補完されることを確認した。補完件数は 3 件になる。
- (b) 表の作り直し後、rating=0／6 の INSERT が `ck_reviews_ck_reviews_rating` で拒否されること、NULL は通ること（段B 形式の行の INSERT）を実行して確認した。

### 残り
- [要確認] 判別の土台は、アダプタの実装（SQLAlchemy 2.0.50 / asyncpg 0.31.0）。単体テストは実クラスを使うが、アダプタの変換そのものは手で再現している。SQLAlchemy を更新したときは、アダプタの `_handle_exception` が `pgcode/sqlstate` と `from error` を保っているか確かめる。CI の pg-concurrency（実 PostgreSQL）に、一意制約違反→409 の結合テストを足すと確実になる（未実施の提案）。
