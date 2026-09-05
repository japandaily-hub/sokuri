# r10 運営オペレーション監査（2026-09-05）

対象: 運営者が朝に `/admin` を開いてから1日の業務を終えるまで。読み取り専用・編集なし。
除外: `docs/TODO.md` 03（意図的未対応）と 01（ユーザー判断・仮定）に載っている事項は再指摘しない
（入札ゼロ放置・訪問日超過のリマインド未実装／口座全桁開示の監査ログが標準出力のみ／停止業者の
既存進行中取引の扱い／全 admin 退会後の再ブートストラップ窓／`/admin/reviews/{id}/hide` の UI 未実装、等）。

## 回帰確認（r6-web-quality.md 通知マトリクスの H1〜H3）

| r6 の指摘 | 現状 | 根拠 |
|---|---|---|
| H1 アカウント停止/解除の通知経路が無い | **解消（解除のみ通知・停止時は無通知が設計判断）** | `backend/app/api/v1/endpoints/admin.py:428-437`（業者）, `:951-960`（依頼者） |
| H2 本人確認 承認/却下の通知経路が無い | **解消** | `admin.py:1516-1523`, `:1602-1609` |
| H3 業者 入札可否切替（verify）の通知経路が無い | **解消（状態変化時のみ）** | `admin.py:386-394` |
| 全 admin エンドポイントの認可 | **全 24 ルートが `get_current_admin`**（`admin.py` 24 ルート／24 依存。`operator_license.py:198` も同様） | `admin.py:200-1553`, `backend/app/api/deps.py:155-163` |
| 停止中 admin / 退会済み admin | **不可**。`get_current_admin` は `get_current_user` 経由で退会 401・停止 403。`promote` は `is_suspended` を 409 で拒否し停止中 admin を作れない | `deps.py:141-163`, `admin.py:1033-1037` |

---

## High

### H-1. 運営が成約を強制終了すると、依頼者宛メールの「詳細と理由を確認する」リンク先に理由が表示されない
- 重大度: High
- 業務・画面: 成約の強制終了 → 依頼者への結果通知
- 事象: `admin_cancel_transaction` は理由を必須で受け取り `Cancellation.reason` に保存するが、通知メールは
  本文に理由を載せず「画面で確認してもらう」方針で `/chat/{transaction_id}` へ誘導する。ところが依頼者側の
  `/chat/[id]` は `detail.cancellation` を一切描画せず「この取引は終了しています（キャンセル済み）」としか出さない。
  理由が出るのは `/cases/[id]`（別ページ）だけ。業者側 `/operator/transactions/[id]` は正しく理由を表示する。
- 根拠: `backend/app/api/v1/endpoints/admin.py:729-737`（理由必須）／`backend/app/services/notify.py:315-338`
  （`path = f"/chat/{transaction_id}"`・本文「詳細と理由を確認する」）／`web/src/app/chat/[id]/page.tsx:388-392`
  （終了案内のみ・`cancellation` の参照ゼロ）／対照 `web/src/app/operator/transactions/[id]/page.tsx:194-204`、
  `web/src/app/cases/[id]/page.tsx:817-826`
- 再現: 運営が `PATCH /admin/transactions/{id}/cancel`（理由入力）→ 依頼者にメール到達 → リンクを踏む →
  理由が無い → 運営へ「なぜ切られたのか」の問い合わせが発生する（運営の業務量が増える方向の欠陥）。
- 修正案: メールの依頼者向け `path` を `/cases/{case_id}` に変えるか、`/chat/[id]` に
  `operator/transactions/[id]/page.tsx:194-204` と同じ cancellation ブロックを追加する（後者が対称で望ましい）。

