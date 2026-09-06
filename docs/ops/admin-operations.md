# 運営オペレーション手順（管理画面）

更新: 2026-09-06。管理画面は https://sokuri.vercel.app/admin（管理者ロールのアカウントでログイン）。定期的な確認作業は GitHub Actions「Ops cron」が自動で回す（下記「自動運用」）。

## 毎日やること（管理画面トップの件数バッジが起点）
1. **事前申込の審査**（/admin/operator-applications）: /business からの申込。詳細を確認して承認（招待コードが発行され申込者へメール送付）または却下（理由必須・申込者へメール）。同じメールの業者が既に居る場合は 409 になるので、その申込は却下する。
2. **業者の承認**（/admin）: 「pending（うち許可証提出済み n）」の業者を確認。許可証画像を見て問題なければ承認（入札可能になり業者へ通知）。許可証未提出は承認できない。審査中（pending/rejected）業者は承認まで案件を閲覧できない（`GET /cases`・`/cases/{id}`・`/cases/{id}/bids`・案件写真が 403 `approval_required` を返す）。また、承認後に閲覧できる案件一覧・詳細でも他社の入札額は業者に非開示（自社の入札額と入札社数のみ表示）。
3. **本人確認書類の審査**（/admin/identity-documents）: 審査待ちを承認／却下（依頼者へ通知）。
4. **お問い合わせ**（/admin/contacts）: 未対応を確認し、返信したら「対応済みにする」。メールでも ADMIN_EMAILS 宛に届く。
5. **取引の確認**（/admin/transactions）: 訪問日超過や当事者が応答不能な取引は「強制終了」（理由は双方に表示される）。

## 例外対応
- **業者の停止／解除**（/admin）: 停止すると入札・チャット等が全て 403 になり、依頼者側には「利用停止中」と表示される。解除すると復帰（業者へ通知）。
- **依頼者の停止／解除**（/admin/users）: 同様。進行中の案件件数が返るので、必要なら取引を強制終了する。
- **管理者の追加／解除**（/admin/users）: 対象ユーザーの行の「管理者にする」「管理者を解除」。ADMIN_EMAILS による自動付与は「管理者が1人も居ない時」だけ働く（初回のみ）。自分自身や最後の1人は解除できない。
- **退会**: 依頼者は /mypage/withdraw、業者は /operator/profile から本人がパスワード再入力で退会する。進行中の取引がある間は退会できない。

## 自動リマインド（訪問日超過・入札ゼロ放置）
- **何が自動で飛ぶか**: (a) 訪問予定日を過ぎても完了確定されていない成約 → 依頼者と業者の双方へ、(b) 作成から3日経っても入札が1件も付かない案件 → 依頼者へ。LINE 連携済みなら LINE、未連携ならメール。**同じ成約・案件へは1回だけ**（送信済みの印を DB 列に持つため、再デプロイ・手動実行・複数インスタンスでも重複しない）。
- **いつ走るか**: バックエンド常駐の背景ループが `REMINDER_INTERVAL_SECONDS`（既定 3600 = 毎時）毎に1周。起動直後にも1周する。1周あたり最大 200 件、対象は「直近14日以内に該当したもの」に限る（それより古い放置は催促しない）。
- **手動実行**: `POST /admin/jobs/reminders`（管理者トークン、または後述の `X-Ops-Token`）。応答は `{"overdue": n, "no_bid": n}` = 今回リマインドした件数。動作確認や、キルスイッチで自動実行を止めている間に手で1周回したいときに使う。
- **キルスイッチ**: Render ダッシュボードの環境変数 `REMINDERS_ENABLED=false` → 再デプロイ で背景ループを起動しない（手動実行は生きたまま）。`render.yaml` に追記しても既存サービスには同期されないため、**必ずダッシュボードで設定する**。`REMINDER_INTERVAL_SECONDS` は 60 秒未満を指定しても 60 秒に切り上げられる。
- **spin-down 対策**: Render 無料枠はアイドルでスピンダウンし、その間は背景ループも止まる。このため GitHub Actions「Ops cron」が**毎時 7 分に外から `POST /admin/jobs/reminders` を叩く**（起こす＋1周回す）。背景ループと二重に走っても送信済みの印で重複しない。
- **再送したい / 送らないようにしたい**: 送信済みの印は `transactions.overdue_reminded_at` / `cases.no_bid_reminded_at`。再送は DB で該当行を NULL に戻す（管理画面の操作は用意していない）。通知の送信自体に失敗した場合は再送されず、運営 LINE へ warning アラートが飛ぶ。

