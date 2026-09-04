# r6 レビュー（QA / セキュリティ・実コード検証）— 2026-09-04

## 総合判定: 条件付き合格（Critical 0 / High 3）。High 3件を修正するまで「問題なく使える」とは言えない。

## 実行検証（実測）

| 項目 | 実測 |
|---|---|
| backend pytest -q | **784 passed, 0 failed**（785 warnings / 432.30s）。backend2 の自己申告 774 は着手時点のスナップショットで、統合後の実数は 784（753 + 新規31: test_case_ai_background 10 + test_txn_state_integrity 11 + test_admin_notifications_r6 10）。 |
| web npx tsc --noEmit | **エラー 0** |
| web npx eslint src | **エラー 0 / warning 3**（notifications/page.tsx:195・operator/transactions/[id]/page.tsx:87 の未使用 eslint-disable、signup/page.tsx:59 の未使用 router。いずれも本差分と無関係な既存分） |
| alembic heads | **単一**: 0028_txn_state_integrity。総リビジョン 29。0026 → 0027_case_ai_status → 0028_txn_state_integrity の直列。リビジョンIDは 20/23 文字で 32 文字制限内。 |
| next build | 指示どおり未実行 |

自己申告のうち実コードで**確認できた**もの:

- 背景セッションが get_background_session_factory() 経由の新 AsyncSession（cases.py:141）で、認証依存性のリクエストスコープ session を再利用していない
- 通知 add_task が AI 解析 add_task より先（cases.py:400-408）＝通知は解析を待たない
- _lock_txn_rows が Case→Transaction 順（transactions.py:169-189、case_lock.py:24 と同順）
- cancel_count が UPDATE ... cancel_count + 1 の原子加算（transactions.py:363-369）
- /readyz の config が bool のみで秘密値を含まない（main.py:68-104）
- alerts._inflight_tasks の強参照保持（alerts.py:44,183-185）
- 退会時の暗黙キャンセルが Bid却下・Cancellation・bid_lost 通知の3点で cancel_case と一致（users.py:508-580 vs cases.py:595-605。cancelled_by="user"・transaction_id=None まで一致）
- select_bid の停止/非active業者 409（bids.py:254-271）と list_bids の operator_suspended 旗（bids.py:67。Bid.operator は bids.py:39 で eager load 済み＝MissingGreenlet なし）
- pending 減額があると完了できない件は web に解消導線あり（cases/[id]/page.tsx:765-800 の承認/却下ボタン、完了ボタンは disabled={busy || Boolean(pendingReduction)} で整合）
- 0028 の RuntimeError は alembic env.py:62 の transaction_per_migration=True により 0028 のみをロールバックする（0027 は適用済みで残る）

---

## High（3件）

### H1. web が limit/offset を送らず、101件目以降が恒久的に不可視になる回帰

- 該当: `web/src/lib/katadzuke-api.ts:1427-1429`（listOpenCases → request("/cases")）、`web/src/lib/katadzuke-api.ts:1509-1511`（listTransactions → request("/transactions")）。backend 側は `backend/app/api/v1/endpoints/cases.py:419-427`（既定100・上限200）と `backend/app/api/v1/endpoints/transactions.py:58-59`（既定100・上限200）。
- 問題: backend が既定 LIMIT 100 を新設したのに、web の呼び出し全箇所がクエリを付けていない（operator/cases/page.tsx、operator/page.tsx:310、mypage/page.tsx:179、notifications/page.tsx:127、schedule/page.tsx:98、chat/[id]/page.tsx:128、operator/chat/[id]/page.tsx:122、operator/transactions/page.tsx:40、mypage/withdraw/page.tsx:103、components/kdz/AppHeaderBell.tsx）。r6-fix-backend1 自身が「web 側の追随が必須」と書いた契約が未履行。
- 再現条件: 公開中案件が101件を超えると、業者は created_at desc 上位100件しか見えず、101件目以降には**入札が一切付かない**。依頼者からは「誰も入札しない案件」に見え、原因は画面のどこにも出ない（本監査の主題「静かに壊れる」の再生産）。成約が101件を超えたユーザー/業者では未読バッジ・評価待ち・進行中件数が過小になる。
- 修正案: listOpenCases(token, {limit, offset}) / listTransactions(token, {limit, offset}) にオプション引数を足し、一覧画面に「さらに読み込む」を実装する。暫定でよければ全呼び出しに ?limit=200 を付け、res.length === 200 のときだけ追加取得する。