### H-2. `/readyz` の `degraded_config` を外形監視が判定に使っておらず、本番の設定欠落が誰にも通知されない
- 重大度: High
- 業務・画面: 日次の異常検知（アラート）
- 事象: `/readyz` は `brevo` / `line_push` / `gemini` / `encryption_key` / `admin_emails` / `frontend_base_url` の
  充足を payload で返すが、**未設定でも `status` は `ready` のまま**という設計。そして外形監視スクリプトは
  `status`・`db`・`alembic_version==expected_head` の3点しか見ず `degraded_config` を無視する。結果、
  BREVO_API_KEY 失効・LINE トークン失効・APP_ENCRYPTION_KEY 未設定は 100% 緑のまま無通知で進行する。
  これは 2026-09-04 に実際に起きた「本番の依頼者向けメールが BREVO_API_KEY 未設定で一度も送信されていなかった」
  事象（`.agent-state/PROJECT_STATE.md` 次アクション欄）と同一の失敗モードで、再発検知手段が今も無い。
- 根拠: `backend/app/main.py:308-316`（`status` は ready 固定）／`scripts/uptime_check.py:78-89`
  （`head_ok` と `status`/`db` のみ）／`docs/ops/alerting.md` 「検知条件 > 外形監視」に `degraded_config` の記載なし
- 再現: Render で `BREVO_API_KEY` を空にする → `/readyz` は 200・`status:"ready"`・`degraded_config:["brevo"]` →
  `uptime_check.py` は ok 判定 → 通知ゼロ。`TODO.md` 01-12 が「push 後に人が curl で確認」と書いているのは、
  この自動検知が無いことの裏返し。
- 修正案: `scripts/uptime_check.py:78-89` に `degraded_config` が空でないとき Warning（応答遅延と同じ遷移型通知）
  を追加し、`docs/ops/alerting.md` の検知条件表にも 1 行足す。

### H-3. アラート基盤の死活を誰も検証しておらず、通知経路が死んでいても「静か＝正常」と区別できない
- 重大度: High
- 業務・画面: 異常検知そのもの（運営が受け取る通知の宛先）
- 事象: `alerts.py` は 3 チャネルとも未設定なら `logger.info` でスキップ、送信失敗も `logger.error` のみで、
  呼び出し側へ失敗が伝わらない（`send_alert` の戻り値はどこでも判定されていない）。`_config_readiness` にも
  `alert_*` の項目が無いため `/readyz` にも出ない。一方で外形監視は「正常時は何も送らない」設計。
  したがって ALERT_LINE_CHANNEL_ACCESS_TOKEN 失効・運営が LINE 公式アカウントをブロック・ALERT_EMAILS 誤記の
  いずれが起きても、運営は「今日も平和だ」としか観測できない。GitHub PAT が 2026-10-04 に失効する予定
  （PROJECT_STATE）である点も、この盲点の上に乗っている。
- 根拠: `backend/app/services/alerts.py:74-77`（メール未設定スキップ）, `:104-118`（LINE 失敗は log のみ）,
  `:186`（`fire_and_forget` は例外を握るだけ）／`backend/app/main.py:140-146`（`_config_readiness` に alert 系なし）／
  `docs/ops/alerting.md`「**正常時は何も送らない**」
- 再現: Render の `ALERT_LINE_CHANNEL_ACCESS_TOKEN` を無効値にする → 5xx バーストを起こしても LINE は 401 で失敗 →
  ログ 1 行のみ・運営には何も届かない・`/readyz` も緑。
- 修正案: (a) `_config_readiness` に `alerts_channel`（メール or LINE or Webhook が1つ以上設定済み）を追加、
  (b) `uptime-alert.yml` に週1回の heartbeat（`force_notify` 相当の「監視は生きています」通知）を追加して
  デッドマンスイッチにする。

---

## Medium

### M-1. 本人確認書類の審査待ちが、ダッシュボードのバッジにも通知にも一切出ない（提出時の運営通知がゼロ）
- 業務・画面: `/admin` → `/admin/identity-documents`
- 事象: 事前申込には未審査件数の赤バッジがあるが、本人確認書類のリンクにはバッジが無い。API も
  `response_model=list[...]` で `total` を返さないためバッジを出しようがない。さらに
  `user_identity.py` の提出エンドポイントに運営通知（`notify`/`alerts`）が一切無い。運営がこのタブを
  能動的に開かない限り、提出した依頼者は「審査中」のまま無期限に待つ。
