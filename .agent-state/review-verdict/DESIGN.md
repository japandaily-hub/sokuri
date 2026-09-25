# 確定設計: 評価の2択化（よかった／伸びしろ）＋コメント候補のワンタップ入力（2026-09-25）

## 【改訂 2026-09-25 午後】番号の振り直しとレビュー反映（本節が以下の本文より優先）
- 別セッションの `0039_sessions_revoked_at`（停止解除時のセッション失効・624face）が先にコミットされたため、こちらは
  **0040_review_verdict**（down=0039_sessions_revoked_at・本文の「0039」はこれを指す）へ振り直し。
- **0041_review_verdict_recount を P2 に追加**（DDL なしのデータ補正）: P1〜P2 の間に旧コードが書いた verdict NULL 行の補完と、
  全業者の good/improve/review_count の再計算。security Medium 1・QA #7（非表示の口コミが件数差から推測できる・順位が水増しのまま残る）への対応。
  P2 は migration を含むが DDL が無いので、失敗しても「新コード×P1 済みスキーマ」で動く（安全）。
- contract は **0042**（本文の「0040（contract）」はこれを指す）。
- head の固定: 0040 のテストでは固定しない（P1 単体の時点）。0041 のテストで `get_heads()==["0041_review_verdict_recount"]`。分岐防止は test_0036 の `len(get_heads())==1`。
  別セッションの test_0039 の head 固定は、こちらの P1 コミットで外す（先方へ連絡済み）。
- レビュー反映（P2）: reviews.py の assert を明示 422 へ／flush〜commit を try で囲み二重投稿の IntegrityError を 409 に／Review モデルへ本番既存の一意制約・rating CHECK を宣言。
- レビュー反映（P3）: /review 送信直後の「評価投稿済み（）」空括弧の解消／radio の aria-describedby 重複除去／入札一覧の件数表示の途中折り返し解消／radio を選択肢の枠全体に透明で重ねる（E2E の check() が図形に遮られた件・リーダー修正済み）。
- 見送り（ユーザー報告に載せる）: 移行時のロック順（Low・P1 は失敗しても旧コード×旧スキーマで安全）、口コミ上限 300/1000 の不一致（contract で揃える）、「よかった」件数順の並びが件数水増しに弱い点（並び方の方針はユーザー判断）。

architect（opus）確定設計を全面採用。叩き台は同フォルダの DESIGN_DRAFT.md。
リーダーが根拠を実物で再確認済み: backend/start.sh:39-57（alembic が3回失敗しても uvicorn を起動＝degraded）、
render.yaml:36 healthCheckPath=/health（スキーマ状態を見ない）、backend/app/services/text_sanitize.py
（NFKC＋Unicode カテゴリ C* 除去＝改行は消え、全角「！」「？」は半角「!」「?」になる）。

## 共通の運用ルール（実装担当向け）
- **コミット・push はしない**（リーダーが pathspec 指定でコミットする）。git add もしない。
- backend 担当は backend/ 配下だけ、frontend 担当は web/ 配下だけを触る（相互に相手の領域を編集しない）。
- 反映は3段階: **P1**＝0039 マイグレーションとそのテストのみ → **P2**＝backend コード → **P3**＝web。
  P1 のファイルだけで（旧アプリコードのまま）pytest 全件が緑であること。P2 を足しても全件緑であること。
- 既存コードのスタイル（日本語コメントの密度・命名・レビュー番号付きコメントの流儀）を継承する。

