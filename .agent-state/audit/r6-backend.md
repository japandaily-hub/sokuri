# r6 backend 監査（運用開始後に静かに壊れる欠陥）— 2026-09-04

対象: `backend/`（読み取りのみ・編集なし）。既知/意図的未対応（`docs/TODO.md` 03・`.agent-state/PROJECT_STATE.md`）は再指摘していない。
観点: 状態遷移の同時実行、N+1/索引、設定の起動時検証、BackgroundTasks、レート制限、画像ストレージ、日時、0025/0026 の適用安全性。

---

## High

### H-1 案件作成が「リクエスト内で最長175秒のAI解析」を直列実行する → プロキシ側タイムアウトで二重案件

- 箇所: `backend/app/api/v1/endpoints/cases.py:186-231`（`generate_case_ai` / `generate_case_summary` を commit 前に await）、`backend/app/services/summary.py:31`（`_ANALYZE_IMAGE_TIMEOUT_SEC = 25`）、`backend/app/services/summary.py:95-100`（未分類写真の解析が **for ループの逐次**）、`backend/app/services/summary.py:300-315`（items 予算 8 コール／同時実行 3）
- 事象: 最悪値は「未分類写真 4 枚 × 25 秒 = 100 秒（逐次）」＋「items 8 コール ÷ 同時実行 3 = 3 波 × 25 秒 = 75 秒」で **1 リクエスト約 175 秒**。Cloudflare の応答待ち上限（100 秒／524）を超えると、依頼者のブラウザにはエラーが出るが **サーバ側は解析を続行し `session.commit()` して案件を作る**。依頼者は失敗したと思って再送信し、同一内容の案件が 2 件（以上）並ぶ。業者側には重複案件が見え、Gemini コストも二重。さらに `rl_case_create_account_max = 10/時`（`config.py:143-145`）は成否を問わずカウントするため、数回の再送信で本人が 429 に落ちる。
- 再現条件: Gemini のレスポンスが遅い時間帯（または `gemini_max_retries` によるリトライが発生した時）に、商品 4 点以上＋未分類写真ありの案件を作成する。
- 修正案（最小差分）: `cases.py` の AI 解析ブロック全体を `async with asyncio.timeout(45):` で囲み、超過時は既存の `except Exception` フォールバック文言に落とす（`cases.py:232-234` の経路をそのまま使うので差分は 2 行）。併せて `summary.py:95-100` の逐次ループを `asyncio.gather` に変える（プロセス全体の Semaphore が別途上限を掛けているため輻輳は増えない）。

### H-2 写真の保存先が Render の一時ディスク。15 分スピンダウンのたびに全消失し、`/files/{key}` が恒久 404 になる

- 箇所: `render.yaml:59-60`（`STORAGE_DIR=/tmp/uploads`）、`backend/app/config.py:62-63`、`backend/app/services/storage.py:56-59`、`backend/app/api/v1/endpoints/case_photos.py:111-118`
- 事象: Render Free Web は 15 分無アクセスでインスタンスが破棄され、次アクセスで新しいファイルシステムが起動する（デプロイ時だけの話ではない）。`case_photos` の行と `storage_key` は DB に残るのに実体が無いため、`GET /files/{key}` が **恒久的に 404** になる。画面はエラーを出さず画像だけが割れる＝典型的な「静かに壊れる」。前日までの案件は業者から写真無しに見え、入札根拠が消える。AI 要約（`cases.ai_summary`）だけが残るため、運営も気付きにくい。
- 再現条件: 案件作成 → 15 分以上アクセスが無い → 再アクセスして案件詳細を開く。
- 修正案（最小差分）: β運用として許容するなら、`serve_file`（`case_photos.py:112-118`）で 404 時に `logger.warning` ＋ `alerts.fire_and_forget`（key 固定でクールダウン）を出し、写真消失を運営が検知できるようにする。恒久対応は Cloudflare R2 等への差し替え（`storage.presign_upload` の返却 URL 差し替えのみで済む設計になっている＝`storage.py:1-7`）。

### H-3 メール／LINE 通知の「実行時失敗」が無音（アラートはキー未設定時のみ）