### H2. ai_status="pending" が恒久的に残留する経路があり、web は永久に「解析中」を表示し続ける

- 該当: `backend/app/api/v1/endpoints/cases.py:114-206`（_run_case_ai_analysis）、`backend/app/api/v1/endpoints/cases.py:406-408`（background.add_task）、`web/src/app/cases/[id]/page.tsx:270-290`（ポーリング）・`web/src/app/cases/[id]/page.tsx:548-553`（pending 表示）。
- 問題: Starlette の BackgroundTasks はプロセス内タスクで永続キューではない。Render のデプロイ・スリープ復帰・OOM・SIGTERM でレスポンス直後のタスクが失われると ai_status は pending のまま残り、**誰も failed に落とさない**（回収バッチ・起動時スイープ・GET 側の時間経過判定のいずれも未実装）。web は 180 秒で clearInterval するだけで表示は「AI が写真を解析中です…この画面は自動で更新されます」のまま固定され、手動更新導線もない。
- 再現条件: 案件作成の応答直後（〜120秒以内）に backend を再デプロイ／再起動する。案件詳細は以後ずっと解析中表示のまま。
- 修正案: (a) GET /cases/{id} で ai_status=="pending" かつ now - created_at > 5分 を failed 相当として返す（DB も遅延更新）、または (b) lifespan 起動時に `UPDATE cases SET ai_status='failed', ai_failed_reason='interrupted' WHERE ai_status='pending' AND created_at < now() - interval '10 minutes'` のスイープを入れる。併せて web の 180 秒到達時に「更新する」ボタンを出す。

### H3. 0028 は本番データ次第で確定的に失敗し、失敗しても起動は継続するため「制約が在るつもり」で走る

- 該当: `backend/alembic/versions/0028_txn_state_integrity.py:56-72`（_assert_no_duplicates → RuntimeError）、`backend/start.sh:52-63`（alembic 失敗 3 回で警告のみ・uvicorn は起動）、`backend/alembic/env.py:62`（transaction_per_migration=True）。
- 問題: cancellations.transaction_id または reduction_requests(status='pending') に重複が1組でもあると 0028 だけがロールバックし、0027 は適用済みのまま degraded 起動する。この状態では uq_cancellations_transaction_id と uq_reduction_requests_pending が存在しないのに、`transactions.py:390-398` と `reductions.py:98-110` は「IntegrityError が飛ぶ前提」で 409 変換を書いている＝**二重キャンセル・二重 pending 減額の DB 層の防御が丸ごと無い状態で本番が動く**。/readyz の expected_head 不一致で検知はできるが、監視で気づかない限り無言で劣化する。
- 再現条件: 本番 cancellations に同一 transaction_id の行が2件以上ある状態でデプロイする（r6-fix-backend2 自身が「本番適用前の確認（必須）」に挙げているが未実行）。
- 修正案: デプロイ前に `SELECT transaction_id, count(*) FROM cancellations WHERE transaction_id IS NOT NULL GROUP BY 1 HAVING count(*)>1;` と `SELECT transaction_id, count(*) FROM reduction_requests WHERE status='pending' GROUP BY 1 HAVING count(*)>1;` の2本を実行し 0 行を確認する。恒久策は 0027（安全）と 0028（データ依存）のデプロイ分割＋適用後に /readyz の migration.current が 0028_txn_state_integrity であることをログで実証（「デプロイした」はログで確認するまで未検証扱いという規約どおり）。

---

## Medium（7件）

