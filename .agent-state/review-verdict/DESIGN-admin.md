# ★列の DB 削除 ＋ 運営の口コミ管理 — 確定設計（architect 確定・2026-09-25）

ユーザー指示: 「推奨で実行して（＝★の列を DB から削除）」「運営が口コミの削除ができるようにもしておいて」。
推奨案をそのまま採用（ユーザーは「推奨で」と指示）: 論理削除・ボタン文言「削除する」・理由必須（定型5種＋自由入力）・
hidden_by_admin_id は「今非表示にしている人」だけ（履歴はログ）・投稿者本人の削除請求（本文消去）は別チケット。
**物理削除は入れない**（送信防止措置・発信者情報開示の申出に応じるため記録を保持。誤操作も戻せる）。

## 共通ルール（実装担当）
- 作業場所は **C:\Users\ko13h\Claude\Projects\ソクウリ\.claude\worktrees\rv-admin 配下のみ**（絶対パス）。本体ツリーは別セッションが使用中なので触らない。
- backend 担当は backend/ と .github/workflows/ci.yml、frontend 担当は web/ だけ。相互に触らない。
- **backend 担当は worktree のブランチ feat/review-admin-drop-rating に段ごとにコミットしてよい**（pathspec 指定・backend と ci.yml のみ。push は禁止）。frontend 担当は git 操作をしない（リーダーがコミット）。
- pytest: `cd C:/Users/ko13h/Claude/Projects/ソクウリ/.claude/worktrees/rv-admin/backend && TZ=Asia/Tokyo PYTHONUTF8=1 C:/Users/ko13h/Claude/Projects/ソクウリ/backend/.venv/Scripts/python.exe -m pytest -q`。
- web: worktree に node_modules が無いので、リーダーがジャンクションを用意済み（web/node_modules → 本体の web/node_modules）。**web/node_modules を削除・rm しない**。

## 反映の3段（start.sh は alembic 失敗でも起動するため、マイグレーションとそれに依存するコードを同じ push に入れない）
- **段1（コードのみ・0043 と独立）**: Review／Operator の rating のマップと rating CHECK 宣言を撤去（未使用 import も）、コメントを完了形に、テスト更新
  （test_katadzuke_api.py:2647・:2714-2717 の Review.rating 参照、test_review_model_constraints.py:69-71 の rating CHECK 名固定）。
  段1 のコードは今の DB（rating 列あり・NULL 可）と両立する（INSERT で列を省けば NULL、NULL は CHECK を通る）。
- **段2（マイグレーションのみ・先方の 0043_audit_active_no_license が main に入り、段1 の稼働確認後）**:
  - `0044_drop_rating_columns`（24字・down=0043_audit_active_no_license・app を import しない）:
    PG のみ `SET LOCAL lock_timeout='3s'` → `LOCK TABLE reviews`（ACCESS EXCLUSIVE）→ `LOCK TABLE operators` → `SET LOCAL lock_timeout='10s'`。
    表ごとに inspector で rating 列の有無を見て無ければ飛ばす（冪等・ログ）。表ごとに非 NULL 件数、1〜50 件なら (id, rating) を INFO（取り消せない操作の手掛かり）。
    CHECK 名は推測しない: `sa.inspect(bind).get_check_constraints("reviews")` で sqltext が `\brating\b` に一致するものの name を全て取り（None は飛ばす）、
    `batch_alter_table("reviews")` 内で `drop_constraint(op.f(name), type_="check")` → `drop_column("rating")`（op.f 必須＝命名規約の二重前置を防ぐ）。
    operators は batch で `drop_column("rating")`。INFO「0044: reviews.rating（非NULL n 件・CHECK [名前]）と operators.rating（非NULL m 件）を削除。」
    downgrade: 同じ順でロック → reviews に `rating INTEGER NULL`＋`op.f("ck_reviews_ck_reviews_rating")` の CHECK(1〜5)、operators に `rating FLOAT NULL`（値は NULL で戻る＝旧値は復元不可）。
  - `0045_review_hidden_by_admin`（27字・down=0044）: reviews.hidden_by_admin_id（UUID・NULL 可・FK users.id ON DELETE SET NULL・名前 fk_reviews_hidden_by_admin_id_users・索引 op.f("ix_reviews_hidden_by_admin_id")。作り方は 0031 と同じ batch＋create_index。PG は lock_timeout 3s）。downgrade で撤去。
  - 移行テスト（SQLite・stamp 0043 → 明示の revision へ upgrade）: CHECK 名3通り（ck_reviews_ck_reviews_rating／ck_reviews_rating／無し）のパラメータ化、
    作り直し後も uq_reviews_transaction_reviewer・ck_reviews_verdict・FK が有効で `PRAGMA foreign_key_check` が空、他列と件数が不変、caplog、downgrade（NULL で戻り CHECK が 6 を拒否し NULL を通す）、往復、列が無い DB で upgrade が no-op、32字以内、
    `get_heads()==["0045_review_hidden_by_admin"]`（先方の test_0043 の head 固定はこちらで外す＝先方了承の流儀）。0045 は列・FK（SET NULL）・索引と downgrade。
  - ci.yml の pg-concurrency に「`python scripts/pg_alembic_upgrade.py downgrade 0043_audit_active_no_license` → `upgrade head`」の往復を追加（実 PG で 0044/0045 の downgrade を検証）。