## 監視
- 外形監視（GitHub Actions・5分毎）が /health・/readyz を確認し、異常は運営 LINE 公式アカウントへ通知。`/readyz` の `degraded_config` が非空（brevo・line_push・encryption_key・gemini・admin_emails・frontend_base_url の未設定）も warning で通知される。
- メール送信キー未設定・送信失敗はアプリから critical/warning アラート。詳細は alerting.md。

## 自動運用（GitHub Actions「Ops cron」・`.github/workflows/ops-cron.yml`）

人手の定期確認を機械化した。**正常時は何も通知しない**。失敗・不整合だけが運営 LINE／メールに届き、Actions の実行も赤くなる。実体は `scripts/ops_jobs.py`。

| ジョブ | 周期 | 何をするか | 失敗時に届く通知 |
| --- | --- | --- | --- |
| `hourly` | 毎時 7 分 | `/health` で Render を起こし `POST /admin/jobs/reminders` を1周 | backend が起きない／ジョブが非200 |
| `daily` | 毎日 03:00 JST | ① `POST /admin/jobs/admin-audit`（ADMIN_EMAILS の全アドレスが登録済み・role=admin・非停止か）② `POST /admin/jobs/contacts/handle-probes`（運営自身のプローブ問い合わせを対応済みへ）③ `POST /admin/jobs/mail-probe`（運営宛に到達確認メールを送り、Brevo のイベント API で **delivered まで最大5分追跡**）④ Brevo の直近1日集計でバウンス・ブロック・エラーが 0 件か | ①不整合（アプリ側からも critical アラート）②なし ③配送未確認・失敗 ④配送不能あり |
| `key-check` | 毎週月曜 04:00 JST | Render の `APP_ENCRYPTION_KEY` と GitHub Secrets の控え `APP_ENCRYPTION_KEY_ESCROW` を SHA-256 で照合（値は出力しない） | 控え未登録／不一致／本番が空 |
| `key-restore` | 手動のみ | `/readyz` が `encryption_key` 未設定を報告し、かつ Render の値が空のときだけ控えを書き戻して再デプロイ。`force=true` で条件を無視して上書き | 復元を実行したときに通知（成功でも届く） |

- **手動実行**: GitHub → Actions → Ops cron → Run workflow → `job` を選ぶ。`key-restore` は鍵消失時の復旧専用で、通常は触らない。
- **運営ジョブの機械認証（`X-Ops-Token`）**: `/api/v1/admin/jobs/*` だけは、管理者ログインの代わりにヘッダ `X-Ops-Token: <OPS_JOB_TOKEN>` でも実行できる（`secrets.compare_digest` 比較・未設定時は無効）。一覧閲覧や停止・昇格など他の管理 API には効かない。curl 例: `curl -X POST -H "X-Ops-Token: $OPS_JOB_TOKEN" https://sokuri-backend.onrender.com/api/v1/admin/jobs/admin-audit`
- **初期設定（済・再実行可）**: `backend\.venv\Scripts\python.exe scripts\ops_bootstrap.py --probe-email katazuke.info@gmail.com` が `.env.alerts` の GITHUB_TOKEN / RENDER_API_KEY で、① `OPS_JOB_TOKEN`（Render 環境変数＋GitHub Secret）② `APP_ENCRYPTION_KEY_ESCROW`（GitHub Secret＝鍵の控え）③ `RENDER_API_KEY`（GitHub Secret）④ `OPS_PROBE_CONTACT_EMAIL`（Render）を登録する。値は表示しない。**鍵を Render 側で変えたら同じコマンドで控えを更新する**（`key-check` が不一致を通知する）。
- **必要な Secrets / 環境変数**: GitHub Secrets = `OPS_JOB_TOKEN`, `RENDER_API_KEY`, `APP_ENCRYPTION_KEY_ESCROW` ＋ 通知系（`uptime-alert.yml` と共通）。Render 環境変数 = `OPS_JOB_TOKEN`, `OPS_PROBE_CONTACT_EMAIL`。
- **PostgreSQL 同時実行チェックは CI に移した**: `ci.yml` の `pg-concurrency` ジョブが push ごとに PostgreSQL 16 サービス上で実マイグレーション→API 起動→`scripts/pg_concurrency_check.py` の 6 シナリオを回す。ローカルの Docker は不要。
- **止めたいとき**: Actions の Ops cron を Disable workflow。アプリ側の `OPS_JOB_TOKEN` を Render から消せば `X-Ops-Token` 経路そのものが閉じる。
