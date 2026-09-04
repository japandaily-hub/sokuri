# r6-backend 独立検証（立案者と無関係な再判定）— 2026-09-04

対象台帳: `.agent-state/audit/r6-backend.md`（High 4・Medium 7）。全項目を file:line で自分で読み直して判定した。編集は本ファイルの Write のみ。

集計: **CONFIRMED 10 / PARTIAL 1 / REJECTED 0**。重大度修正 1 件（M-6 → Low）。追加 High 1 件・追加 Medium 1 件。

---

## High

### H-1 案件作成がリクエスト内で AI 解析を直列実行 → 二重案件 … **CONFIRMED**（High 妥当）

- 検証: `cases.py:205-211` で `generate_case_ai` を await し、`cases.py:236-238` で **その後に** `session.commit()`。クライアント切断でも ASGI ハンドラは走り続けるため「ブラウザはエラー・サーバは案件作成」が成立する。`rl_case_create_account_max = 10`（`config.py:144`）は成否を問わずカウント（`cases.py:128` の `hit_account`）＝再送信で本人が 429 に落ちるのも事実。
- **台帳の見積りは過小**（実測値の訂正）:
  - グローバル同時実行は **3 ではなく 4**（`config.py:45` `gemini_max_concurrent_calls: int = 4`、`vision.py:175`）。
  - items 側は「8 コール ÷ 3 = 3 波 = 75 秒」ではない。1 商品タスク内が **逐次 2 枚**（`summary.py:252-254`、各枚 25 秒）で、これを `Semaphore(3)`（`summary.py:327`）で並列化するため、**4 商品 × 2 枚 = 8 コール構成では 2 波 × 50 秒 = 100 秒**が最悪。
  - 未分類写真は `generate_case_ai` 内で **items の解析完了後に逐次**実行される（`summary.py:395` → `:406-410` → `_detect_photo_labels` の for ループ `summary.py:95-98`）＝ 4 枚 × 25 秒 = 100 秒。
  - 合計最悪値は **約 200 秒**（台帳の 175 秒より悪い）。方向性は正しく、結論は変わらない。
- 修正案への注意:
  1. `asyncio.timeout(45)` は成立する。ネストした `asyncio.timeout(25)`（`summary.py:97`・`:254`）とも 3.11+ で正しく連鎖し、`summary.py:112` / `:339-341` の `except Exception` は `CancelledError`（BaseException）を飲まないので外側へ伝播する。`cases.py:232` の `except Exception` は `TimeoutError` を捕捉するため、フォールバック文言へ落ちる想定どおりに動く。
  2. **ただしこれは緩和であって解決ではない。** 45 秒でも「サーバは commit 済み・利用者は失敗と認識」という重複の窓は残る。恒久策は冪等キー（クライアント発行の request key + UNIQUE）か、AI 解析の `BackgroundTasks` 化のいずれか。45 秒案を入れるなら「窓が 200 秒→45 秒に縮むだけ」と台帳に明記すべき。
  3. `summary.py:95-100` の `asyncio.gather` 化は妥当（グローバル `Semaphore(4)` が輻輳を抑える）。ただし `_detect_photo_labels` は現在 `detected` へ **appendの順序＝写真順**を保証しており、`gather` で結果順序は保たれるが `continue` によるスキップ表現を `None` フィルタへ書き換える必要がある（1 行では済まない）。

### H-2 写真が Render 一時ディスクに保存され再起動で消える … **PARTIAL**（事実 CONFIRMED / 新規発見ではない）

- 事実は確定した:
  - `render.yaml:59-60` に `STORAGE_DIR=/tmp/uploads`。**`render.yaml` は全 100 行で `disk:` / `mountPath` の指定は一切無い**（Render の persistent disk 未使用を確定）。
  - `backend/` 全体に S3/R2/boto3/minio の設定経路も依存も **存在しない**（`grep -rniE "boto3|s3_|R2_|minio|mountPath|disk:"` でヒット 0。Cloudflare のヒットは全て `client_ip.py` の IP レンジ判定）。
  - 実体は `storage.py:56-59` の `Path(settings.storage_dir)` へのローカル書き込み、配信は `case_photos.py:112-117` の `FileResponse`。`render.yaml` の envVars が既存サービスへ同期されない件（`start.sh:13-19`）を考慮しても、コード既定値 `./uploads_storage`（`config.py:63`）はコンテナ内＝同じくエフェメラルなので、**どちらの経路でも結論は同じ**。