- 根拠: `web/src/app/admin/page.tsx:390-400`（事前申込のバッジ）対 `:410-412`（本人確認はバッジ無し）／
  `backend/app/api/v1/endpoints/admin.py:1358-1363`（`response_model=list[UserIdentityDocumentAdminOut]`）／
  `web/src/app/admin/identity-documents/page.tsx:280-286`（`total={null}`）／
  `backend/app/api/v1/endpoints/user_identity.py:167`（`submit_identity_document` に通知呼び出し無し）
- 再現: 依頼者が本人確認書類を提出 → 運営に何も届かない → `/admin` トップにも件数が出ない。
- 修正案: `list_identity_documents` を `{items,total}` に変更（`list_operator_applications` と同型）し、
  `/admin` のリンクに `status=pending&limit=1` の `total` をバッジ表示する。提出時の運営メールは任意。

### M-2. 本人確認書類一覧の並び順に tie-breaker が無く、ページングで行の重複・欠落が起きうる
- 業務・画面: `/admin/identity-documents`
- 事象: 他の全 admin 一覧（cases / transactions / users / operators / operator-applications）は QA M3 対応で
  `created_at desc, id desc` の決定的順序になっているが、本人確認書類だけ `submitted_at.desc()` 単独のまま。
  同一秒に提出された書類が複数あると、offset ページングで同じ行が二度出たり抜けたりする＝審査漏れ。
- 根拠: `backend/app/api/v1/endpoints/admin.py:1392`（`.order_by(UserIdentityDocument.submitted_at.desc())`）／
  対照 `:882-884`, `:1157-1161`
- 再現: 同一秒に 51 件以上の提出（バッチ登録・キャンペーン流入）→ 2ページ目で 1ページ目の行が再出現しうる。
- 修正案: `.order_by(UserIdentityDocument.submitted_at.desc(), UserIdentityDocument.id.desc())`。

### M-3. 本人確認書類一覧に検索（q）が無く、「この依頼者の本人確認はどうなっているか」に答えられない
- 業務・画面: `/admin/identity-documents`（問い合わせ対応）
- 事象: 絞り込みは `status`（pending/approved/rejected/all）のみ。依頼者 1,000 人規模では、特定の依頼者の
  書類に到達するには `all` を 50 件ずつ手繰るしかない。他の 4 一覧（cases / transactions / users / operators）は
  すべて `q` を持つ。
- 根拠: `backend/app/api/v1/endpoints/admin.py:1363-1372`（`q` パラメータ無し）／対照 `:536`, `:843-844`
- 再現: 依頼者から「本人確認はまだですか」と問い合わせ → メールアドレスで引けない。
- 修正案: `User.email` / `User.name` / `user_id` に対する `q` を追加（`admin_list_users` の実装をそのまま流用）。

### M-4. 業者の「pending」件数に許可証提出済み（＝今日承認できる）内訳が無く、実行可能な仕事量が分からない
- 業務・画面: `/admin`（業者承認）
- 事象: `verify_operator` は `has_license_image` が偽なら 409 で承認を拒否する（UI もボタンを無効化）。
  しかし一覧の絞り込み・カウントは `vendor_status` と `is_suspended` の 2 軸しか無く、「pending かつ許可証提出済み」
  を数えることも絞ることもできない。pending が 30 件表示されても、そのうち今日承認できるのが 2 件なのか
  30 件なのかは 1 件ずつ開かないと分からない。
- 根拠: `backend/app/api/v1/endpoints/admin.py:252-258`（status の Literal に許可証軸なし）, `:377-382`（409 の条件）／
  `web/src/app/admin/page.tsx:362-369`（counts のボタン列）
- 再現: 業者 100 社・pending 30 社の状態で `/admin` を開く → 「今日の承認作業は何件か」が判断できない。
- 修正案: `status` に `pending_with_license` を追加するか、`OperatorListCounts` に
  `pending_with_license` を 1 フィールド足して同じ集計クエリで返す（`case(...)` 1 個の追加で済む）。