- **段3（コードと web・段2 の本番適用確認後）**: hidden_by_admin_id のマップ（ReviewOut／PublicReviewOut には出さない＝運営個人を当事者に開示しない）、一覧 API、非表示 API の強化、web 一式、E2E。

## 段3 backend
- `GET /admin/reviews`（`Depends(get_current_admin)`）: `visibility`=visible|hidden|all（既定 all）、`reviewer_type`=user|operator、`verdict`=good|improve、`operator_id`、`q`（100字以内。strip 後 UUID として読めれば `Review.id==u OR Review.transaction_id==u` の完全一致、読めなければ `Operator.company_name.ilike('%'+esc+'%', escape='\\')`・既存 `_escape_ilike_value`／`_try_parse_uuid` を流用）、`limit`（既定 50・1〜200）・`offset`。
  Review→Transaction 内部結合、Bid・Operator 外部結合（業者が削除・匿名化されても行が出る）。1 クエリ（N+1 なし）、`created_at desc, id desc`。
  応答 `{items, total, counts}`: total は絞込後、counts{all, visible, hidden} は絞込に関わらない全件（operators と同じ契約・`count().filter()` の1クエリ）。
  行: id, transaction_id, reviewer_type, verdict, comment（全文）, created_at, hidden_at, hidden_reason, hidden_by_admin_id, operator_id, company_name（依頼者のメールは出さない）。
- `PATCH /admin/reviews/{id}/hide`（パスと応答 ReviewOut は不変）: ReviewHideRequest に model_validator — hidden=true は reason 必須（strip 後 1〜200 字・`_sanitize_free_text`）、欠落 422。hidden=false の reason は無視。
  `session.get(Review, id, with_for_update=True)` で行ロック（reviews→operators の順）。**冪等**: 既に同じ状態なら何も書かず再計算もせず 200（最初に消した人・時刻・理由を保持＝contacts/handle と同じ）。
  削除: hidden_at=now・hidden_reason・hidden_by_admin_id=admin.id。元に戻す: 3列とも NULL。reviewer_type=user のときだけ recalc_operator_review_stats。
- 監査ログ: `admin_review_hide admin= review= operator= hidden= changed=`、一覧は絞込の種類・has_q・count・total・admin_id のみ（本文・理由・q の中身は出さない）。
- テスト backend/tests/test_admin_reviews.py（新規）: 認可（401/403）、各絞込、UUID 完全一致（部分 UUID は不一致）、業者名の `%`・`_` エスケープ、total と counts、limit 0/201 は 422、同時刻の行のページ跨ぎで重複・欠落なし、業者削除済みでも行が出る、理由なし・空白・201 字は 422、hidden_by_admin_id、二度押しで最初の値保持・再計算なし、元に戻すで3列 NULL、依頼者→業者は件数・最新口コミ・公開プロフィールが増減し業者→依頼者は不変、ReviewOut に hidden_reason・hidden_by_admin_id が出ない、存在しない ID は 404。