- **PARTIAL の理由**: これは「静かに壊れる欠陥の発見」ではなく、**既に文書化された意図的なβ許容**。`render.yaml:60`（「Free plan はエフェメラル（β許容）」）、`config.py:62-63`（「Render Free はエフェメラル。βでは許容」）、`storage.py:1-7`（「クローズドβはゼロコスト方針のため外部オブジェクトストレージを使わず…R2/S3 へ移行する場合は presign_upload() の返却 URL を差し替えるだけでよい」）、`docs/TODO.md`「04 運用上の注意」の 15 分スピンダウン記載。台帳の指摘のうち **新規性があるのは「消失を検知する経路が皆無」の一点のみ**（`case_photos.py:114-117` は素の 404）。
- 重大度: 利用者影響（入札根拠の消失）としては High のままで良いが、**「未知の欠陥 High」ではなく「既知の受容リスク＋可観測性の欠落」**として起票し直すべき。修正案（404 時の warning + alert）は妥当で副作用も小さい。
- 未確認: 「15 分スピンダウンでファイルが消える」の実測は行っていない（Render の仕様上そうなるが、本監査では外形実験をしていない）。台帳の再現条件をそのまま 1 回実行すれば確定する。

### H-3 通知の実行時失敗が無音 … **CONFIRMED**（High 妥当）

- 検証: `notify.py:67-82` はキー未設定時のみ `alerts.fire_and_forget`（しかも `_brevo_missing_key_alerted` によるプロセス内 1 回限り）。実際の送信失敗は `notify.py:98-100` で `logger.error` のみ・`False` を返すだけ。`line_notify.py:71-73` も同一構造。`notify_dispatch._best_effort` が例外を握る点も台帳どおり。429（Brevo 無料枠 300 通/日）・401/402 がここに全部落ちる。
- 修正案への注意（台帳が触れていない致命点）: **アラートの送出経路自体が Brevo を使う**（`alerts.py` のメール送信）。Brevo が落ちている／枠切れの状況では「送信失敗アラート」も同じ理由で送れない。したがって送信失敗アラートは **LINE（`alert_line_channel_access_token`）か webhook（`alert_webhook_url`）を必須経路**にすること。加えて、通知は `BackgroundTasks` から N 件同時に走るため、`key="notify_brevo_send_failed"` の固定キー＋`alert_cooldown_seconds=600`（`config.py:87`）で必ず束ねること（キーを宛先別にすると障害時にアラートが N 通出る）。

### H-4 本番必須設定が起動ガードにも /readyz にも現れない … **CONFIRMED**（High 妥当）

- 検証: `main.py:77-108` の production ブロックは **JWT_SECRET（起動中断）/ DATABASE_URL localhost（ログのみ・起動継続）/ ALLOWED_ORIGINS のワイルドカード（起動中断）** の 3 つだけ。`app_encryption_key` は一切参照されない。`/readyz`（`main.py:152-207`）は `SELECT 1` と alembic リビジョン＋テーブル存在のみで、設定の欠落は表現されない。
- 影響の実在も確認: `config.py:72` 既定値 `""` → `crypto.py:34-40` が `EncryptionKeyMissingError`（RuntimeError 派生）を送出 → `operator_applications.py:95` の `encrypt_json` はハンドラ内で呼ばれるため **FastAPI が 500 に変換**（プロセスは落ちない）。`render.yaml:76-80` が `sync: false` であることも確認（ダッシュボード手動入力＝落としやすいという前提は正しい）。鍵入れ替え時の静かな劣化も `admin.py:135-140` の `except Exception` → `bank_account_masked=None` で確定。
- 修正案への注意: **起動中断（`RuntimeError`）にすると失敗モードが「業者申込だけ 500」から「API 全断」へ拡大する。** 本監査の主題が「外形監視は緑なのに壊れている」である以上、`/readyz` の `"config"` ブロック追加（台帳後半の案）が主で、起動中断は副にすべき。少なくとも `Fernet(key)` の構築失敗（形式不正）と未設定は区別し、CRITICAL ログ＋`/readyz` の degraded 表示で足りる。`/readyz` に config を足す場合は **値ではなく bool のみ**を返すこと（`main.py:153` の `token` ガードは診断ログにしか掛かっていないため、payload は無認証で読める）。

---

## Medium

### M-1 Transaction 側の状態遷移がロック規約に不参加 … **CONFIRMED**

