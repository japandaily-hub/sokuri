# 評価の2択化（よかった／伸びしろ）＋コメント候補チップ — 設計叩き台（リーダー起票 2026-09-25）

## 依頼（ユーザー原文の要旨）
ユーザー⇔業者の相互評価を、メルカリを参照して「よかった」「伸びしろ」の2択にする。
コメントは自由記述のまま、「安心して取引できました！」「スムーズでした！」等の候補を表示し、ワンタップで入力できるようにする。

参照（一次情報で確認済み）: メルカリ公式コラム https://jp-news.mercari.com/contents/1615
「良い（良かった）」「悪い（残念だった）」の2段階。評価コメントは任意。受けた評価とコメントはほかのユーザーも閲覧可能。

## 調査済みの事実（file:line）
### バックエンド（FastAPI / SQLAlchemy async / alembic、テストは SQLite in-memory、本番 PostgreSQL on Render）
- `backend/app/db/models/transaction.py:147-164` Review: `rating INT NOT NULL (1–5)`, `comment TEXT NULL`, `hidden_at`, `hidden_reason`。一意制約 `uq_reviews_transaction_reviewer`（transaction_id, reviewer_type）は既存マイグレーション側で定義。
- `backend/app/db/models/operator.py:21-25` Operator: `rating FLOAT NULL`（平均）, `review_count INT NOT NULL DEFAULT 0`, `latest_review_comment VARCHAR(200) NULL`。
- `backend/app/services/review_stats.py` `recalc_operator_review_stats()` が集計の単一の正本（reviews.py の投稿時と admin.py:532-560 の非表示/再表示時に呼ぶ。operators 行を with_for_update でロック）。集計対象は reviewer_type="user" かつ hidden_at IS NULL。
- `backend/app/api/v1/endpoints/reviews.py` POST /api/v1/reviews {transaction_id, rating(1–5), comment?}。reviewer_type はトークン種別から導出、completed のみ、二重投稿は409（IntegrityError も409）。
- `backend/app/schemas_katadzuke.py`
  - :98-117 OperatorOut.rating（admin一覧・業者自身）
  - :154-165 OperatorPublicOut{rating, review_count, latest_review_comment}（入札一覧の業者情報）
  - :996-1007 ReviewCreateRequest{transaction_id, rating ge1 le5, comment ≤1000 + _sanitize_free_text（連絡先/URL拒否）}
  - :1010-1020 ReviewOut{id, transaction_id, reviewer_type, rating, comment, created_at, hidden_at}
  - :1030-1039 PublicReviewOut{id, rating, comment, created_at}
  - :1350-1370 OperatorProfileOut.rating / review_count
  - :1408-1425 OperatorPublicProfileOut.rating / review_count / reviews
  - :1428-1440 OperatorPublicListItemOut.rating / review_count / latest_review_comment
- `backend/app/api/v1/endpoints/operator_profile.py` :93-111 _to_profile_out / :190-228 公開プロフィール（user→業者レビューのみ・非表示除外・最新50件）/ :231-282 GET /vendors（並び: rating IS NULL, rating DESC, review_count DESC, created_at ASC）。
- `backend/app/api/v1/endpoints/transactions.py:329` 取引詳細は双方のレビュー全件（ReviewOut）を当事者双方に返す（業者→ユーザー評価は公開プロフィールには出ないが、取引詳細APIでは当事者に返っている。既存挙動・今回スコープ外）。
- 最新マイグレーション: `backend/alembic/versions/0038_clear_deleted_op_line_ids.py`。**revision id は32文字以内厳守**（過去の全断障害）。PGでは `SET LOCAL lock_timeout = '10s'` を冒頭に置く慣習。
- マイグレーションテストの型: `backend/tests/test_0037_0038_migrations.py`（SQLite ファイルに最小スキーマを作り alembic upgrade/downgrade、`script.get_heads() == ["0038_..."]` を assert している:183 → 新リビジョン追加で更新が必要）。
- rating を使う既存テスト: `backend/tests/test_katadzuke_api.py`（552-573, 661, 730, 761-769, 2354-2361, 2482-2575）、`backend/tests/test_deleted_operator_token_revocation.py`（297, 344）。
- 起動時に alembic upgrade が走る（Render・zero-downtime デプロイ）＝**新インスタンスがマイグレーションを流した後、旧コードが数分〜（新デプロイ失敗時は長時間）新スキーマ上で動く**。

### フロントエンド（Next.js 15 App Router、Vercel。デザインは明朝・角丸0・苔色）
- 入力箇所3つ:
  1. `web/src/app/review/page.tsx`（依頼者→業者の専用評価画面。★5段階＋「良かった点」タグ6個→comment 末尾に「良かった点: …」を付与。MAX_COMMENT=300。CSS: `review/review.css` の `.tag-chip` 等）
  2. `web/src/app/cases/[id]/page.tsx:1039-1108`（依頼者→業者のインライン評価。★既定5・Tailwind）
  3. `web/src/app/operator/transactions/[id]/page.tsx:390-425`（業者→依頼者。★既定5・operator-shared.css）