- 箇所: `backend/app/services/notify.py:66-82`（未設定時のみ `alerts.send_alert`）、`backend/app/services/notify.py:98-100`（**送信失敗は `logger.error` のみ**）、`backend/app/services/line_notify.py:71-73`（同上）
- 事象: `BREVO_API_KEY` が「設定されているが無効」な状態—失効・権限変更・**Brevo 無料枠の 1 日 300 通到達（429）**・送信ドメイン未認証（401/402）—では `_send` が `False` を返して静かに終わる。`notify_dispatch._best_effort`（`notify_dispatch.py:48-67`）も例外を握るため、入札通知・落札通知・日程確定・申込受付が **1 通も届かないまま画面上は正常** に見える。Render Free のログ保持は 7 日で、運営が気付く経路が存在しない。
- 再現条件: Brevo の日次上限に到達させる、または API キーを失効させて任意の通知を発火させる。
- 修正案（最小差分）: `notify.py:98-100` の `except` 内に、`notify.py:70-81` と同じ `alerts.fire_and_forget(alerts.send_alert(..., key="notify_brevo_send_failed"))` を 1 ブロック足す（`alerts.send_alert` 側に key 単位のクールダウンがあるため連打しない）。`line_notify.py:71-73` も同様。

### H-4 本番必須設定のうち、起動ガードにも `/readyz` にも現れないキーがある（APP_ENCRYPTION_KEY 未設定で業者の事前申込が全滅）

- 箇所: `backend/app/main.py:77-113`（本番ガードは **JWT_SECRET / DATABASE_URL / ALLOWED_ORIGINS のみ**）、`backend/app/main.py:152-268`（`/readyz` は DB 到達性と alembic リビジョンのみ）、`backend/app/config.py:70-75`（`app_encryption_key`・`line_channel_access_token` の既定値は空文字）、`backend/app/core/crypto.py:31-47`
- 事象: `APP_ENCRYPTION_KEY` は `render.yaml:76-80` で `sync: false`＝ダッシュボード手動入力のため、サービス再作成・DB 差し替え時に落としやすい。未設定のまま起動すると **起動は成功し `/health` も `/readyz` も 200** を返すが、口座情報を含む業者の事前申込（`bank_account_enc`）・口座登録が `EncryptionKeyMissingError` → 500 で全滅する。業者オンボーディングが止まっているのに外形監視は緑のまま。鍵を**入れ替えた**場合はさらに静かで、`admin.py:123-137` が復号失敗を `logger.error` して `bank_account=None` を返すため、管理画面は「口座未登録の申込」として何事もなく表示される。`GOOGLE_API_KEY` 未設定も同様に AI 要約が常時フォールバック文へ落ちるだけで可視化されない。
- 再現条件: `APP_ENCRYPTION_KEY` を未設定にして起動し、口座情報付きで `POST /operator-applications` を送る。
- 修正案（最小差分）: `main.py:77` の production ブロックに、`app_encryption_key` が空/不正なら `Fernet(key)` 構築を試して `RuntimeError` で起動中断（JWT_SECRET と同じ扱い）を追加。`brevo_api_key` / `line_channel_access_token` / `google_api_key` は起動を止めず、`/readyz` の payload に `"config": {"mail": bool, "line": bool, "vision": bool, "crypto": bool}` を足して外形監視から欠落を見えるようにする。

---

## Medium

### M-1 成約（Transaction）側の状態遷移だけロック規約に参加していない

- 箇所: `backend/app/api/v1/endpoints/transactions.py:225-247`（complete）、`:254-285`（cancel）、`:471-500`（confirm_schedule）。いずれも `lock_case_row` 相当の `with_for_update` も条件付き UPDATE も無い（cf. `bids.py:118`・`bids.py:224`・`cases.py:357`・`case_lock.py:22-28`）
- 事象: 依頼者の「完了」と業者の「キャンセル」が同時に走ると、双方が同じ `txn.status="pending"` を読んでチェックを通過し、後勝ちで上書きされる。結果として `transactions.status="completed"` なのに `cancellations` 行が存在する／`cases.status="cancelled"` なのに成約は完了、といった相互に矛盾した状態が残り、以後の評価投稿（`reviews.py:65`）や一覧表示が実態とずれる。
- 再現条件: PostgreSQL（READ COMMITTED）で、同一 `transaction_id` に対し complete と cancel をほぼ同時に投げる。SQLite の逐次実行テストでは再現しない。
- 修正案（最小差分）: `case_lock.lock_case_row` と同じ作法で `select(Transaction.id).where(...).with_for_update()` を `_get_txn` の直前に置く共通ヘルパ（`services/txn_lock.py`）を作り、3 ハンドラの先頭で呼ぶ。