- 検証: `_get_txn`（`transactions.py:113-121`）は `with_for_update` 無しの素の SELECT。`complete`（`:225-246`）・`cancel`（`:254-299`）・`confirm_schedule`（`:471-493`）のいずれも条件付き UPDATE も無く、read→check→write が非原子。`bids.py` / `cases.py:357` が `lock_case_row` を使っているのと非対称なのも事実。
- 修正案への注意（台帳の記載に不足）:
  1. `cancel` は Transaction 以外に **`txn.case.status`（`transactions.py:269`）と `operator.cancel_count`（`:279`）** も書く。Transaction 行だけロックしても `cancel_count` の read-modify-write は保護されない（別トランザクションの成約でも同じ行を触る）。`cancel_count` は `UPDATE operators SET cancel_count = cancel_count + 1` の原子更新にするか、同じロック配下に入れること。
  2. **ロック順序**の統一が必須。既存経路は Case → （Transaction）の順（`cases.py:357`・`bids.py:224`）。新ヘルパが Transaction → Case の順で掴むとデッドロックを新規に作る。`services/txn_lock.py` を作るなら「Case を先に掴んでから Transaction」に固定すること。この 1 点を明記せずに実装させると事故る。

### M-2 キャンセル二重送信で `cancellations` 2 行・`cancel_count` 2 加算 … **CONFIRMED**

- 検証: `0004_katadzuke_schema.py:240-251` に `transaction_id` の UNIQUE は無く、`ix_cancellations_transaction_id`（:251）のみ。`transactions.py:270-279` の add と `+= 1` に排他なし。
- 注意: FK は `ondelete="SET NULL"`（`0004:242`）＝当該列は NULL 可。PostgreSQL の UNIQUE は NULL を重複扱いしないので制約自体は成立するが、**運営による代理キャンセル（`ck_cancellations_cancelled_by` は 'admin' を許容・`0004:245-248`）で 2 行目を正当に入れたい運用が将来出ると詰む**。台帳 #4（既存重複行の事前確認）は妥当。

### M-3 減額回答が成約ステータスを検査しない … **CONFIRMED**

- 検証: `reductions.py:134-152` に `txn.status` の判定は皆無（`create_reduction` は `:70` で `("pending","visiting")` に限定）。`complete_transaction:241-243` が `final_amount` を確定した後でも `reductions.py:152` が上書きできる。キャンセル済みでも同じ。修正案（`:144` 直前に 409）は最小差分で成立し、副作用も無い。

### M-4 「未回答は1件だけ」がアプリ層のみ … **CONFIRMED**

- 検証: `reductions.py:75` の `any(...)` はメモリ上判定のみ。`0004:195-197` は `ix_reduction_requests_transaction_id`（非一意）だけで部分一意索引は無い。pending が 2 行残ると `:75` により業者が恒久的に 409 で締め出される、という帰結も正しい。
- 注意: 部分一意索引は PostgreSQL 専用のため **SQLite の既存テスト群では一切検証できない**。`IntegrityError` → 409 変換を併設する台帳案は必須（片方だけ入れると本番でのみ 500）。

### M-5 業者の案件一覧が LIMIT なし＋重量 eager load … **CONFIRMED**（Medium 妥当）

- 検証: `cases.py:286-293` に `limit`/`offset` 無し。`_CASE_LOAD`（`cases.py:83-88`）が `photos` / `items→photos` / `bids→operator` / `bids→transaction` を一括ロード。管理画面のみ r4 でページング済み、という非対称も事実。
- 注意: **API 契約の変更**になるため `web/src/lib/katadzuke-api.ts` と業者の一覧画面を同一変更に含めること。backend だけ `limit=50` を入れると、業者には「51 件目以降が存在しないように見える」静かな劣化が新規に生まれる（本監査の主題そのもの）。

### M-6 `transactions.bid_id` に索引なし … **CONFIRMED（事実）／重大度 Medium → Low へ修正**

- 検証: `0004:148-152` が FK のみ、`:161-162` の索引は `case_id` と `status` だけ。`transactions.py:58-75` が `join Bid` 経由なのも事実。
- 重大度を下げる根拠: `uq_transactions_case_id`（`0004:153`）により **transactions の行数は案件数を超えない**。クローズドβの規模では PG はどのみち seq scan を選ぶ（索引を張っても使われない）。台帳自身が「現時点では未顕在」と書いており、`bids` 行は削除されない運用のため RESTRICT の全走査も発生しない。**将来の予防措置＝Low** が妥当。0027 に同梱するのは安価なので反対はしない。

### M-7 業者申込の承認に行ロックが無く招待コードが 2 件発行 … **CONFIRMED**