## 段3 web
- `web/src/lib/katadzuke-api.ts`: 型と `adminListReviews(params, token)`・`adminSetReviewHidden(id, {hidden, reason?}, token)`。
- `web/src/app/admin/reviews/page.tsx`（新規・contacts と同じ構成）: 題「口コミの管理」、説明「公開中の口コミを確認し、問題のある口コミを公開画面から削除します。削除した口コミは運営画面に記録として残り、元に戻せます。」、右上「管理画面トップへ」。
  絞込: StatusFilterBar ×3（状態: 表示中・削除済み・すべて〔counts で件数〕／向き: すべて・依頼者→業者・業者→依頼者／評価: すべて・よかった・伸びしろ）＋検索欄「口コミ ID・取引 ID・業者名」。既定は「表示中」。
  URL の q・visibility・operator_id を初期値に読む（useSearchParams は Suspense で包む）。業者名クリックで operator_id 絞込＋解除チップ。
  表: 投稿日時／向き／評価（よかった・伸びしろ）／口コミ（テキストノードのみ・pre-wrap・break-words）／業者／取引 ID・口コミ ID（CopyableId）／状態（StatusBadge「表示中」「削除済み」＋日時・理由）／操作。0件「該当する口コミはありません。」。AdminPagination。
  削除ダイアログ: 題「この口コミを公開画面から削除します」、本文の抜粋（80字）と業者名、理由必須（定型「誹謗中傷・名誉毀損のおそれ／第三者の個人情報／送信防止措置の申出／取引と関係ない内容・宣伝／その他」＋自由入力・200字以内）、
  説明「公開プロフィール・口コミの件数・最新の口コミから消えます。記録は運営画面に残り、『元に戻す』で再表示できます。」、確定「削除する」、失敗はモーダル内に表示。
  元に戻すダイアログ: 題「この口コミを元に戻します」、説明「公開プロフィールと件数に再び反映されます。削除の理由と実施者の記録は消え、操作ログにだけ残ります。」、確定「元に戻す」。
  確認ダイアログは既存 `web/src/components/kdz/ConfirmModal.tsx`（reasonLabel・reasonRequired を持つ）を使う。定型理由の選択が要るなら /admin/transactions の強制終了と同じ組み方に揃え、共有部品は改変しない。
- 導線: `web/src/app/admin/page.tsx`（お問い合わせのリンクの隣）に「口コミの管理」。
- 報告→問い合わせ→該当口コミ（既存の不具合修正）: `/contact` は subject を読んでおらず、`vendors/[id]` の「口コミの報告（<id>）」が送信時に失われ運営に口コミ ID が届かない。
  `web/src/lib/review-report.ts`（新規）に件名の組み立てと本文から口コミ ID を取り出す処理（`口コミの報告（UUID）` の厳密一致）をまとめ、vendors/[id] もこれを使う。
  `/contact`: subject が厳密一致したときだけ読み、「報告する口コミ: <ID>」を表示、種別 other を初期選択、送信時に本文先頭へ件名行を付ける（既存 DISCLOSURE_PREFIX と同じ方式・backend 変更なし）。一致しない subject は無視。
  `/admin/contacts`: ID が取れた行に「該当の口コミを開く」→ `/admin/reviews?q=<id>&visibility=all`。
- E2E: `web/e2e/09-admin-reviews.spec.ts`（新規）— 削除 → /vendors/<id> から消えて件数が減る → 削除済み一覧で理由が見える → 元に戻す。報告リンク → /contact に ID 表示 → 送信 → /admin/contacts「該当の口コミを開く」→ 1件だけ出る。99-mobile-audit に /admin/reviews を追加。helpers/api.ts に必要な型。

## レビュー反映（2026-09-25〜27）
- security Medium-1（段3 のコードが段2 未適用の DB で動くと、口コミを読む公開 API まで 500。0044 だけ成功し 0045 が失敗する部分適用も起こり得る）:
  **段3 を push する前の関門**として、本番の `/readyz` の `schema.alembic_version == "0045_review_hidden_by_admin"`（expected_head と一致）を curl で実証し、
  Render ログに「0044:」「0045:」の INFO があることを確認する。満たさなければ段3 を出さない。起動時ガード（列が無ければ CRITICAL）は採らない
  （段ごとの外形確認で足り、起動経路を増やさない）。
- security Low-1（「元に戻す」の説明文が「理由は操作ログに残る」と読める）: 文言を実態（ログには実施者・対象・削除/復元・変化の有無だけ）に合わせて修正。
- QA Medium（削除 API の行ロックを実 PostgreSQL の並行実行で検証していない）: CI の pg-concurrency に S8（同時削除・同時復元・削除と復元の同時・投稿と削除の同時）を追加。
  **本番 push の前に検証用 PR で CI（pg-concurrency を含む）を通す**（0044/0045 の実 PostgreSQL での適用・往復もここで先に確かめる）。
- QA Low（operator_id と q の同時指定）: テスト追加。QA Low（理由 201〜500 字の入力 UX）: 共有部品を改変しない方針のため現状維持（送信前に 200 字超を止めるのでデータは守られる）。

## 戻し手順（逆順を厳守）
段3 を revert → `alembic downgrade 0044_drop_rating_columns`（0045 を戻す）→ `alembic downgrade 0043_audit_active_no_license`（★列を NULL で復活）→ 段1 を revert。
DB に rating が無いまま段1 より前のコードへ戻すと operators の読み取りが全部 500 になる。
