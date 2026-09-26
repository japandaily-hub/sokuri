# backend 報告: ★列の DB 削除 ＋ 運営の口コミ管理（2026-09-25）

設計の正本: `.agent-state/review-verdict/DESIGN-admin.md`。作業場所は worktree `rv-admin`（ブランチ feat/review-admin-drop-rating・起点 da778db）。push はしていない。

## 結論
- 段1（d2017f9）と段3 backend（c1b5c3c）をコミットした。段2 は未コミットで worktree に置いてある（先方の 0043 を複製して連鎖させた状態）。
- pytest: 基準線 1432 → 段1 1432 passed → 段3 1443 passed → 段2 1455 passed（いずれも全件・失敗 0）。
- **反映順の注意（重要）**: ブランチ上の順序は 段1 → 段3 だが、本番は **段1 → 段2（0044/0045）→ 段3** の順で出すこと。c1b5c3c は `reviews.hidden_by_admin_id` をマップするため、0045 が本番に当たる前に動くと reviews を読む全経路（公開プロフィール・投稿・一覧）が 500 になる。

## 段1（コミット d2017f9・pytest 1432 passed）
| ファイル | 内容 |
|---|---|
| backend/app/db/models/operator.py | `rating` のマップ撤去・未使用の `Float` import 撤去・コメントを完了形へ |
| backend/app/db/models/transaction.py | `Review.rating` のマップと rating CHECK の宣言を撤去・未使用の `Integer` import 撤去・docstring とコメントを完了形へ |
| backend/app/api/v1/endpoints/reviews.py | コメントを完了形へ（:4・:178） |
| backend/app/services/review_stats.py | docstring を完了形へ |
| backend/tests/test_katadzuke_api.py | T1・T3 の `Review.rating` 参照を「verdict の保存＋モデルが rating をマップしない」の確認へ置換 |
| backend/tests/test_review_model_constraints.py | 「モデルが rating CHECK を宣言しない」＋「0004 の実名 ck_reviews_ck_reviews_rating（0044 の downgrade が作り直す名前）」の固定へ |

- 今の本番 DB と両立することを確認済み: operators.rating は 0004 から NULL 可、reviews.rating は 0042 で NULL 可。INSERT が列を省くので NULL が入り、NULL は旧 CHECK を通る。

## 段3 backend（コミット c1b5c3c・pytest 1443 passed）
| ファイル | 内容 |
|---|---|
| backend/app/api/v1/endpoints/admin.py | `GET /admin/reviews` 新設、`PATCH /admin/reviews/{id}/hide` を強化、`_join_review_operator`・`_REVIEW_NOT_FOUND`（http_exception_factory） |
| backend/app/schemas_katadzuke.py | `ReviewHideRequest` に model_validator、`AdminReviewListItem`・`AdminReviewListCounts`・`AdminReviewListResponse`、ReviewOut に「理由・実施者を意図して含めない」旨のコメント |
| backend/app/db/models/transaction.py | `Review.hidden_by_admin_id`（Uuid・FK users.id ON DELETE SET NULL・index=True） |
| backend/app/core/limits.py | `REVIEW_HIDE_REASON_MAX_LENGTH = 200` |
| backend/tests/test_admin_reviews.py（新規 11 件） | 認可 401/403、各絞込と組み合わせ、total/counts、UUID 完全一致（部分・1字欠けは不一致・大文字と前後空白は可）、`%`・`_` のエスケープ、limit 0/201・offset -1・q 101 字は 422、同時刻のページ跨ぎ、SQL 本数一定（N+1 防止）、退会業者の行、理由の検証（欠落・null・空・空白・全角空白・201 字・URL は 422 で何も書かない／200 字＋前後空白は可／NFKC）、hidden_by_admin_id、二度押しで最初の値保持・再計算なし、元に戻すで3列 NULL、依頼者→業者だけ集計が増減、ReviewOut のキー固定、404/422、ログに本文・理由・q を書かない |