### M-5. 依頼者一覧に「退会済みを含める」トグルも「停止中」絞り込みも無く、業者一覧と非対称
- 業務・画面: `/admin/users`
- 事象: backend の `admin_list_users` は `include_deleted` を実装済みだが、web の `adminListUsers` は
  `q/limit/offset` しか送らない（型定義で `Pick<AdminListParams, "q"|"limit"|"offset">` に限定）。業者一覧には
  r8 で `includeDeletedOperators` トグルが入っており、依頼者側だけ取り残されている。停止中ユーザーの
  絞り込みは backend にもフロントにも無い（業者は `status=suspended` がある）。
- 根拠: `web/src/lib/katadzuke-api.ts:2014-2019`／`backend/app/api/v1/endpoints/admin.py:848-852`（backend は対応済み）／
  対照 `web/src/app/admin/page.tsx:80-82`（業者側のトグル）, `admin.py:252-258`（業者の `suspended` 絞り込み）
- 再現: 「退会したはずの依頼者の記録を確認したい」「停止中の依頼者を棚卸ししたい」→ 画面からは不可能。
- 修正案: `adminListUsers` に `include_deleted` を通し、`/admin/users` にトグルを置く。停止中の絞り込みは
  `admin_list_users` に `suspended` フィルタを追加（`list_operators` と同型）。

### M-6. 停止解除依頼を受ける経路も一覧も無く、問い合わせは DB に残らない（対応漏れが構造的に検知できない）
- 業務・画面: 停止解除 / 問い合わせ対応
- 事象: 停止された当事者に返るのは「お問い合わせ窓口までご連絡ください。」という文言だけで、窓口は
  `/contact`＝**メール送信のみ・DB 保存なし**。したがって (a) 停止解除依頼の待ち行列は管理画面に存在せず、
  (b) 問い合わせは運営の受信箱にしか残らず未対応検知ができず、(c) `/admin/users` は停止中で絞り込めない（M-5）
  ため、解除対象を探すにはメールアドレスの手打ち検索しかない。
- 根拠: `backend/app/api/deps.py:79-83`（`SUSPENDED_ACCOUNT_DETAIL` の文言）／
  `backend/app/api/v1/endpoints/contact.py:194-207`（`admin_emails` へメール送信のみ・保存処理なし）／
  `backend/app/api/v1/endpoints/admin.py:923-996`（解除 API はあるが「依頼」の受け皿は無い）
- 再現: 誤停止された依頼者が `/contact` から連絡 → 運営の受信箱に 1 通届くだけ → 見落とすと恒久ロックアウト。
- 修正案: 最小実装として `/contact` を `contact_messages` テーブルへ保存し `/admin` に未対応件数バッジを出す。
  当面の運用回避としては M-5 の停止中フィルタだけでも入れる（対象者を機械的に列挙できるようになる）。

### M-7. `docs/LINE_SETUP.md` の「現状」が陳腐化しており、読むと設定済みの本番を未設定と誤認する
- 業務・画面: 運用手順書
- 事象: 「現状（2026-09-04 時点）: … Render は `LINE_CLIENT_ID` 未設定（exchange が 503）・
  `LINE_CHANNEL_ACCESS_TOKEN` 未設定」と書かれているが、同日中に設定が完了し exchange は 503→401 へ遷移済み
  （PROJECT_STATE の完了ログ）。手順書だけを見た担当者が「未設定」と判断して再設定に走ると、
  トークン再発行で稼働中の LINE 通知を壊しうる。
- 根拠: `docs/LINE_SETUP.md:6`／`.agent-state/PROJECT_STATE.md`「09-04 LINE 連携の本番設定（ユーザー実施）」
- 修正案: 「現状」節を削除し（陳腐化する情報を手順書に置かない）、確認手順（§6 の curl）だけを残す。

### M-8. 新規管理者の追加手順が運用手順書に存在しない（`docs/ops/` に日次運用の runbook が 1 本も無い）
- 業務・画面: 管理者の追加（`/admin/users` の「管理者にする」）
- 事象: 2人目以降の admin 追加は `POST /admin/users/{id}/promote`（画面の「管理者にする」）が唯一の正規経路と
  コードのドキュメント文字列に書かれているが、これを説明した運用文書が無い。`docs/ops/` の中身は
  `alerting.md` 1 本のみで、手順の記載は `docs/TODO.md` 01-6 の末尾 1 文だけ（TODO は完了すると消える場所）。
  昇格・降格は `alerts.send_alert(severity="critical")` を発火する重い操作であり、手順の所在が TODO なのは危うい。
