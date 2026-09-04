# 運営導線 監査台帳 r3-operator.md の独立検証
検証日: 2026-09-04 / 検証者: 独立QA（立案者と無関係）/ 方式: 静的読解（読み取り専用）
対象台帳: `.agent-state/audit/r3-operator.md`
除外条件: `backend/app/config.py` / `backend/app/main.py` / `backend/app/core/alert_middleware.py` / `backend/app/services/alerts.py` への修正提案は却下対象（別セッション編集中）。ただし**読解による反証材料としては参照した**。

---

## 1. 台帳項目の判定

### H1. `/contact` がバックエンド未配線 → **CONFIRMED（High 妥当）**
- 実コード照合:
  - `web/src/app/contact/page.tsx:5-6` 実装者コメント「送信はバックエンド未配線」を確認。
  - `web/src/app/contact/page.tsx:30-59` `onSubmit` は `preventDefault()` → 必須項目/メール形式検証 → `setSent(true)` → `window.scrollTo` のみ。`fetch`/`mailto`/API 呼び出しは1つも存在しない（同ファイル全文 grep で `mailto|fetch|api` の該当0件、ヒットしたのは文言行 `:225` `:259` のみ）。
  - `web/src/app/contact/page.tsx:259` 完了画面「送信を受け付けました（デモ）」、`:261-263`「通常3営業日以内にご連絡いたします。」、`:225`「通常3営業日以内にご返信します。」— 断定表示を確認。
  - バックエンド側に受け口なし: `backend/app/api/v1/router.py` の include 一覧に contact 系ルータは存在しない。
- 重大度判定: **High で妥当**。特商法上の問い合わせ窓口が事実上不在であり、かつ「返信する」と断定表示する点で単なる未実装より悪い（偽の成功表示）。
- 修正案の妥当性: **妥当**。案(2)（フォーム撤去＋直接連絡手段の明示）は最小構成として合理的で、リリースまでの暫定措置として即日実施可能。案(1) の `notify.py` 経由（`app.services.notify` は既存・`operator_applications.py:59` で BackgroundTasks 送信の前例あり）も既存パターンに沿う。

### H2. 運営に案件・取引の横断閲覧/介入手段が無い → **CONFIRMED（High 妥当）**
- 実コード照合:
  - `backend/app/api/v1/endpoints/cases.py:271-281` — `actor.typ == "user"` 分岐は `Case.user_id == actor.user.id` の一択。`role == "admin"` の分岐は無い。
  - `backend/app/api/deps.py:117-125` — `get_current_admin` は `get_current_user`（`typ == "user"` を要求）の上に `role` チェックを乗せるだけ。よって admin トークンは `get_current_actor` 経由で必ず `typ == "user"` 側に落ちる。台帳の推論は正しい。
  - `backend/app/api/v1/endpoints/transactions.py:69-71` — 同様に `Case.user_id == actor.user.id` のみ、admin 分岐なし。
  - 個別取得は admin 許容済み: `cases.py:317`（`if case.user_id != actor.user.id and actor.user.role != "admin"`）、`transactions.py:133`（`or actor.user.role == "admin"`）、`reductions.py:112`（`if txn.case.user_id != user.id and user.role != "admin"`）。→ 「ID さえ分かれば見られるが、ID への到達経路が無い」という台帳の構造把握は正確。
  - 管理画面: `web/src/app/admin/page.tsx` 全642行中、案件/取引への言及は cell-density 集計表（`:541` `:550` `:564` `:586`、`open_cases` 件数のみ）だけ。個別案件・成約への一覧/検索/リンクは0件。
  - `backend/app/api/v1/endpoints/admin.py` の `@router` は17件（`:126,142,161,170,179,207,232,263,311,324,336,380,427,490,554,588,662`）で、case/transaction 系は皆無。強制終了・運営キャンセルのエンドポイントも存在しない。
- 重大度判定: **High で妥当**。
- 軽微な誇張1点: 「実質常に空配列」は不正確で、正しくは「admin 自身が依頼者として作成した案件のみ」。台帳自身が再現手順で括弧書き補足しているため実害なし。
- 修正案の妥当性: **妥当かつ既存パターン準拠**。`admin.py` の全17ルートが `/admin/*` プレフィックス＋`Depends(get_current_admin)` で統一されており、`GET /admin/cases` / `GET /admin/transactions` の追加はこの規約にそのまま乗る。「見える化を先行、強制終了は業務要件確定後」という段階分けも妥当。

### M1. AI解析失敗がどこにも記録されない → **PARTIAL**
- CONFIRMED の部分:
  - `backend/app/api/v1/endpoints/analyze.py` 全体に `logging` の import すら無く、`except ValueError`（`:60-64`）・`except GenAIAPIError`（`:65-70`）とも `logger` 呼び出しゼロ。**アプリ側の構造化ログが皆無**は事実。
  - `/admin` 側に失敗件数・直近失敗時刻の指標が無いのも事実（`web/src/app/admin/page.tsx` の取得APIは `adminGetCellDensity` 等のみ、`:118`）。