## 叩き台からの主な変更点
- reviews.verdict は 0039 では NULL 可（CHECK 付き）。NOT NULL 化は後続 0040（別チケット）。NULL 行は Review.verdict のハイブリッド（rating≥4→good）で読む。
- rating は NOT NULL のまま。新API経由の評価には互換値 good→5・improve→2 を書く（旧 /review ラベル「5 最高でした」「2 もう少し…」）。
- 集計の backfill で review_count も同じ母集団から再計算（不変条件 review_count = good_count + improve_count）。SQLite 両対応のため相関サブクエリで書く。
- 集計クエリは `count(*) FILTER (WHERE …)` を with_only_columns で1回（GROUP BY は使わない）。
- 応答から rating を消すのは 0040 に延期。今回は項目の**追加のみ**（P2〜P3 の間に旧 web が壊れないように）。OperatorOut には件数を足さない。
- GET /vendors の並びは `good_count DESC, improve_count ASC, created_at ASC, id ASC`（「口コミあり」キーは置かない）。
- 候補文は文末記号で完結させ、区切りは必要なときだけ半角スペース（改行はサーバで消えるため）。評価を切り替えても本文は消さない。
- 伸びしろ側の候補文末は「。」。用語ルールに合わせ「買取金額」→「買取総額」。
- cases/[id] の「詳しく評価する →」（:1100-1105 付近）は削除（入力UIが /review と同一になるため）。

## (1) DB マイグレーション 0039（backend 担当・P1）
- ファイル: backend/alembic/versions/0039_review_verdict.py、revision=`0039_review_verdict`（19字）、down_revision=`0038_clear_deleted_op_line_ids`。作成直前に `alembic heads` が 0038 の1本であることを確認。
- ロガー `logging.getLogger("alembic.versions.0039_review_verdict")`（0038 と同方式）。app のコードは import しない。閾値4が app 側 `LEGACY_GOOD_MIN_RATING` と同値である旨をコメントに書く。
- PG では全体が1トランザクション。operators の ALTER は最後寄りに置き ACCESS EXCLUSIVE 保持を最短に。
- upgrade:
  - U0: PG のみ `SET LOCAL lock_timeout = '10s'`
  - U1: `with op.batch_alter_table("reviews")`: `add_column(verdict String(16), nullable=True)` と `create_check_constraint("ck_reviews_verdict", "verdict IN ('good','improve')")`（NULL は CHECK を通る＝expand 期間中の旧コード INSERT を許す）
  - U2: `UPDATE reviews SET verdict = CASE WHEN rating >= 4 THEN 'good' ELSE 'improve' END WHERE verdict IS NULL`（reviewer_type 問わず・非表示行も含む）
  - U3: operators に good_count / improve_count（Integer, NOT NULL, server_default "0"）を add_column
  - U4: 補正対象の業者数（review_count が「非表示を除く依頼者→業者レビュー件数」と不一致）を先に数える
  - U5: 全業者を相関サブクエリで UPDATE（good_count / improve_count / review_count。母集団は recalc と同じ: reviewer_type='user' AND hidden_at IS NULL）
  - U6: INFO ログ「0039: reviews.verdict を N 件設定（依頼者→業者: よかった a／伸びしろ b〔うち★3 c〕、業者→依頼者: よかった d／伸びしろ e）。業者 M 件の集計を再計算（review_count の補正 f 件）。」f>0 なら WARNING。
- downgrade: PG のみ lock_timeout → operators の improve_count / good_count を drop → batch で ck_reviews_verdict を drop → verdict を drop。rating は一度も書き換えないので旧コードはそのまま動く。review_count の補正は戻さない。
- [要確認] SQLite batch で既存の名前付き CHECK / FK が作り直し後も残るか → マイグレーションテストで判定。