- 根拠: `backend/app/api/v1/endpoints/admin.py:1017-1022`（正規経路の宣言）／`ls docs/ops/` = `alerting.md` のみ／
  `docs/TODO.md` 01-6（唯一の記述）
- 修正案: `docs/ops/admin-operations.md` を新設し、①管理者の追加/解除手順と前提（対象は
  `deleted_at IS NULL` かつ `is_suspended=false` かつ `role="user"`）②昇格時に critical アラートが飛ぶこと
  ③`ADMIN_EMAILS` は「有効 admin 不在時のみ」自動付与される緊急経路であることを書く。

### M-9. `docs/beta-operator-onboarding.md` が「許可証画像をどこで出すか」を書いておらず、承認待ち滞留の直接原因になる
- 業務・画面: 業者オンボーディング（送付テンプレート）
- 事象: 本文は「入札は運営の承認後（通常3営業日以内・許可証画像の提出が必要）」とだけ書き、アップロード先
  （`/operator/profile` の「許可証の画像」）に触れていない。許可証未提出の業者は `verify_operator` が 409 で
  承認を拒むため、運営から見ると「pending のまま動かない業者」として溜まり続ける（M-4 と直結）。
  併せて減額申請の「1 取引につき 2 回まで」（r8 で追加）も未記載で、業者からの問い合わせ要因になる。
- 根拠: `docs/beta-operator-onboarding.md`（手順 1〜4 に許可証アップロードの記載なし）／
  `web/src/app/operator/profile/page.tsx:576`（実際の提出場所）／
  `backend/app/api/v1/endpoints/admin.py:377-382`（未提出は 409）／
  `backend/app/api/v1/endpoints/reductions.py:34,109-112`（2 回上限）
- 修正案: 手順に「4. `/operator/profile` を開き『許可証の画像』をアップロード（承認に必須）」を追加し、
  減額申請の節に上限回数を 1 行追記する。

---

## 1日の業務の一覧（管理画面で見える／通知で届く／どちらも無い）

| 業務 | 管理画面 | 通知 | 根拠 |
|---|---|---|---|
| 事前申込の審査待ち | ○ `/admin/operator-applications`・トップに赤バッジ（total 由来） | ○ 申込時に `ADMIN_EMAILS` へメール | `web/src/app/admin/page.tsx:390-400`／`operator_applications.py:161` |
| 業者の承認待ち（pending） | △ `/admin` の絞り込みに件数。ただし「許可証提出済み＝承認可能」の内訳は無し（M-4） | ✗ 登録・許可証アップロード時の運営通知は無し | `admin.py:252-258, 377-382`／`operator_license.py:65`（通知呼び出し無し） |
| 本人確認書類の審査待ち | △ `/admin/identity-documents`（既定 pending）。バッジ・総件数・検索は無し（M-1/M-2/M-3） | ✗ 提出時の運営通知は無し | `admin.py:1358-1392`／`user_identity.py:167` |
| 停止解除依頼 | ✗ 待ち行列も停止中の絞り込みも無し（M-5/M-6） | ✗（当事者は `/contact` へ誘導されるが DB に残らない） | `deps.py:79-83`／`contact.py:194-207` |
| 未回答の減額申請 | ✗ 管理画面に一覧・絞り込み無し（`/admin/transactions` の status は取引状態のみ） | ✗ 運営宛の通知は無し（当事者間のみ） | `admin.py:619-632`／`reductions.py:65-140` |
| 訪問日超過 | ✗（`visit_date` は一覧に**表示**されるが超過の絞り込み・並べ替えは無し） | ✗ | `admin.py:800-812`／TODO 03 で意図的未対応 |
| 入札ゼロ放置 | ✗（`/admin/cases` に入札数の列も絞り込みも無し） | ✗ | `admin.py:598-612`／TODO 03 で意図的未対応 |
| 問い合わせ | ✗ 画面なし（DB 保存なし） | ○ `ADMIN_EMAILS` へメール＋閾値超過時に warning アラート | `contact.py:179-207` |
| 5xx バースト・未処理例外 | ✗ | ○ LINE / Webhook / メール（ただし H-3 の死活未検証） | `core/alert_middleware.py:33-79` |
| 本番設定の欠落（Brevo/LINE/暗号鍵） | △ `/readyz` の `degraded_config`（人が curl した時だけ） | ✗ 外形監視は判定に使っていない（H-2） | `main.py:308-316`／`scripts/uptime_check.py:78-89` |
| admin 権限の付与・剥奪 | ○ `/admin/users` | ○ critical アラート | `admin.py:1046-1060, 1103-1114` |