### M-2 キャンセルの二重送信で `cancellations` が 2 行、`operator.cancel_count` が 2 加算される

- 箇所: `backend/app/api/v1/endpoints/transactions.py:268-279`、`backend/alembic/versions/0004_katadzuke_schema.py:250-251`（`cancellations` は index のみで `transaction_id` に一意制約が無い）
- 事象: 通信が遅い時のボタン二度押し（M-1 のロック不在と同根）で、キャンセル記録が重複し、業者の `cancel_count` が実際の 2 倍になる。`cancel_count` は業者の評価・停止判断の材料になるため、無実の業者にペナルティが積み上がる。DB 制約が無いため事後の検知も難しい。
- 再現条件: `/transactions/{id}/cancel` を同時に 2 回送る。
- 修正案（最小差分）: `0027` で `op.create_unique_constraint("uq_cancellations_transaction_id", "cancellations", ["transaction_id"])`（既存重複行の有無を先に確認）＋ `transactions.py` 側で `IntegrityError` を 409 に変換（`bids.py:158-170` と同じパターン）。

### M-3 減額申請への回答が成約ステータスを検査しない → 完了後・キャンセル後に成約金額を書き換えられる

- 箇所: `backend/app/api/v1/endpoints/reductions.py:126-155`（`txn.status` のチェックが一切無い。`create_reduction` 側は `:70` で `("pending","visiting")` に限定している）
- 事象: 業者が減額申請 → 依頼者が回答しないまま「完了」（`transactions.py:241-243` で `final_amount = initial_amount` が確定）→ その後に依頼者が古い画面から「承認」を押すと、**完了済み取引の `final_amount` が下がる**。評価済み・精算済みの後でも金額が変わり、記録として一貫しない。キャンセル済み取引でも同様に承認できる。
- 再現条件: pending の減額申請を残したまま `/transactions/{id}/complete` → その後 `PATCH .../reduction/{id}` に `approve`。
- 修正案（最小差分）: `reductions.py:144` の直前に `if txn.status not in ("pending", "visiting"): raise HTTPException(409, "回答できる状態ではありません。")` を追加（`create_reduction` と同じ条件式を使う）。

### M-4 減額申請の「未回答が1件だけ」がアプリ層でしか担保されていない

- 箇所: `backend/app/api/v1/endpoints/reductions.py:75`（`any(r.status == "pending" ...)` の in-memory 判定のみ）、`0004_katadzuke_schema.py` の `reduction_requests` に部分一意索引が無い
- 事象: 同時 2 リクエスト（二度押し・リトライ）で pending が 2 行できる。依頼者が一方に回答しても他方が pending のまま残り、`:75` の判定により **業者は以後永久に減額申請できない**（409 が返り続ける）。運営が DB を直接触るまで復旧できない。
- 再現条件: `POST /transactions/{id}/reduction` を同時に 2 回送る。
- 修正案（最小差分）: `0027` で `CREATE UNIQUE INDEX uq_reduction_requests_pending ON reduction_requests (transaction_id) WHERE status = 'pending'`（PG の部分一意索引。SQLite テストには効かないので `IntegrityError` → 409 変換を `reductions.py` に併設）。

### M-5 業者の案件一覧が無制限（LIMIT なし）で、写真・商品・入札まで一括 eager load する