## (2) API コントラクト（P2 で有効。web は P3 でこれに合わせる）
| スキーマ | 追加 | 残す（非推奨・0040で削除） | 備考 |
|---|---|---|---|
| ReviewCreateRequest | `verdict: "good"\|"improve"`（任意） | `rating: int 1–5`（必須→任意） | 入力規則は下 |
| ReviewOut | `verdict`（非NULL） | `rating` | POST /reviews・取引詳細 reviews[]・PATCH /admin/reviews/{id}/hide |
| PublicReviewOut | `verdict` | `rating` | /vendors/{id} の reviews[] |
| OperatorPublicOut | `good_count`, `improve_count`（int・既定0） | `rating` | 入札一覧・取引詳細の operator |
| OperatorProfileOut | 同上 | `rating` | 自社プロフィール |
| OperatorPublicProfileOut | 同上 | `rating` | 公開プロフィール |
| OperatorPublicListItemOut | 同上 | `rating` | GET /vendors |
| OperatorOut | なし | `rating` | admin・業者本人（web 未使用） |
- 入力規則: verdict も rating も無い→422「評価（よかった／伸びしろ）を選んでください。」／両方→verdict を採用し rating は無視／保存する rating は verdict 指定時 good=5・improve=2、rating のみの旧形式は受け取った値のまま保存し verdict は rating≥4→good それ以外→improve。comment は現状どおり（1000字・無害化）。ステータスコードは不変（201/403/404/409/422）。
- good_count / improve_count は「依頼者→業者・非表示を除く」＝review_count と同じ母集団。常に review_count = good + improve。
- web の型: `ReviewVerdict = "good" | "improve"` を追加。全ての型から rating を消す（応答に残っていても使わせない）。createReview の payload は `{ transaction_id; verdict; comment? }`（rating は送らない）。

## (3) 集計と GET /vendors（backend 担当・P2）
- Review モデル（transaction.py）: 列属性 `_verdict = mapped_column("verdict", String(16), nullable=True)`、公開名はハイブリッドプロパティ `verdict`（インスタンス: `_verdict or verdict_from_rating(rating)`／SQL: `COALESCE(verdict, CASE WHEN rating >= 4 THEN 'good' ELSE 'improve' END)`／setter は `_verdict`）。定数 `LEGACY_GOOD_MIN_RATING = 4`、`COMPAT_RATING_BY_VERDICT = {"good": 5, "improve": 2}`、関数 `verdict_from_rating()` を Review 直前に置き唯一の対応表とする。CHECK は __table_args__ にも宣言（テストの create_all でも効くように）。Pydantic は from_attributes で `verdict` を読むので model_validate の呼び出し側は変更不要（実装時に確認）。
- reviews.py: 入力規則どおり `Review(verdict=…, rating=…)`。
- recalc_operator_review_stats: 行ロック維持。`base.with_only_columns(func.count().filter(Review.verdict == "good"), func.count().filter(Review.verdict == "improve"))` の1回で件数を取り review_count = good + improve。rating の AVG は残す（P2〜P3 の旧 web 表示とロールバック用。0040 で停止）。latest_review_comment は不変。
- GET /vendors: `ORDER BY good_count DESC, improve_count ASC, created_at ASC, id ASC`。summary・docstring を「『よかった』の多い順（同数なら『伸びしろ』の少ない順、次に登録の古い順）」に。

## (4) 変更ファイル（担当ごとに重なりなし）
- backend・P1: `backend/alembic/versions/0039_review_verdict.py`（新規）、`backend/tests/test_0039_review_verdict_migration.py`（新規）、`backend/tests/test_0037_0038_migrations.py`（:183 付近の head 固定を 0039 テストへ移す。get_heads を使う他テストも同様）
- backend・P2: `backend/app/db/models/transaction.py`、`backend/app/db/models/operator.py`、`backend/app/schemas_katadzuke.py`、`backend/app/api/v1/endpoints/reviews.py`、`backend/app/services/review_stats.py`、`backend/app/api/v1/endpoints/operator_profile.py`、`backend/app/api/v1/endpoints/admin.py`（:543 docstring）、`backend/tests/test_katadzuke_api.py`、`backend/tests/test_deleted_operator_token_revocation.py`（入札一覧の operator 組み立てが model_validate か実装時に確認）
- frontend・P3: `web/src/lib/katadzuke-api.ts`、`web/src/lib/review-verdict.ts`（新規）、`web/src/components/kdz/ReviewComposer.tsx`（新規）、`web/src/components/kdz/review-composer.css`（新規）、`web/src/app/review/page.tsx`、`web/src/app/review/review.css`、`web/src/app/cases/[id]/page.tsx`、`web/src/app/operator/transactions/[id]/page.tsx`（`.review-stars-input` を定義する CSS も grep で特定）、`web/src/app/vendors/page.tsx`、`web/src/app/vendors/vendors.css`、`web/src/app/vendors/[id]/page.tsx`、`web/src/app/vendors/[id]/vendor.css`、`web/src/app/operator/profile/page.tsx`、`web/src/app/operator/profile/profile.css`、`web/e2e/04-schedule-reduction-complete.spec.ts`
- 対象外（誤検知）: web/src/lib/api.ts:11 の「5段階」は品物のコンディション／operator/profile :529・:536・:693 と vendors/[id] :149 の★は得意カテゴリの印／scripts とシードに rating 参照なし／alembic 0004・0024 は履歴。