- **M1** `backend/app/api/v1/endpoints/transactions.py:299,341,578` — _lock_txn_rows() を _assert_party() **より前**に呼んでおり、認可判定前に Case 行の FOR UPDATE を取る。`backend/app/api/v1/endpoints/cases.py:625-640` が security review 2周目の指摘で明示的に避けた「認可前ロック取得によるロック争奪」を、同型の3遷移（complete / cancel / confirm_schedule）に再導入している。再現: 有効な transaction_id を知る当事者外アクターが complete を連打すると、403 を返す前に当該案件の正規処理（落札・取り下げ）を待たせられる。修正案: _get_txn → _assert_party → _lock_txn_rows → 再読込（expire_all + _get_txn）の順にする（cancel_case と同じ「事前照会 → 認可 → ロック → 再検証」パターン）。
- **M2** `backend/app/api/v1/endpoints/cases.py:89-112` + `backend/app/db/models/case.py:91-94` — idempotency_key に DB 一意制約が無く、窓判定も Python 側のため、**同時2リクエストは両方とも None を得て2件作成する**。web の submitting state（`web/src/app/create/page.tsx:118`）は同一タブの二度押ししか防げず、別タブ・モバイルブラウザの再送では防げない。修正案: `Index("uq_cases_idempotency_key", "user_id", "idempotency_key", unique=True, postgresql_where=text("idempotency_key IS NOT NULL"))` を追加し、IntegrityError を捕捉して既存案件を 200 で返す（reductions.py と同じ多層防御）。
- **M3** `backend/app/main.py:265-275` — /readyz は無認証で config / degraded_config を返す。値は載せていないが「encryption_key が不正」「admin_emails 未設定」といった攻撃の下準備に有用な情報を外部へ開示する。修正案: config は DIAG_TOKEN 一致時のみ payload に含め、無認証時は degraded_config の**件数**だけ返す。
- **M4** `backend/app/api/v1/endpoints/admin.py:360-372,396-404,798-806` — 状態が実際に変化したかを見ずに通知する。verified=true の業者へ再度 verified=true を送る／既に解除済みのアカウントへ再度 suspended=false を送ると、そのつど「入札できるようになりました」「制限を解除しました」が届く。修正案: 更新前の値を退避して previous != new のときだけ add_task する。
- **M5** `backend/app/api/v1/endpoints/reductions.py:104-106` — コメント「部分一意索引は PostgreSQL 専用で SQLite のテストでは発火しない」は**誤り**。モデル（`backend/app/db/models/transaction.py:99-105`）と migration（`0028_txn_state_integrity.py:87-94`）に sqlite_where を併記しており SQLite 3.8+ でも効く（`backend/tests/test_txn_state_integrity.py:381` が実際に SQLite で通っている）。誤ったコメントは将来「SQLite では守られない」という前提での退行改修を招く。修正案: コメントを実装に合わせて訂正する。
- **M6** `backend/app/services/alerts.py:33-40,150-158` — 抑制はプロセス内 dict + asyncio.Lock。同一プロセス内の並列は直列化されるが、**プロセス再起動で last_sent_at が消えクールダウンがリセットされる**。5xx で再起動を繰り返す障害では 10 分抑制が実質無効化され、運営 LINE（@854kzrrb）が溢れる。docstring に既知として記載済みだが、通知失敗アラート（`backend/app/services/notify.py:105-117` / `backend/app/services/line_notify.py:78-89`）を新設した本差分で発火経路が増えた分だけ実害が増した。修正案: 抑制状態を DB か /tmp の JSON に永続化する。最低限 ALERT_COOLDOWN_SECONDS を 600 → 1800 へ。
- **M7** `web/src/app/create/page.tsx:395-435` — 送信失敗後の再試行は写真アップロード（uploadCasePhoto）からやり直すが、idempotency_key が一致すると backend は**最初の案件**を返す。結果、2回目にアップロードした storage オブジェクトはどの案件からも参照されない孤児として残る（H-2「写真が Render 一時ディスクで消える」未対応と重なる）。修正案: アップロード済み storage_key を useRef にキャッシュして再試行時に再利用する。

## Low（5件）