- 箇所: `backend/app/api/v1/endpoints/cases.py:286-293`（`select(Case).where(status.in_(["open","bidding"]))` に `limit/offset` が無い）、`:84-87`（`_CASE_LOAD` が `photos` / `items→photos` / `bids→operator` / `bids→transaction` を eager load）
- 事象: N+1 ではないが、公開中の案件数に比例して 1 リクエストの行数・JSON サイズが線形に伸びる。案件 1 件あたり写真は最大 150 枚（`cases.py:222` 周辺の上限）まで許容されるため、公開案件が数百件になった時点で Render Free（単一 uvicorn・512MB）で数秒〜十数秒＋数 MB の応答になる。管理画面側（`admin.py:499-500`・`:600-601`・`:684-685`）は r4 でページングされたのに、**業者が毎日開く画面だけが素通し**。
- 再現条件: `cases` に open/bidding の行を数百件用意して業者トークンで `GET /cases`。
- 修正案（最小差分）: `admin_list_cases` と同じ `limit: int = Query(50, le=100)` / `offset` を `list_cases` の業者分岐に付け、`_CASE_LOAD` から一覧では不要な `items→photos` を外した軽量ローダを一覧専用に用意する。

### M-6 `transactions.bid_id` に索引が無い（業者の取引一覧の絞込経路）

- 箇所: `backend/alembic/versions/0004_katadzuke_schema.py:148-152`（FK は張るが索引なし）、`:161-162`（作られる索引は `case_id` と `status` のみ）、`backend/app/api/v1/endpoints/transactions.py:58-75`（業者分岐は `join Bid ... where Bid.operator_id`＝`transactions.bid_id` 経由）
- 事象: 業者の取引一覧・`admin_list_transactions` が `transactions` の全走査に落ちる。行数が少ないうちは表に出ず、成約が積み上がってから徐々に遅くなる（＝静かに劣化する）。`ondelete="RESTRICT"` の FK チェックも同じ索引不在で毎回全走査になる。
- 再現条件: `transactions` が数万行規模になった状態で業者の取引一覧を開く（現時点では未顕在）。
- 修正案（最小差分）: `0027` に `op.create_index("ix_transactions_bid_id", "transactions", ["bid_id"])` を追加。行数が少ない今のうちなら `CONCURRENTLY` 無しでもロック時間は無視できる。

### M-7 業者申込の承認に行ロックが無く、二重承認で招待コードが 2 件発行される

- 箇所: `backend/app/api/v1/endpoints/admin.py:1031-1062`（`application.status != "received"` の判定と `commit` の間に排他が無い）、`:114-119`（`_issue_unique_invite_code` は SELECT→生成のチェックのみ）
- 事象: 承認ボタンの二度押し／管理者 2 名の同時操作で、`invites` に有効なコードが 2 件でき、承認メールも 2 通飛ぶ。`application.invite_code`（r5 で追加した本登録追跡用・`0026`）は後勝ちで 1 件しか残らないため、**先に発行された方のコードで本登録されると申込と業者の紐付けが辿れない**。もう一方のコードは未使用のまま有効（誰かに転送されれば使える）。
- 再現条件: 同一 `application_id` に対し `PATCH .../approve` を同時に 2 回。
- 修正案（最小差分）: `_get_application_or_404`（`admin.py:167-172`）を `session.get(..., with_for_update=True)` にする（1 行）。ロックを取れば既存の `status != "received"` 判定がそのまま直列化される。

---

## 確認したが問題なし