- 表示箇所4つ: 入札一覧 `cases/[id]/page.tsx:689-717`（★平均＋件数＋最新の口コミ）／業者一覧 `vendors/page.tsx:25-28, 73（「5段階評価」表記）, 297-311`／公開プロフィール `vendors/[id]/page.tsx:26-29, 124-130, 167-200`／業者の自社プロフィール `operator/profile/page.tsx:101-105, 646-663`。
- 型: `web/src/lib/katadzuke-api.ts` Operator:34, OperatorPublic:46-55, ReviewOut:286-293, OperatorProfile:443-453, PublicReview:532-537, OperatorPublicProfile:552-553, VendorListItem:569-571, createReview:1899-1904。
- E2E: `web/e2e/04-schedule-reduction-complete.spec.ts:70-75`（「5つ星」ボタンを押して「評価を送信する」）。
- 用語ルール（依頼者向け文面）: 「品物」「1点」「引き取り」（×回収）。「入札（買取総額）」が軸で「見積もり」は使わない。

## 叩き台の設計判断（architect に反証・確定してほしい）
D1 データ: `reviews.verdict VARCHAR(16) NOT NULL` + CHECK (verdict IN ('good','improve'))。既存行は rating>=4→'good'、<=3→'improve' で backfill（「よかった」は明確な満足の表明であり、★3「普通」は含めない）。
D2 旧列: `reviews.rating` は NOT NULL のまま残し、新API経由の評価には互換値（good→5, improve→2 ※/review の旧ラベルで2=「もう少し…」）を書く。`operators.rating`（平均）も集計で従来どおり維持（内部の互換値。公開APIからは外す）。
    理由: 旧コードが新スキーマ上で動く窓（zero-downtime デプロイ・デプロイ失敗・ロールバック）で、旧コードの読み取り（ReviewOut.rating: int 等）が NULL で 500 にならないようにする。旧コードの**書き込み**だけは verdict NOT NULL で失敗する（窓の間だけ・5xx で検知可能・再試行で回復）。
D3 集計: `operators.good_count` / `operators.improve_count`（INT NOT NULL DEFAULT 0）を追加し、マイグレーションで可視の user→業者レビューから backfill。recalc で両方を再計算（review_count = 可視件数のまま）。
D4 API入力: ReviewCreateRequest に `verdict: Literal['good','improve'] | None`。旧クライアント（開きっぱなしのタブの旧JS）互換として `rating`(1–5) も受け、verdict 未指定時のみ rating から導出（>=4 good）。verdict 指定時は rating を無視し互換値を書く。両方無しは 422。
D5 API出力: ReviewOut / PublicReviewOut に `verdict` 追加、`rating` は公開系（PublicReviewOut・業者系の各 Out）から外す。業者系 Out（OperatorOut, OperatorPublicOut, OperatorProfileOut, OperatorPublicProfileOut, OperatorPublicListItemOut）に `good_count`, `improve_count` を追加し `rating` を外す。ReviewOut.rating も外す（互換値を見せない）。
D6 並び: GET /vendors は「口コミあり→よかった件数 DESC→伸びしろ件数 ASC→登録の古い順」。画面の説明文も「『よかった』の多い順」に合わせる。
D7 デプロイ順: backend のコミットを先に push→Render live 確認→web のコミットを push（新web→旧backendの422窓を作らない）。push はユーザー承認事項。
D8 画面: 共通コンポーネント `ReviewComposer`（2択＋候補チップ＋自由記述＋文字数）を3つの入力箇所で共用。評価を選ぶまで候補は出さない（選んだ評価に合う候補だけを出す＝肯定側だけに誘導しない）。チップをタップ→コメント末尾に追記、もう一度タップ→その文を除去（選択状態はコメント本文に含まれるかで導出）。上限超過になるチップは無効化。既定値は置かない（★既定5のような暗黙の送信を無くす）。上限は 300 字で統一。
D9 候補文（方向×評価）:
  - 依頼者→業者 よかった: 安心して取引できました！／スムーズでした！／対応が早くて助かりました！／説明が丁寧でわかりやすかったです！／運び出しが丁寧でした！／買取金額に満足しています！／またお願いしたいです！
  - 依頼者→業者 伸びしろ: 連絡がもう少し早いと助かります／時間どおりに来ていただけるとさらに安心です／金額の説明がもう少し詳しいとうれしいです／運び出しがもう少し丁寧だとさらに安心です／減額の理由をもう少し詳しく知りたかったです
  - 業者→依頼者 よかった: 安心して取引できました！／スムーズでした！／事前の写真と説明が正確で助かりました！／引き取りの準備をしていただき助かりました！／連絡が早くて助かりました！／またよろしくお願いします！
  - 業者→依頼者 伸びしろ: 連絡がもう少し早いと助かります／事前の写真と実物がそろっているとさらに助かります／日程の変更は早めにご連絡いただけると助かります／運び出しの経路を空けていただけると助かります
D10 表示: 件数表示「よかった N・伸びしろ M」（口コミ0件は従来どおり「口コミはまだありません」）。公開プロフィールの各口コミに評価バッジ（よかった／伸びしろ）。
