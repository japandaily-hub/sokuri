# 0042 contract 設計（評価の2択化の後片付け・2026-09-25）

ユーザー指示（2026-09-25）: 「星の取り扱いについては、それぞれの合計数が分かれば良い」「待たずに今始めて」。
→ ★（rating）は応答・入力・集計から完全に外し、「よかった／伸びしろ」の件数だけを残す。旧タブ（★だけの投稿）の猶予は取らない。
DB の★列（reviews.rating・operators.rating）は削除しない（取り消せない操作のため）。既存の流儀
（operator_profiles の is_public / show_stats / show_reviews＝撤去済みでもモデルに残し「DB列は残置」）に合わせ、
モデルにはマップしたまま「撤去済み・書き込まない」とコメントする。
architect の確定設計（DESIGN.md「後続の 0040（contract）」節＝番号は 0042 に読み替え）を踏襲し、下記の具体化を加える。

## 反映の2段（今回と同じ理由: start.sh は alembic 失敗でも起動する）
- **段A＝マイグレーション 0042 のみ**（現行コード＝1f9bdcf と両立すること）。
- **段B＝コード**（段A が本番で適用済みであることを確認してから）。段A 未適用のまま段B が動くと、rating に NULL を書いて NOT NULL 違反＝投稿が 500 になるため順序厳守。

## 段A: backend/alembic/versions/0042_review_verdict_contract.py
- revision="0042_review_verdict_contract"（28字）、down_revision="0041_review_verdict_recount"。app のコードは import しない。
- upgrade:
  - PG のみ: `SET LOCAL lock_timeout = '10s'` → `LOCK TABLE reviews IN ACCESS EXCLUSIVE MODE`
    （後段の ALTER が ACCESS EXCLUSIVE を要するので最初から取る＝ロックの格上げによるデッドロックを避ける。
    reviews は極小で保持は数ミリ秒。operators の行ロックを握ったまま reviews を待つ経路は無い＝循環しない）。
  - R1: `UPDATE reviews SET verdict = CASE WHEN rating >= 4 THEN 'good' ELSE 'improve' END WHERE verdict IS NULL`
    （0040 と同じ閾値。段A 時点の本番コードは verdict を必ず書くので通常 0 件）。
  - R2: `with op.batch_alter_table("reviews")`: `alter_column("verdict", existing_type=String(16), nullable=False)`、
    `alter_column("rating", existing_type=Integer, nullable=True)`（CHECK の rating 1〜5 は NULL を通すので触らない）。
  - R3: 0041 と同じ「ずれている業者だけ」の再計算（母集団＝依頼者→業者・非表示除外。verdict は NOT NULL になったので素の列で数える）。
  - INFO「0042: verdict を N 件補完し NOT NULL 化、rating を NULL 可に変更。件数がずれていた業者 M 件を再計算（更新 K 件）。」（M>0 なら WARNING）
- downgrade: PG の lock → `UPDATE reviews SET rating = CASE WHEN verdict='good' THEN 5 ELSE 2 END WHERE rating IS NULL`
  （段B 以降に書かれた rating NULL 行を互換値で埋める）→ batch で rating NOT NULL・verdict NULL 可へ戻す。
- テスト backend/tests/test_0042_review_verdict_contract_migration.py（0040/0041 と同じ型・SQLite ファイル・stamp 0041）:
  NULL verdict 行の補完、NOT NULL／NULL 可（PRAGMA table_info）、既存の名前付き制約と FK が作り直し後も残る、
  ずれ業者の再計算とログ（caplog）、2回目冪等、downgrade で rating NULL 行が互換値で埋まり制約が戻る、往復、
  `get_heads()==["0042_review_verdict_contract"]`・down_revision・32字以内。
  test_0041 の head 固定（:379）は 0042 のテストへ移す（test_0037_0038／test_0039 と同じ流儀のコメント＋len==1）。