- 検証: `admin.py:1031-1036`（status 判定）と `:1051-1062`（invite 生成・status 更新・commit）の間に排他なし。`_get_application_or_404`（`admin.py:167-171`）は素の `session.get`。`_issue_unique_invite_code`（`:115-120`）は SELECT→生成のみで、**別トランザクションの未コミット行は見えない**ため衝突検査としても不完全（ただし `secrets.token_hex(4)` の衝突自体は実務上無視できる）。`application.invite_code = code`（`:1060`）が後勝ちで 1 件しか残らない帰結も正しい。
- 注意: `_get_application_or_404` は **approve 以外のハンドラからも呼ばれる共有ヘルパ**。無条件に `with_for_update=True` にすると参照系にも行ロックが付く。呼び出し元を全て洗い、承認/却下など状態遷移する経路だけに限定する（別関数に分けるのが安全）。台帳の「1 行」という見積りは楽観。

---

## 追加発見（同観点で見落とされていたもの）

### ADD-1【High】AI 解析の 100〜200 秒間、DB コネクションを開いたトランザクションごと占有し続ける → 少数の同時出品で API 全体が詰まる

- 箇所: `cases.py:119-120`（`get_current_user` と `get_session` が同一リクエストスコープの同一 `AsyncSession` を共有）、`cases.py:205-211`（AI await）、`cases.py:236-238`（commit）、`db/session.py:25-31`（`create_async_engine` に **`pool_size` / `max_overflow` の指定が無い**＝SQLAlchemy 既定の 5 + 10 = 最大 15）、`db/session.py:47-48`（コネクション返却はリクエスト終了時）。
- 事象: 認証依存性（`get_current_user`）が User を SELECT した時点でコネクションがチェックアウトされトランザクションが開始する。以後 `commit()` までの **最大約 200 秒**（ADD 上の H-1 実測値）、その 1 本は返却されない。同時に案件作成が 15 本走ると **プール枯渇**し、ログイン・案件一覧・入札を含む **無関係な全 API** が `QueuePool limit ... connection timed out`（既定 30 秒待ち）で 500 になる。1 プロセス・1 uvicorn（`start.sh:68`）のため逃げ場が無い。PostgreSQL 側にも `idle in transaction` が 200 秒居座る。
- H-1 との差: H-1 は「その利用者に二重案件ができる」。ADD-1 は「**その 1 リクエストがサービス全体を巻き込む**」で、影響範囲もアラート経路も別（`/health` は DB を触らないので緑のまま、`/readyz` は 5 秒の `SELECT 1` がプール待ちで落ちて 503 になる＝原因が誤読される）。
- 実在条件: 同時案件作成 15 件（`rl_case_create_ip_max=10/時` は IP 軸なので複数利用者なら容易に超える）。クローズドβの現トラフィックでは未顕在だが、告知直後や業者説明会など「同時に触る」局面で一発で出る。
- 最小差分の方向: ①H-1 のデッドライン（45 秒）で占有時間を 1/4 にする、②`db/session.py:25` に `pool_size=5, max_overflow=15, pool_timeout=10` を明示（既定値依存をやめる）、③恒久的には AI 解析前に `await session.commit()` して案件行を先に確定し、解析結果は別トランザクションで UPDATE（H-1 の二重案件も同時に解消する）。③は差分が大きいのでユーザー判断。

### ADD-2【Medium】`GET /transactions` も LIMIT なし（M-5 と同一欠陥だが台帳は案件一覧しか挙げていない）

- 箇所: `transactions.py:58-77`。`limit`/`offset` 無しで `case` / `bid→operator` / `reduction_requests` / `reviews` を eager load し、成約が積み上がるほど依頼者・業者双方の一覧が線形に重くなる。M-5 を直す際に同じ関数群を触るので、同時に対処するのが最小コスト。

---

## 未解決 / ユーザー判断（台帳の 5 項目に対する所見）

1. H-2 の恒久対応方針 — 妥当な論点。ただし上記のとおり「既知の受容リスク」なので、判断を仰ぐ形（検知だけ入れる／R2 へ移す）で正しい。
2. H-1 の許容待ち時間 — 45 秒案は妥当だが、**冪等キーが無い限り重複の窓は消えない**ことを併記した上で問うべき。
3. Cloudflare の実測タイムアウト — 台帳自身が [推測] と明記しており適切。ADD-1 の存在により、CF の実値がいくつであっても H-1 の修正価値は下がらない。
4. `cancellations` の既存重複確認 — 必須。同意。
5. `fee_amount` の TODO 03 重複除外 — 正しい判断。**台帳 11 項目のうち TODO 03 と重複するものは無く、REJECTED はゼロ**。H-2 のみ TODO「04 運用上の注意」＋コード内コメントと重複するため PARTIAL とした。