- **L1** `web/src/app/admin/_components/ConfirmModal.tsx:70-73` — Esc ハンドラが busy を見ずに onCancel() を呼ぶ。キャンセルボタンは disabled={busy}（同ファイル:130）なので、処理実行中に Esc だけがモーダルを閉じられる非対称が生まれた。修正案: `if (e.key === "Escape" && !busy)`。
- **L2** `web/src/app/admin/_components/ConfirmModal.tsx:86-88` — keydown の useEffect が依存配列 [] + eslint-disable で onCancel を初回束縛する。親が onCancel を再生成する実装に変わると stale closure になる。修正案: onCancel を useRef に保持して参照する。
- **L3** `web/src/app/cases/[id]/page.tsx:743-762` と `web/src/app/cases/[id]/page.tsx:765-800` — pending の減額申請が「減額申請の履歴」と「業者から減額申請が届いています」の**両方**に表示される。修正案: 履歴側を r.status !== "pending" でフィルタする。
- **L4** `backend/app/api/v1/endpoints/cases.py:302-304` — 冪等ヒット時に response.status_code = 200 を返すがルート宣言は 201 のみで、OpenAPI に 200 が現れない。生成クライアントが 200 を異常扱いしうる。修正案: `responses={200: {"model": CaseOut, "description": "冪等キー一致（既存案件）"}}` を宣言に追加する。
- **L5** `web/src/components/kdz/AppHeaderBell.tsx` — 未読ベルが listTransactions に依存するため H1 の 100 件上限の影響を直接受ける（古い成約の未読を数え落とす）。H1 の修正で同時に解消する。

---

## 未解決リスク（要確認 / 実測待ち）

1. **[要確認] PostgreSQL での同時実行が一度も実証されていない。** FOR UPDATE（`backend/app/api/v1/endpoints/transactions.py:169-189`）・cancel_count の原子加算（同:363-369）・部分一意索引の競合挙動は、SQLite の逐次テストでは「壊れないこと」しか確認できていない。本番相当の PG に対して 2 並列（complete×cancel、同一業者の別成約 cancel×2、同一 idempotency_key×2）を実測するまで、これらの防御は「書いてあるだけ」の扱いとすべき。
2. **[要確認] DB_POOL_SIZE=5 / MAX_OVERFLOW=5 / POOL_TIMEOUT=10 の妥当性が未計測。** render.yaml に該当キーが無く（envVars は既存サービスに同期されない既知事象）、start.sh にも `${VAR:-既定}` の export が無いため、`backend/app/config.py:57-59` のコード既定値がそのまま本番の実効値になる。uvicorn は単一ワーカー起動（`backend/start.sh:63`）なので上限は 10 接続だが、Render 無料 PostgreSQL の実接続上限は未実測。/readyz が 503 を返し始めたら最初に見る値。
3. **[要確認] AI 解析 120 秒デッドラインと Gemini 同時実行セマフォの相互作用が未計測。** `backend/app/api/v1/endpoints/cases.py:73` の _AI_ANALYSIS_DEADLINE_SEC は1案件あたりの全体上限だが、GEMINI_MAX_CONCURRENT_CALLS によるセマフォ待ちも同じ 120 秒の中で消費される。同時投稿が集中すると解析自体は健全でも待ち時間だけで全件 failed に倒れうる。負荷時の ai_status='failed' 率を監視項目へ追加すべき。
4. **0028 の本番事前チェック SQL が未実行**（H3 の再掲。デプロイのブロッカー）。
5. **next build 未実行のため canonical / generateMetadata の実出力が未検証。** `web/src/app/vendors/[id]/layout.tsx:7-19` の generateMetadata 化と 14 ファイルへの alternates.canonical 追加は tsc/eslint では検証できない。metadataBase（`web/src/app/layout.tsx:28`）が設定済みなので相対 canonical は解決されるはずだが、末尾スラッシュの有無と絶対 URL 化は build 後の HTML で実測が必要。sitemap.ts に追加した 10 パスはいずれも実在ルートであることをディレクトリで確認済み（/photo-guide 含む）。
6. **通知の宛先・文面・リンク先は静的確認のみ。** /operator/cases・/operator・/mypage・/mypage/identity・/cases/{id} は全て実在ルートであることを確認したが、LINE 専用ユーザーへの実到達（Messaging API の Push 成功）は本番トークンでの実測が必要。`backend/app/services/notify_dispatch.py:85-146` の LINE 優先→メールのフォールバック順は全新規イベントで一貫している。

---

## サマリ

⚠️ 条件付き合格。pytest 784 passed / tsc 0 / eslint 0 errors / alembic heads 単一と、実行検証は全て緑。Critical 0。ただし High 3件（web のページング未追随による101件目以降の不可視化、ai_status=pending の恒久残留、0028 の本番データ依存失敗）は「静かに壊れる」型の欠陥で、本監査の目的そのものに直撃するため、修正前のマージ完了は不可とする。