- 応答の型は web の `katadzuke-api.ts`（AdminReviewListItem 11 項目・counts{all,visible,hidden}・クエリ名 visibility/reviewer_type/verdict/operator_id/q/limit/offset）と一致することを読み取りで確認済み。
- 一覧の SQL（PostgreSQL 方言で出力して確認）: `reviews JOIN transactions LEFT OUTER JOIN bids LEFT OUTER JOIN operators`、全てパラメータ化、`ORDER BY created_at DESC, id DESC`。1回の一覧で reviews を読む SQL は件数・内訳・本体の3本だけ（テストで固定）。
- 認可は両エンドポイントとも `Depends(get_current_admin)`。認証は Authorization ヘッダの Bearer（Cookie 不使用）なので CSRF の対象外。

## 段2（未コミット・pytest 1455 passed）
| ファイル | 状態 | 内容 |
|---|---|---|
| backend/alembic/versions/0043_audit_active_no_license.py | 複製（先方の成果物・内容不変） | 本体ツリーの同名ファイルと改行コード以外同一を確認 |
| backend/tests/test_0043_audit_active_no_license_migration.py | 複製＋worktree 上で head 固定だけ変更 | `get_heads()==["0043_…"]` → `len(get_heads())==1`＋docstring を test_0042 と同じ作法に |
| backend/tests/test_0042_review_verdict_contract_migration.py | 先方のコミット 0d6005d の版で置換 | 先方が 0043 のために外した head 固定（`len(get_heads())==1`）。0d6005d と同一内容 |
| backend/alembic/versions/0044_drop_rating_columns.py | 新規（24 字・down=0043） | PG のみ lock_timeout 3s → LOCK reviews → LOCK operators（ACCESS EXCLUSIVE）→ 10s。表ごとに列の有無を見て無ければ飛ばす（INFO）。非 NULL 件数と、1〜50 件なら id=rating を INFO。CHECK 名は inspector の get_check_constraints から `\brating\b` で取り（名前なしは飛ばす）batch 内で `drop_constraint(op.f(名前))` → `drop_column`。downgrade は同じ順でロックし rating INTEGER NULL＋`op.f("ck_reviews_ck_reviews_rating")` の CHECK(1〜5)、operators.rating FLOAT NULL（既に列があれば飛ばす）。app を import しない |
| backend/alembic/versions/0045_review_hidden_by_admin.py | 新規（27 字・down=0044） | PG のみ lock_timeout 3s。0031 と同じ batch＋create_index で列・FK fk_reviews_hidden_by_admin_id_users（SET NULL）・索引 ix_reviews_hidden_by_admin_id。downgrade で撤去 |
| backend/tests/test_0044_drop_rating_columns_migration.py | 新規 6 件 | CHECK 名3通り（ck_reviews_ck_reviews_rating／ck_reviews_rating／無し）のパラメータ化、作り直し後の一意制約・verdict CHECK・FK・索引の有効性と `PRAGMA foreign_key_check` 空、他列と件数の不変、caplog の文言、downgrade（NULL で戻り 6 を拒否し NULL を通す）、往復、列が無い DB で no-op（sqlite_master が1バイトも変わらない）、PG のロック文の順序、連鎖と 32 字 |
| backend/tests/test_0045_review_hidden_by_admin_migration.py | 新規 3 件 | 列・FK（SET NULL を実際にユーザー削除で確認・存在しない ID は FK 違反）・索引、戻し手順の順（downgrade 0044 → downgrade 0043 → upgrade head）、PG の lock_timeout、`get_heads()==["0045_review_hidden_by_admin"]` と 0045→0044→0043→0042 の連鎖・32 字 |
| .github/workflows/ci.yml | 変更 | pg-concurrency の「Apply real migrations」の直後に `downgrade 0043_audit_active_no_license` → `upgrade head` の往復ステップを追加（続く同時実行シナリオは上げ直した後のスキーマで走る） |