- 反証された部分（**却下**）:
  - 「運営が気づく手段はサーバー標準出力を能動的に読みに行くことのみ」は誤り。`backend/app/core/alert_middleware.py:5,40,78` の `ServerErrorAlertMiddleware` は `status >= 500` の応答を例外由来も含めて集計し、window 内 threshold 超過でアラートする。`analyze` の 503（`analyze.py:66-69`）はこの集計対象に入る。`backend/app/main.py:129` で登録済み。
  - 残る真の穴は (i) 閾値未満の低率・持続的失敗は検知されない (ii) 422（`ValueError` 経路、画像不正/レスポンス空）は 5xx でないため**一切**カウントされない (iii) 管理画面での可視化が無い、の3点。
- 重大度判定: **Medium で妥当**（範囲を上記3点に縮めた上で）。
- 修正案の妥当性: **条件付き妥当**。`analyze.py` への `logger.error` 追加は禁止ファイルに触れず即実施可。ただし `GET /admin/health-summary` の新設は、既存 `alert_middleware` のカウンタと二重計装になるため、台帳の「未解決4」の通り担当セッションとの調整が先。

### M2. 一覧系 admin API に件数上限が無い → **CONFIRMED（Medium 妥当・引用行の訂正あり）**
- 実コード照合（**台帳の file:line は取り違えがある**。正: ）
  - `backend/app/api/v1/endpoints/admin.py:161-168` `list_invites` — `select(Invite).order_by(...)` のみ、`limit`/`offset` なし。
  - `backend/app/api/v1/endpoints/admin.py:170-177` `list_operators` — 同上（台帳は `:161-176` を `list_operators` と記載しており、`list_invites` と行範囲が入れ替わっている）。
  - `backend/app/api/v1/endpoints/admin.py:495-553` `list_identity_documents` — `status_filter` のみ、`limit`/`cursor` なし。
- **台帳の見落とし（追記）**: `admin.py:311-321` `list_operator_applications` も同じく無制限全件返却。事前申込は公開エンドポイント（`operator_applications.py:49-55`、認証不要）から流入するため、実は4本の中で最も件数が伸びやすい。
- 重大度判定: **Medium で妥当**（ベータ規模では実害軽微という前提評価も妥当）。修正案（`limit`/`offset` 追加＋段階的なサーバーサイド検索移行）も既存パターンを壊さない。

---

## 2. 「確認したが問題なし」節の抜き取り検証（3項目）

| 項目 | 判定 | 根拠 |
|---|---|---|
| admin 認可の境界 | **妥当（軽微な数値誤り1件）** | `admin.py` の `@router` は17件、`Depends(get_current_admin)` も17件（`:129,145,163,172,183,211,236,265,313,329,343,388,436,499,561,595,670`）で1対1対応。例外ルートは無く結論は正しい。ただし台帳の「@router 22件」は誤り（実際は17件）。 |
| ファイル配信 `/files/{storage_key}` | **妥当** | `case_photos.py:111-118` `serve_file` は確かに無認証だが、`operator_license.py:1-8` と `user_identity.py:1-9` の冒頭 docstring に「presign/`/files/{key}` 方式は絶対に再利用しない」旨が明記され、実装も BYTEA 直保存＋認証必須配信（`admin.py:554-585`）になっている。設計判断としての整合を確認。 |
| PII 監査ログ | **妥当** | `admin.py:528-535`（書類一覧・件数とフィルタのみ）、`:573-579`（書類閲覧・document_id/side）、`:365-371`（口座復号・application_id）いずれも `admin.id`/`admin.email` 付き `logger.info`。PII 本体は含まれない。アプリログ止まりという限界の記述も正確。 |

---

## 3. 追加発見（台帳に無い High・同一観点）

### ADD-H1. `POST /analyze` が**無認証かつレート制限なし**で、Gemini クォータを外部から枯渇させられる
- 根拠: `backend/app/api/v1/endpoints/analyze.py:47-51` — 依存は `session` のみ。`get_current_user`/`get_current_actor` も `RateLimitGuard` も無い（同ファイル `get_current_*` grep 該当0件）。`backend/app/api/v1/router.py:31` で無条件に公開。
- 対比（＝コードベースには既にパターンがある）: `cases.py:121` `RateLimitGuard("case_create")`、`auth.py:90,129` `signup`/`login`、`user_identity.py:171` `identity_submit`、`operator_applications.py:67-92` は独自の IP 単位レート制限を実装。**`/analyze` だけが例外**。
- 影響: 匿名の第三者が課金・クォータ制のある Gemini 呼び出し（`app/services/vision.py:263-282`）を無制限に発火でき、`items` テーブルへも無制限に INSERT される。同時実行 Semaphore（`vision.py:283-285` 付近）は輻輳は抑えるが総消費量は抑えない。運営側にはスロットルも緊急停止スイッチも無く、M1 の通り可視化も無い。
- 修正案（最小）: `analyze.py` の署名に `_rl: object = Depends(RateLimitGuard("analyze"))` を追加し、`rate_limit_deps.py` に `analyze` スコープの上限とメッセージを1行足す（`case_cancel` と同形。`:208`,`:411` が雛形）。config.py には触れない。