## (5) フロントの共通部品（frontend 担当・P3）
- `web/src/lib/review-verdict.ts`（React 非依存・候補文の唯一の置き場所）:
  - `REVIEW_VERDICT_LABEL = { good: "よかった", improve: "伸びしろ" }`、`REVIEW_COMMENT_MAX = 300`、`REVIEW_PHRASES: Record<"to_operator"|"to_user", Record<ReviewVerdict, readonly string[]>>`、プレースホルダ（既存文言「業者の対応の感想（任意）」「取引の感想（任意）」）
  - `hasPhrase(text, p)`／`appendPhrase(text, p)`（末尾空白を除いて追記。直前が 。！？!? 以外なら半角スペース1つを挟む）／`removePhrase(text, p)`（最初の出現と、追記時に挟んだスペース1つだけを消す。他の本文に触れない）／`canAppend(text, p)`（区切り込みで300字以内か）／`formatVerdictCounts(good, improve)`→「よかった 3・伸びしろ 1」
  - 不変条件: 同じ方向の中で、ある候補文が別の候補文の部分文字列にならない。
- 候補文（確定）:
  - 依頼者→業者・よかった: 安心して取引できました！／スムーズでした！／対応が早くて助かりました！／説明が丁寧でわかりやすかったです！／運び出しが丁寧でした！／買取総額に満足しています！／またお願いしたいです！
  - 依頼者→業者・伸びしろ: 連絡がもう少し早いと助かります。／時間どおりに来ていただけるとさらに安心です。／金額の説明がもう少し詳しいとうれしいです。／運び出しがもう少し丁寧だとさらに安心です。／減額の理由をもう少し詳しく知りたかったです。
  - 業者→依頼者・よかった: 安心して取引できました！／スムーズでした！／事前の写真と説明が正確で助かりました！／引き取りの準備をしていただき助かりました！／連絡が早くて助かりました！／またよろしくお願いします！
  - 業者→依頼者・伸びしろ: 連絡がもう少し早いと助かります。／事前の写真と実物がそろっているとさらに助かります。／日程の変更は早めにご連絡いただけると助かります。／運び出しの経路を空けていただけると助かります。
- `ReviewComposer.tsx`（"use client"）＋`review-composer.css`（ルート `.kdz-review-composer` 配下に限定・既存CSS変数・明朝・角丸0・色直書きなし）:
  - props `{ direction: "to_operator"|"to_user"; submitLabel: string; busy: boolean; onSubmit: (v: { verdict: ReviewVerdict; comment?: string }) => void | Promise<void> }`。submitLabel は既存文言（「評価を送信する」「評価を投稿する」「レビューを投稿」）をそのまま渡す。
  - 内部状態は `verdict: ReviewVerdict | null`（初期 null・既定値なし）と `comment` のみ。チップの選択状態は `hasPhrase(comment, p)` で導出。送信失敗時は入力を残す。
  - 評価を選ぶまではチップを出さず「『よかった』か『伸びしろ』を選ぶと、よく使われる文を1タップで入力できます」と案内。評価の切替でチップ組を入れ替え、本文は消さない。チップのタップでテキストエリアへフォーカスを移さない。選択中チップは常に押せる（削除）。上限を超えるチップは追加不可。送信 comment は `comment.trim() || undefined`。送信ボタンは busy 中と verdict===null の間は押せない。
  - a11y: 評価は `<fieldset><legend>`＋native radio 2つ（ラベル全体がタップ領域・高さ44px以上・選択は枠線とチェック図形で示し色だけに頼らない）。チップ群は `role="group"` aria-label「よく使われる文（タップで追加・もう一度で削除）」、各チップ `<button type="button" aria-pressed>`、上限で追加不可は `aria-disabled="true"`（フォーカスは受ける）。テキストエリアは `<label>`＋`maxLength=300`、「n/300文字」を aria-describedby で結ぶ。送信不可の理由も aria-describedby。id は useId()。