- **入札・落札・出品取り下げの同時実行**: `bids.create_bid`（`bids.py:118`）・`bids.select_bid`（`:224`）・`cases.cancel_case`（`cases.py:357`）が `lock_case_row`（`case_lock.py:28`＝`SELECT ... FOR UPDATE`）で同一の Case 行に直列化され、さらに `uq_bids_case_operator`（`0004:124`）・`uq_transactions_case_id`（`0004:153`）・条件付き UPDATE（`bids.py:250-259`）・`IntegrityError`→409 変換（`bids.py:158-170`・`:285-295`）の四重で守られている。PostgreSQL の READ COMMITTED でも二重選定・成約後入札・取り下げ後入札は成立しない。
- **口コミ集計の lost update**: `review_stats.recalc_operator_review_stats`（`review_stats.py:28`）が `operators` 行を `with_for_update` で掴んでから集計しており、同時投稿でも平均値がずれない。`uq_reviews_transaction_reviewer` 違反も 409 に変換済み（`reviews.py:90-98`）。
- **日時の扱い**: 全モデルが `DateTime(timezone=True)`（`db/base.py:36-46` の `TimestampMixin`、`transaction.py:47-48`、`user.py:76-95` 等）、書き込みは一貫して `datetime.now(timezone.utc)`（`transactions.py:419`・`admin.py:1056` 他）。訪問予定日は `Date` 型＋表示用ラベル文字列（`transactions.py:490-500`）で、naive/aware の混在も JST 二重変換も無い。
- **画像アップロード**: Content-Length 早期拒否＋ストリーミング上限 10MB（`case_photos.py:73-88`）、マジックバイト判定（`storage.py:152-164`）、`storage_key` の `fullmatch` 検証（`storage.py:49-53`）、上書き禁止（`storage.py:73-76`）。認証も PUT 側に掛かっている。※保存先の永続性のみ H-2。
- **BackgroundTasks の失敗耐性**: `notify_dispatch._best_effort`（`notify_dispatch.py:48-67`）が全例外を捕捉し、`notify._send` / `line_notify._push` も内部で握るため、通知失敗で本流（成約・入札）が壊れることはない。※逆方向（無音化）が H-3。
- **DB 接続の再利用**: `pool_pre_ping=True` / `pool_recycle=300` / `command_timeout=30`（`db/session.py:22-31`）。スピンダウン・DB 再起動後の stale connection で初回リクエストが落ちる典型は塞がれている。
- **マイグレーション 0025 / 0026 の本番適用**: `0025` は `users` への 3 列追加（`is_suspended` は `server_default="false"` 付き＝PG11+ で全行書き換えなし）＋索引 1 本、`0026` は `operator_applications` への nullable 列 1 本＋索引 1 本（`0026:29-39`）。いずれも `ACCESS EXCLUSIVE` は一瞬で、既存行の既定値も定義済み。現在の行数規模ならロック待ちは問題にならない。
- **レート制限の実値**: 出品は IP・アカウント各 10 回/時（`config.py:143-145`）＝1 世帯が 1 日数件出品する正規利用は阻害しない。入札にはレート制限が掛かっていないため、業者が 1 日に数十件入札しても 429 にならない。`TRUSTED_PROXY_HOPS` は `start.sh:29` が実測値 3 を既定注入しており（`render.yaml` の envVars が既存サービスへ同期されない問題を回避）、コード既定値 1 のまま本番に出る経路は無い。
- **管理画面の一覧クエリ**: `admin_list_cases` / `admin_list_transactions` / `admin_list_users` はいずれも `limit/offset` 付きで、関連ユーザーは `IN` 句の一括取得（`admin.py:506-513`・`:606-613`・`:695-701`）＝N+1 なし。公開業者一覧も `select(Operator, OperatorProfile)` の 1 クエリ（`operator_profile.py:243-269`）。

---

## 未解決 / ユーザー判断が要るもの

1. **H-2 の恒久対応方針** — β期間中は「写真は消えるもの」と割り切って検知だけ入れるか、R2/S3 へ移すか。移す場合の費用（R2 は 10GB まで無料）と作業量の判断はユーザー案件。
2. **H-1 の許容待ち時間** — AI 解析の全体デッドラインを何秒に置くか（45 秒案は暫定）。短くすると AI 要約の品質が落ち、長いとタイムアウト由来の重複案件が残る。
3. **Cloudflare／Render の実測タイムアウト値** — H-1 は「CF の応答待ち上限 100 秒」を前提にしている。[推測] 本番の実値は未計測。長時間かかる案件作成を 1 回実行して 524 が出るかを確認すると確定できる。
4. **M-2 の一意制約を張る前の既存重複** — 本番 `cancellations` に既に重複行があると migration が失敗する。適用前に `SELECT transaction_id, count(*) FROM cancellations GROUP BY 1 HAVING count(*)>1` の確認が必要。
5. **`fee_amount` が常に 0**（`bids.py:270`）は `docs/TODO.md` 03 に既出のため本監査では起票していない。