### ADD-H2. 依頼者（User）に対する**利用停止・凍結の手段が API・UI・DB のいずれにも存在しない**
- 根拠: `backend/app/db/models/user.py:39-87` のカラムに停止フラグ相当が無い（`deleted_at:85` は本人退会の論理削除、`identity_status:80` は書類審査用）。業者側にある `Operator.is_suspended`（`admin.py:207-229` `suspend_operator`、`deps.py:139` `assert_operator_not_suspended`）に対応する仕組みが User 側に無い。
- `admin.py` の17ルートに `/admin/users` 系は皆無。管理画面 `web/src/app/admin/page.tsx` にも依頼者の検索/参照 UI は無い。
- 影響: スパム出品・虚偽案件・業者への嫌がらせを行う依頼者を運営が止められない。書類却下（`admin.py:662-`）はできても、アカウント自体は生き続け新規案件を出し続けられる。H2 を修正して「見える」ようになっても「止められない」ままである。
- 修正案（最小）: `User` に `is_suspended`（既存 `Operator` と同形）を追加し、`deps.py` の `assert_user_not_revoked` に停止ゲートを1行追加、`admin.py` に `PATCH /admin/users/{id}/suspend` を `suspend_operator:207-229` と同形で新設。

### ADD-H3. admin 権限の**付与経路が新規サインアップ時の一度きり**で、後から誰も管理者にできない
- 根拠: `backend/app/api/v1/endpoints/auth.py:108` `role = "admin" if email in get_settings().admin_emails else "user"` — これがバックエンド全体で唯一の `role="admin"` 代入（`backend/` の `role="admin"` grep はここ＋tests のみ）。
- LINE 経由の新規ユーザーは `auth.py:633-638` で `role="user"` 固定。ログイン時に role を再評価する処理も無い。
- `ADMIN_EMAILS` は `render.yaml:57-58` に値付きで定義されているが、既存サービスへの envVars 同期は行われない仕様（既知事項）。
- 影響: (i) スタッフを増員しても、既に登録済みのアカウントは `ADMIN_EMAILS` に追記しても永久に一般ユーザーのまま (ii) 管理者が LINE でサインアップしてしまうと admin になれない (iii) 復旧手段は DB への直接 UPDATE のみ。
- 修正案（最小）: `auth.py` のログイン成功時に `email in admin_emails and user.role != "admin"` なら role を昇格させる（降格はしない）3行を追加。config.py には触れない。

---

## 4. (b) 台帳の全項目を修正しても運営がサービスを回せないケース

**あり。** ADD-H3 がそれに該当する。H1・H2・M1・M2 をすべて実装しても、**それを操作できる admin アカウントを作れない／増やせない**状況が成立しうる。具体的には、`ADMIN_EMAILS` が現行の Render サービスに実際に反映されているかは render.yaml の記述からは保証されず（既存サービスへ envVars は同期されない）、また運営担当を1名でも追加しようとした瞬間に「既存アカウントは昇格不可・新規サインアップし直しか DB 直接 UPDATE」という詰みが発生する。新設した `/admin/cases` も `/admin/transactions` も、admin ロールを持つ者が誰もいなければ 403 を返すだけの飾りになる。**H1/H2 の実装より先に、admin 昇格経路（ADD-H3）と本番での ADMIN_EMAILS 実効値の確認を済ませるべき。**

---

## サマリ
結論: 台帳の High 2件はいずれも**実コードで裏付けを取り CONFIRMED**。Medium は1件 CONFIRMED・1件 PARTIAL（M1 は `alert_middleware` の 5xx 集計により「気づく手段が皆無」という前提が反証され、真の穴は「422 が非集計」「低率失敗の見逃し」「管理画面の可視化欠如」の3点に縮小）。「問題なし」節の3項目は抜き取り検証の結果いずれも妥当（`@router 22件` の数値のみ誤り、実際17件）。
✅達成: 判定 CONFIRMED 3 / PARTIAL 1 / REJECTED 0。認可境界・PII ログ・ファイル配信の健全性は独立に再確認。
⚠️課題: 追加 High 3件（`/analyze` 無認証・無制限／依頼者の停止手段の完全欠如／admin 昇格経路の一度きり）。M2 は `list_operator_applications:311-321` の見落としあり、引用行にも取り違えあり。
❌ブロッカー: ADD-H3。admin を作れない・増やせない状態では、H1/H2 の修正成果を運営が使えない。実装着手より先に本番の ADMIN_EMAILS 実効値を確認すること。