## 段B: コード
- models/transaction.py: 互換用の LEGACY_GOOD_MIN_RATING・COMPAT_RATING_BY_VERDICT・verdict_from_rating・ハイブリッドと `_verdict` を撤去し、
  `verdict: Mapped[str] = mapped_column(String(16), nullable=False)`。`rating: Mapped[int | None]`（nullable・「撤去済み。DB列は残置し書き込まない＝0042 以降の新規行は NULL」）。
  __table_args__ の制約宣言（verdict CHECK・rating CHECK・一意制約）は維持。
- models/operator.py: `rating` はマップしたまま「撤去済み（0042）。DB列は残置・更新しない」。
- schemas_katadzuke.py: ReviewCreateRequest＝`verdict: ReviewVerdict`（必須）、rating と model_validator を撤去。
  **口コミの上限を 300 字**（Field max_length と `_sanitize_free_text(max_length=…)` の両方。定数を1か所に置く。web の REVIEW_COMMENT_MAX=300 と一致）。
  応答から rating を削除: ReviewOut・PublicReviewOut・OperatorPublicOut・OperatorProfileOut・OperatorPublicProfileOut・OperatorPublicListItemOut・OperatorOut。
- endpoints/reviews.py: 旧形式の経路・互換値・`review_legacy_rating_payload` ログ・到達不能な 422 分岐を撤去。rating は渡さない（NULL）。
  ロック前の当事者確認・IntegrityError→409 等、2段目で入れた堅牢化はそのまま。
- services/review_stats.py: AVG(rating) と operator.rating の更新を撤去（件数・最新口コミは不変）。
- endpoints/operator_profile.py: `rating=operator.rating` の3か所を撤去、docstring 更新。admin.py の docstring 更新。
- 「0042 で削除」等の予告コメントを完了形に直す。
- テスト: T8（応答に rating が残る）→「応答に rating が無い」へ反転。旧形式 rating のみ投稿は 422（verdict 必須）に置換。
  T6（verdict NULL 行のハイブリッド読み）と明示 422 分岐のテストは撤去。rating を確かめる既存アサーションを件数へ。
  口コミ 300 字ちょうど OK／301 字 422 を追加。
- web: 変更なし（型は既に rating を持たない。REVIEW_COMMENT_MAX=300）。

## 戻し手順（security M-2・段B の後に元へ戻す必要が出た場合）
- **コードだけを段B 前（1f9bdcf 相当）へ戻してはいけない。** 戻したコードの alembic スクリプトは 0041 までしか無いので、start.sh の
  `alembic upgrade head` が DB の版 0042 を見つけられず3回失敗→degraded 起動する。さらに旧コードは段B 期間の行（rating=NULL）を
  `rating: int` の応答型で直列化するため、公開プロフィール・業者一覧・投稿応答が 500 になる。
- 正しい順序:
  1. 0042 を含むビルド（段B のコード）が稼働している状態で、Render 上（ダッシュボードの Shell など）で
     `cd backend && alembic downgrade 0041_review_verdict_recount` を実行する。downgrade は rating が NULL の行を
     互換値（good=5／improve=2）で埋めてから rating NOT NULL・verdict NULL 可へ戻す。/readyz の alembic_version が 0041 になったことを確認。
  2. その後にコードを段B 前へ戻す（revert コミットを push）。
  - 1〜2 の間は段B のコードが rating を書かないため投稿が NOT NULL 違反になる。security M-1 の修正で 409 に偽装されず
    500＋エラーログとして見える（数分の窓。気になる場合はその間だけ投稿を止める）。
- 段A だけを戻す場合（段B 前）は `alembic downgrade 0041_review_verdict_recount` だけでよい（段A はアプリコードを変えない）。

## 本番確認（段ごと）
- 段A: /readyz alembic=expected_head=0042、Render ログ「0042:」、Traceback・alembic 失敗なし、現行コードで GET /api/v1/vendors 200・応答に rating がまだある（段A 時点は旧コード）。
- 段B: /health commit、/readyz 0042、ログにエラーなし、/api/v1/vendors の応答に rating が無く good_count/improve_count がある。CI（backend・pg-concurrency・web）success。