## 設計から逸れた点・設計にない判断
1. **ReviewHideRequest.reason の上限の数え方**: 設計「strip 後 1〜200 字」「hidden=false の reason は無視」を厳密に満たすため、`Field(max_length=200)` をやめ、validator 内で strip 後の長さを判定してから `_sanitize_free_text` に通す（最初は生の長さで弾いていて、200 字＋前後空白が 422 になることをテストで検出して直した）。hidden=false は中身も長さも見ずに捨てる。
2. **無害化の副作用（設計どおりだが web に周知が要る）**: `_sanitize_free_text` のため、理由は NFKC 正規化される（例「ＡＢＣ（宣伝）」→「ABC(宣伝)」で保存）。電話番号・メール・URL を含む理由は 422「削除の理由に電話番号・メールアドレス・URLは記載できません。」になる。
3. 上限 200 を `app/core/limits.py` の `REVIEW_HIDE_REASON_MAX_LENGTH` に置いた（設計に記載なし・単一の出所にするため）。
4. hide の実装詳細: `session.get(..., with_for_update=True, populate_existing=True)`（ロック後の最新行で判定）。変更なしの経路でも `commit()` して行ロックを解放する（書き込みは無い）。業者の特定を `session.get` 2回から1クエリ（ロックなし）に変更。404 の detail は既存の "Review not found." を維持。
5. 一覧のログは `operator_id` の値を書かず `operator_filter=True/False` だけにした（設計「絞込の種類・has_q・count・total・admin_id のみ」の解釈）。q の 100 字上限は他の admin 一覧と同じく生の値に掛かる（web は trim してから送る）。
6. **test_0042 の置換（指示の「0043 の2ファイルだけ複製」の外）**: worktree の test_0042 は head を 0042 に固定しており 0043 以降で必ず落ちるため、先方が 0d6005d で行った同じ変更の版に置き換えた。内容は 0d6005d と同一なので、載せ替え時に衝突しない。
7. 状況の変化: 指示時点で「未コミット」だった先方の 0043 は、本体ツリーでローカルコミット 0d6005d（未 push・origin/main は da778db のまま）になっていた。0d6005d には 0043・test_0043・test_0042 の変更が入っている。

## 未解決・要確認
- [要確認] **0044/0045 の PostgreSQL 経路は未実証**（ローカルに PostgreSQL が無い＝Docker 停止・5432/5433 閉）。inspector の CHECK 文字列（PG は `(rating >= 1) AND (rating <= 5)` 形式）・ALTER・LOCK は、追加した CI の往復ステップが push 後に初めて通す。段2 の push 後に pg-concurrency の成功を確認すること。
- [要確認] **本番の★の非 NULL 件数**: 0044 は値を消す（downgrade でも戻らない）。1〜50 件なら id=rating を Render のログに残すが、51 件以上なら件数だけ。必要なら段2 の前に `SELECT id, rating FROM reviews WHERE rating IS NOT NULL` と operators の同等を控えること。
- [推測] ロック順のデッドロック: 0044 は reviews → operators の順に ACCESS EXCLUSIVE を取る。operators を先に読んでから reviews を読む読み取りトランザクション（公開プロフィール等）と数ミリ秒の窓で重なるとデッドロックになり得る。その場合 PostgreSQL が片方を中断し、DDL はトランザクション内なので安全に失敗して start.sh の再試行に回る。発生確率は極小と見るが、段2 は低トラフィック時に出すのが無難。
- 載せ替え時の扱い（リーダー判断）: test_0043 の head 固定の変更は worktree 上だけのもの。先方の 0d6005d が origin/main に入った後、0043 と test_0042 は上流と同一になり、test_0043 は head 固定の差分だけが残る。
- 範囲外の古いコメント: test_0040:285・test_0041:18/:376 の「現在は test_0042…」は 0043 の時点から古い（見た目だけ・動作に影響なし）。
- [推測] 規模が大きくなった場合（口コミ 10 万件〜）: 一覧の `ORDER BY created_at DESC, id DESC` と `hidden_at IS NULL` の件数用に索引を検討（今の規模では不要）。