- 表示4画面: `formatVerdictCounts` を使い表示条件は `review_count > 0`（`rating != null` 判定は廃止）。/vendors/[id] の各口コミに `<span className="review-verdict" data-verdict>` バッジ（文字で区別・色は補助）。投稿済み表示「評価投稿済み（よかった）」等。

## (6) テスト観点
- pytest（test_katadzuke_api.py）: T1 verdict で投稿→201・ReviewOut.verdict・保存 rating 5/2・業者件数／T2 旧形式 rating のみ 4→good、3・1→improve、rating はそのまま／T3 両方→verdict 優先、両方無し・"bad"→422／T4 業者→依頼者は業者集計に入らない／T5 admin 非表示・再表示で件数増減・不変条件維持／T6 旧コードが書いた行（_verdict=None, rating=4）が取引詳細・公開プロフィールで good、集計でも good／T7 GET /vendors 並び (5,5)(3,0)(3,2)(0,0)(0,1) の順、同数は created_at→id／T8 P1〜P3 互換: 各応答に rating が残ることを固定（0040 で意図的に削除する旨 docstring）／T9 候補文3つ連結コメントが無害化を通り「！」→「!」に正規化されることを固定。既存の rating 送信箇所は verdict に置換、旧形式経路は T2 で担保。
- マイグレーションテスト（新規・同期・SQLite ファイル・stamp 0038→upgrade 0039）: 事前スキーマ operators(rating, review_count NOT NULL DEFAULT 0, latest_review_comment, created_at)/bids/transactions/reviews(rating NOT NULL, comment, hidden_at, created_at、名前付き ck_reviews_rating・ck_reviews_reviewer_type・uq_reviews_transaction_reviewer)。データ: 依頼者レビュー★1〜5（1件非表示）、業者レビュー★5・★2、レビュー無し業者、review_count がずれた業者。確認: ★4・5→good／★1〜3→improve（非表示・業者レビュー含む）、件数一致、ずれ補正と WARNING、caplog の INFO、CHECK が 'bad' を拒否し NULL を通す、作り直し後も既存の名前付き制約と FK が残る（sqlite_master・PRAGMA foreign_key_list）、downgrade→upgrade 往復で同結果、downgrade 後は3列が消え rating と行数不変、`get_heads() == ["0039_review_verdict"]`・down_revision 0038・32字以内。
- E2E 04（:73）: 評価前は送信不可 → `getByRole("radio",{name:"よかった"}).check()` → チップ「安心して取引できました！」を押して本文に入る → 「評価を送信する」→「評価を送信しました。」→ API で reviews[].verdict === "good"。
- web: `npm run lint`・`npx tsc --noEmit`・`next build` を通す。375px 幅でチップの折り返しとタップ領域を確認。

## (7) ユーザー判断が要る点（リーダーが報告に載せる）
1. push 3回（P1→/readyz と Render ログで 0039 確認→P2→稼働確認→P3）は本番デプロイ＝ユーザー承認。
2. 0040（contract）の時期（P3 後、開きっぱなしのタブが消えるまで待つ・別チケット）。
3. ★3 を「伸びしろ」に割り当て（満足度調査の top-2-box 慣行）。実データはほぼ無く 0039 のログで件数確認可能。
4. 候補文の最終確認（「買取総額」・伸びしろ側の言い回し）。
5. 伸びしろ件数の公開（メルカリも両方公開）。
6. 「！」が「!」になる・改行が消えるのは既存の無害化仕様。
7. 構造課題（別チケット）: healthCheckPath がスキーマ状態を見ないため migration とコード同梱は常に危険。
8. スコープ外: 業者→依頼者の評価を新たに見せる機能は作らない。