### 運営操作の完了後に当事者へ届くもの

| 操作 | 相手 | 届く | 根拠 |
|---|---|---|---|
| 事前申込 承認（招待コード） | 業者 | ○ メール | `admin.py:1283-1288` |
| 事前申込 却下（理由付き） | 業者 | ○ メール（理由入り） | `admin.py:1337-1342` |
| 業者の承認 / 取消（verify） | 業者 | ○ LINE→メール。**状態が変わった時のみ** | `admin.py:386-394` |
| 業者・依頼者の停止 | 本人 | ✗ 無通知（設計判断。ログイン時に 403 で気付く） | `admin.py:428-431` のコメント／`:951-954` |
| 停止の解除 | 本人 | ○ LINE→メール。**停止→解除の遷移時のみ** | `admin.py:428-437`, `:951-960` |
| 成約の強制終了 | 双方 | △ メール/LINE は届くが、依頼者はリンク先に理由が無い（H-1） | `notify.py:315-338`／`web/src/app/chat/[id]/page.tsx:388-392` |
| 本人確認 承認 / 却下 | 依頼者 | ○ LINE→メール（却下は理由入り） | `admin.py:1516-1523`, `:1602-1609` |
| 口コミの非表示 | 投稿者 | ✗ 無通知（かつ UI も無し＝TODO 03 既知） | `admin.py:445-475` |

### 実務量（業者 100 社・案件 1,000 件）への耐性

- ○ `cases` / `transactions` / `users` / `operators` / `operator-applications`: `q` 検索・`status` 絞り込み・
  `total` 付きページング（50 件）・`id` tie-breaker・N+1 回避（メール／案件数／キャンセル主体はバッチ取得）まで揃う。
  `admin.py:583-590, 690-700, 891-901`。
- △ `identity-documents` のみ検索なし・total なし・tie-breaker なし（M-1〜M-3）。
- ○ `cell-density` は都道府県×用途の GROUP BY で行数が有界。`admin.py:476-518`。
- ✗ 「今日やること」を 1 画面に集約するダッシュボードは無く、5 タブを順に開く運用が前提。

### 個人情報の取り扱い

- 口座全桁の復号開示（`admin.py:1188-1230`）・許可証画像（`operator_license.py:198-214`）・本人確認画像
  （`admin.py:1425-1455`）はいずれも admin 限定で、`admin_id` + `admin_email` を含む閲覧ログを出す。
  本人確認画像は `Cache-Control: private, no-store` 付き。一覧 API は BLOB を列指定 select で除外し、
  退会済みユーザーの書類を JOIN 条件で除外する（`admin.py:1385-1393`）。
- 監査ログが標準出力のみである点は `docs/TODO.md` 03 で既知の意図的未対応のため再指摘しない。

## 保存パス
`C:\Users\ko13h\Claude\Projects\ソクウリ\.agent-state\audit\r10-operator.md`

## サマリ
- ❌ H-1 強制終了の理由が依頼者の着地ページに無い／H-2 `degraded_config` 未監視／H-3 アラート基盤の死活未検証
- ⚠️ M-1〜M-4 本人確認・業者承認の待ち行列が数えられない／M-5・M-6 停止まわりの棚卸し不能／M-7〜M-9 手順書の陳腐化と欠落
- ✅ 認可境界（24/24 ルートが `get_current_admin`・停止/退会 admin は到達不能）、r6 通知欠落 H1〜H3 の解消、
  主要 5 一覧の検索・ページング・N+1 対策、PII 閲覧ログは回帰なし
