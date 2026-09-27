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

## 自動リマインド（訪問日超過・入札ゼロ放置・入札未決定）
- **何が自動で飛ぶか**: (a) 訪問予定日を過ぎても完了確定されていない成約 → 依頼者と業者の双方へ、(b) 作成から3日経っても入札が1件も付かない案件 → 依頼者へ、(c) 入札は届いているが2日経っても依頼者が決定していない案件（`status='bidding'`）→ 依頼者へ。LINE 連携済みなら LINE、未連携ならメール。**同じ成約・案件へは1回だけ**（送信済みの印を DB 列に持つため、再デプロイ・手動実行・複数インスタンスでも重複しない）。(c) は選択できない入札（停止中・承認取消・退会済み業者のもの）を母集団から除外しているため、選べる入札が実際に残っている案件だけに送る。
- **いつ走るか**: バックエンド常駐の背景ループが `REMINDER_INTERVAL_SECONDS`（既定 3600 = 毎時）毎に1周。起動直後にも1周する。1周あたり最大 200 件、対象は「直近14日以内に該当したもの」に限る（それより古い放置は催促しない）。(c) は「最古の pending 入札からの経過」が基準のため、その入札が窓（2+14日）を超えて古いまま新たな入札が来ない案件は以後も対象外になり続ける（仕様）。
- **手動実行**: `POST /admin/jobs/reminders`（管理者トークン、または後述の `X-Ops-Token`）。応答は `{"overdue": n, "no_bid": n, "bids_pending": n}` = 今回リマインドした件数。動作確認や、キルスイッチで自動実行を止めている間に手で1周回したいときに使う。
- **キルスイッチ**: Render ダッシュボードの環境変数 `REMINDERS_ENABLED=false` → 再デプロイ で背景ループを起動しない（手動実行は生きたまま）。`render.yaml` に追記しても既存サービスには同期されないため、**必ずダッシュボードで設定する**。`REMINDER_INTERVAL_SECONDS` は 60 秒未満を指定しても 60 秒に切り上げられる。
- **spin-down 対策**: Render 無料枠はアイドルでスピンダウンし、その間は背景ループも止まる。このため GitHub Actions「Ops cron」が**毎時 7 分に外から `POST /admin/jobs/reminders` を叩く**（起こす＋1周回す）。背景ループと二重に走っても送信済みの印で重複しない。
- **再送したい / 送らないようにしたい**: 送信済みの印は `transactions.overdue_reminded_at` / `cases.no_bid_reminded_at` / `cases.bids_pending_reminded_at`。再送は DB で該当行を NULL に戻す（管理画面の操作は用意していない）。通知の送信自体に失敗した場合は再送されず、運営 LINE へ warning アラートが飛ぶ想定だが、この経路は現状 `notify_dispatch` 側で例外が握り潰されるため実際には発火しないことが判明している（別件で要修正・[bids-pending reminder に付随して発見]）。

## 署名付き中継IPの鍵（CLIENT_IP_RELAY_SECRETS）
- **何のための鍵か**: web(Vercel) がサーバー側から呼ぶ `/auth/login`・`/auth/operator/login`・`/auth/line/exchange` は、backend からは常に Vercel の送信元IPに見えるため、レート制限のIP軸（本来は X-Forwarded-For の hops 方式）が全利用者で共有されてしまう。web が実際の利用者IPを HMAC 署名して中継し、backend は署名が正しい場合のみ `login`・`line_exchange` の2 scope 限定でそのIPを採用する（それ以外の scope・不採用時は常に従来どおり hops 方式）。
- **鍵はチャットやログに絶対に貼らない**（値そのものは backend のログにも一切出力されない設計）。
- **投入・入れ替えの順序**: ① Render dashboard で `CLIENT_IP_RELAY_SECRETS` を設定 → 環境変数を変えたら**手動で再デプロイ**（`render.yaml` の envVars は既存サービスに同期されないため、dashboard での設定のみでは反映されない）→ ② Vercel 側の `CLIENT_IP_RELAY_SECRET` に同じ値を設定。**必ず Render を先に**行う（backend が新しい鍵を受け付けられる状態にしてから web に使わせる。逆順だと一時的に署名不一致で hops へフォールバックするだけで実害は無いが、確認の手間を減らすため）。
- **反映確認**: `/readyz` の `config.client_ip_relay` が `true`（値そのものは返らない）。実際に採用されたかは、backend ログの `client_ip_relay: 起動後初めて署名付き中継の利用者IPを採用しました…key_slot=N` という WARNING（`(scope, key_slot)` の組ごとに1回だけ出る。2回目 security review L-B により鍵を入れ替えるたびに新しい key_slot で再度出るようになった）で確認する。2回目以降は INFO 格下げ・60秒に1回のスロットリングのため、ログ保持期間（Render 無料枠は7日）内に見つからないことがある。
- **鍵の妥当性チェック**: `/readyz` の `config.client_ip_relay_secrets_valid` が `false`（＝`degraded_config` に `client_ip_relay_secrets_valid` が含まれる）の場合、`CLIENT_IP_RELAY_SECRETS` に設定した候補のどれかが除外されている（短すぎる・既知のテストベクトル鍵/命名パターンと一致・使用文字が偏っている、のいずれか）。`client_ip_relay`（鍵が1本以上有効か）とは独立したフラグで、こちらが `false` でも有効な鍵が残っていれば中継自体は動く。原因の詳細（何番目の候補か・理由）は backend ログの `client_ip_relay: CLIENT_IP_RELAY_SECRETS の…番目の鍵が…` という ERROR（値・長さは出ない）で確認する。鍵は `python -c "import secrets; print(secrets.token_urlsafe(48))"` 等、十分にランダムな値で生成すること（コピペミスやドキュメント例示値をそのまま貼っていないか疑う）。
- **Vercel 側の環境変数設定**: `CLIENT_IP_RELAY_SECRET` は **Production 環境のみ**に設定し、**Sensitive（値をマスクする）** を有効にする。**Development / Preview のチェックは外す**（プレビューデプロイは URL を知っていれば誰でも触れるため、本番と同じ鍵を晒す経路になる）。本番以外の環境で試す必要がある場合も、**本番の鍵をそのまま使い回さない**（環境ごとに別の値にする。使い回すと、プレビュー環境の漏洩がそのまま本番の署名偽造に直結する）。
- **本番投入後の偽装耐性の確認手順（security review M-2・2回目レビューで是正。必ず中継の採用 WARNING を確認した「後」に行う）**: 中継が効いていない状態でこの手順を行うと**全利用者のログインが最大15分止まる**ため、順序を厳守すること。自宅などの固定回線で行い、**直前15分に同じ回線でログイン失敗をしていないこと**（社内など共有 NAT 配下で行うと、同じ出口を使う他人も巻き添えで最大15分ログインできなくなる）。
  - **旧手順の欠陥（是正済み）**: 同じメールアドレスで20回送ると、IP軸より先にアカウント軸（5回/15分）の 429 に当たってしまい偽装の成否を誤判定する。また送り手から直接見えるのは backend の 401/429 ではなく、web（NextAuth）がそれを変換した後のリダイレクト先であり、旧手順はこの変換を経由しない前提で書かれていた。
  1. **21回すべて別々の・backend の入力検証を通る未登録メール**（例 `spoofcheck-01@example.com` から連番で `spoofcheck-21@example.com` まで）を使う（アカウント軸の429に先に当たらないようにするため）。送信は **`curl -4` に固定**する（デュアルスタック環境だと実IPがIPv4/IPv6で揺れ、偽装の成否と無関係な要因で結果がぶれるため。IPv6側の中継も別途確認したい場合は `-6` を付けてこの手順をもう一度行う）。
  2. CSRF トークンを取得する: `curl -4 -c jar https://<web>/api/auth/csrf`（応答 JSON の `csrfToken` を控える。以降の全リクエストで同じ `jar` を使い回す）。
  3. 1〜20回目は TEST-NET の値 A（例 `203.0.113.10`）を、21回目だけ値 B（例 `203.0.113.20`）を使い、`x-real-ip`・`x-forwarded-for`・`x-vercel-forwarded-for`・`forwarded` の4ヘッダすべてに同じ値を付けて、誤ったパスワードで `spoofcheck-NN@example.com`（NN は連番）宛に送信する:
    `curl -4 -b jar -o /dev/null -w '%{redirect_url}\n' -H 'x-real-ip: 203.0.113.10' -H 'x-forwarded-for: 203.0.113.10' -H 'x-vercel-forwarded-for: 203.0.113.10' -H 'forwarded: for=203.0.113.10' --data-urlencode csrfToken=<控えた値> --data-urlencode email=spoofcheck-NN@example.com --data-urlencode password=wrong-password https://<web>/api/auth/callback/user-credentials`
  4. **判定は 21 回目のリダイレクト先（`%{redirect_url}`）を見る**（backend の 401/429 は web 側の NextAuth が握って変換するため、curl からは直接見えない）。リダイレクト先に **`code=rate_limited`** が付けば**偽装は効いていない**（web が中継する実クライアントIPで正しく数えられている＝想定どおり）。**`code=credentials`**（通常の認証失敗）が付けば**偽装できてしまっている**（自分で送ったヘッダの値で数えられている＝web 側が実クライアントIPではなく偽装可能なヘッダを中継してしまっている疑い）ため、直ちに Vercel 側の `CLIENT_IP_RELAY_SECRET` を削除して再デプロイし、中継を止めて hops 方式のみへ切り戻す。（`code=` の値の出典: web/src/auth.ts の `RateLimitedError`（`code="rate_limited"`。backend の429を変換）と NextAuth 標準の `CredentialsSignin`（`code="credentials"`）。値は今後の web 側の実装変更で変わりうるため、実施前に必ず該当ファイルを読んで確認すること。）
  5. **陽性対照（判定後に必ず行う）**: 別の回線（スマホのテザリング等、上記と異なる実IPになる経路）から1回、`spoofcheck-` シリーズとは別の未登録メールで誤ったパスワードを通常どおり送信し、`code=credentials` になることを確認する（直前の 429/`rate_limited` が「テスト用に共有した特定の枠」ではなく「自分のIPで正しく数えられていたこと」の裏付け。ここでも `code=rate_limited` になる場合、20回分の失敗が想定と違うバケット（例えばIP以外の軸）に乗っている疑いがあり、手順・実装の双方を疑うこと）。
  6. この手順による影響は**自分（と、共有 NAT 経由の場合は同じ出口の他人）が最大15分ログインできなくなるだけ**（scope="login" の IP軸の窓が15分のため）。
- **ローテーション（鍵の入れ替え）**: 新鍵への切替は ① Render 側を `NEW,OLD`（カンマ区切り・両方同時に有効。`NEW` を先頭にする）に設定→**環境変数を変えたら手動で再デプロイ**（Render・Vercel とも環境変数の変更だけでは反映されず、再デプロイが必要）→② Vercel 側を `NEW` のみに切替→再デプロイ→③ **反映確認**: backend ログで `client_ip_relay: 起動後初めて署名付き中継の利用者IPを採用しました…key_slot=0` という WARNING が **scope=login と scope=line_exchange の両方**で出たことを確認する（key_slot=0 は「先頭の鍵＝ NEW」が実際に採用されたことを意味する。2回目 security review L-B により、鍵を入れ替えるたびに key_slot ごとの初回 WARNING が再度出るようになった）→④ 確認後に Render 側も `NEW` のみに戻す（旧鍵 `OLD` を無効化）。**③の反映確認を飛ばして④に進まないこと**（`NEW` が実際に web 側で使われているかを確認しないまま `OLD` を外すと、設定ミスに気付けないまま鍵を失うことになる）。
- **停止（無効化・切り戻し）**: Vercel 側の鍵（`CLIENT_IP_RELAY_SECRET`）を削除して再デプロイすれば、中継ヘッダが送られなくなり自動的に hops 方式のみへ戻る（backend 側の鍵を消す必要は無い。backend 側だけ消したい場合も Render の値を空にして再デプロイすれば同様に hops のみへ戻る）。
- **残るリスク（対策済みの上でなお残る既知の限界。解消済みと誤解しないこと）**:
  1. **再送（リプレイ）耐性が無い**: v1 はノンスやリクエスト本文ハッシュを署名対象に含めていないため、有効なヘッダ値を盗聴・記録できた第三者は、時刻ずれが60秒以内であれば同じヘッダ値をそのまま再送して同じ利用者IPとしてカウントさせられる。ヘッダは TLS 区間内のみを流れ、web・backend とも生のヘッダ値をログや APM に記録しない前提のため実務上のリスクは小さいと判断している。将来 APM 等でリクエストヘッダを記録する仕組みを導入する場合は、v2 でノンスまたは本文ハッシュを署名に加えて1回限りの使用に強制する必要がある。
  2. **共有 IPv4（携帯回線の CGNAT 等）の巻き添え**: 中継が正しく動作していても、同じキャリア NAT の裏にいる複数の利用者は同じ実クライアントIPとして数えられ、1人の連続失敗が同じ NAT 配下の他の利用者を巻き込みうる。ただし「全利用者が同一バケットを共有する」問題（本機能導入前の状態）と比べれば影響範囲ははるかに小さい。
  3. **hops のドリフト検知が効かない範囲がある**: 中継が採用されている間（login/line_exchange が中継IPで数えられている間）は、hops 方式側のドリフト検知（診断用 scan との不一致 WARNING）は実行されない（中継が不採用でhopsにフォールバックしたときのみ動く）。他の scope（signup 等）では従来どおり常に動く。
  4. ~~**IPv6 の /64 集約は未対応**~~ **解消済み（2回目 security review M-1 で確認）**: 中継IPの IP軸判定は `rate_limit_deps._apply_ip_axis`（IPv6 を /64・/56・/48 の3段で数える。1d14e6f）にそのまま委譲されるため、hops 方式・中継方式のどちらでも /64 集約が効く（中継専用の別実装は無い）。結合の固定テストは `tests/test_client_ip_relay_api.py::TestRelayIpv6TierIntegration`。
- **運用上の注意点（構成変更時に見直すこと。2回目 security review I-b/I-c/I-d）**:
  1. **Vercel の Sensitive 属性は「値を手元に取り出せない」ための前提であること**: Sensitive 属性はダッシュボード上で値をマスクする機能であり、ビルド・実行時にプロセスへ環境変数として渡ること自体は防がない。**Vercel 以外の環境で本番ビルドを動かす場合は `CLIENT_IP_RELAY_SECRET` を渡さないこと**（未設定なら web 側は中継ヘッダを付けず、中継が無効化されて hops のみへ自動フォールバックするだけで実害は無い）。
  2. **backend のスピンアップ直後は中継が `expired` になり hops へ戻ることがある（想定内）**: Render 無料枠のコールドスタート遅延により、タイムスタンプの許容ずれ（60秒）を超えることがある。攻撃や両サーバー間の時計ずれと誤読しないこと。
  3. **CF レンジ警告で検知できるのは Cloudflare だけ**: `is_cloudflare_range` は Cloudflare の公開IPレンジのハードコード判定のため、他社CDN・プロキシ（Fastly・Akamai・自前のリバースプロキシ等）を Vercel の前段に置く構成変更は検知できない。Vercel の Trusted Proxy 機能を有効にする、または Vercel の前段に別のプロキシを追加する場合、`x-real-ip` 等のヘッダの意味（どの層のIPが入るか）が変わりうるため、その都度 I8 の前提（web が利用者の実IPを中継できているか）を見直すこと。
  4. **APM・Sentry 等導入時は中継ヘッダをスクラブすること**: `X-Katazuke-Client-Ip-Relay` ヘッダの値には利用者の実IPが平文で含まれ、上記「残るリスク 1.」（再送耐性が無い）と組み合わさると、記録された値がそのまま有効期限内に再送可能な「署名済みトークン」として残ってしまう。APM・エラートラッキング導入時はリクエストヘッダの自動収集対象からこのヘッダを必ず除外（スクラブ）すること。
  5. **v2 で再送対策をする場合はリクエスト本文の SHA-256 を署名対象に加える方式を推奨**: ノンス方式（サーバー側で使用済みノンス集合の保持・掃除という状態管理コストが要る）よりも、本文ハッシュ方式（状態を持たず、内容が同一の正当な重複リクエストを誤って拒否しない）を推奨する。

## 監視
- 外形監視（GitHub Actions・5分毎）が /health・/readyz を確認し、異常は運営 LINE 公式アカウントへ通知。`/readyz` の `degraded_config` が非空（brevo・line_push・encryption_key・gemini・admin_emails・frontend_base_url の未設定、または `CLIENT_IP_RELAY_SECRETS` に不正な鍵が混じっている場合の `client_ip_relay_secrets_valid`）も warning で通知される。
- メール送信キー未設定・送信失敗はアプリから critical/warning アラート。詳細は alerting.md。

## 自動運用（GitHub Actions「Ops cron」・`.github/workflows/ops-cron.yml`）

人手の定期確認を機械化した。**正常時は何も通知しない**。失敗・不整合だけが運営 LINE／メールに届き、Actions の実行も赤くなる。実体は `scripts/ops_jobs.py`。

| ジョブ | 周期 | 何をするか | 失敗時に届く通知 |
| --- | --- | --- | --- |
| `hourly` | 毎時 7 分 | `/health` で Render を起こし `POST /admin/jobs/reminders` を1周 | backend が起きない／ジョブが非200 |
| `daily` | 毎日 03:00 JST | ① `POST /admin/jobs/admin-audit`（ADMIN_EMAILS の全アドレスが登録済み・role=admin・非停止か）② `POST /admin/jobs/contacts/handle-probes`（差出人が `OPS_PROBE_CONTACT_EMAIL` **かつ氏名が「カタヅケ運営（自動確認）」と完全一致・受信7日以内**の未対応行を対応済みへ。同じアドレスでも氏名が違えば実相談として残す）③ `POST /admin/jobs/mail-probe`（運営宛に到達確認メールを送り、Brevo のイベント API で **delivered まで最大5分追跡**。直近20時間以内に試行済みなら送らない）④ Brevo の直近1日集計でバウンス・ブロック・エラーが 0 件か ⑤ **毎時ジョブが直近24時間に20回以上成功しているか**（GitHub API で実行履歴を数える＝「実行されなかった」の検知） | ①不整合（アプリ側からも critical アラート）②なし ③配送未確認・失敗 ④配送不能あり ⑤失敗あり／成功回数不足 |
| `key-check` | 毎週月曜 04:00 JST | backend の `POST /admin/jobs/key-fingerprint`（鍵の SHA-256 のみ返す）と GitHub Secrets の控え `APP_ENCRYPTION_KEY_ESCROW` の SHA-256 を照合（値も指紋も出力しない・Render API キー不要） | 控え未登録／不一致／本番が空 |
| `key-restore` | 手動のみ | `/readyz` が `encryption_key` 未設定を報告し、**かつ Render の値が空のときだけ**控えを書き戻して再デプロイ。設定済みの鍵を上書きする経路はワークフローに無い（別の鍵で上書きすると保存済みデータが復号不能になるため） | 復元を実行したときに通知（成功でも届く） |

- **手動実行**: GitHub → Actions → Ops cron → Run workflow → `job` を選ぶ。`key-restore` は鍵消失時の復旧専用で、通常は触らない。ジョブは `ops`（hourly/daily）・`key-check`・`key-restore` に分かれ、それぞれ必要な Secrets しか受け取らない（Render API キーは `key-restore` だけ、鍵の控えは `key-check`/`key-restore` だけ）。スクリプトに到達する前に落ちた場合も末尾の `notify-failure` ジョブが運営へ通知する。
- **運営ジョブの機械認証（`X-Ops-Token`）**: `/api/v1/admin/jobs/*` だけは、管理者ログインの代わりにヘッダ `X-Ops-Token: <OPS_JOB_TOKEN>` でも実行できる（`secrets.compare_digest` 比較・未設定または 32 文字未満なら無効・不一致は値を出さずに warning ログ、プロセス内で 5 回に達したら運営へ warning アラート）。一覧閲覧や停止・昇格など他の管理 API には効かない。curl 例: `curl -X POST -H "X-Ops-Token: $OPS_JOB_TOKEN" https://sokuri-backend.onrender.com/api/v1/admin/jobs/admin-audit`
- **鍵の控えを GitHub Secrets に置くことの意味**: GitHub アカウント／Actions の侵害が本番暗号鍵の侵害と等価になる。リポジトリの Collaborator と PAT の発行は最小に保ち、鍵ジョブに渡す Secrets を運用ジョブへ広げない。将来、外部の Secret Manager に移す余地あり。
- **初期設定（済・再実行可）**: `backend\.venv\Scripts\python.exe scripts\ops_bootstrap.py --probe-email katazuke.info@gmail.com` が `.env.alerts` の GITHUB_TOKEN / RENDER_API_KEY で、① `OPS_JOB_TOKEN`（Render 環境変数＋GitHub Secret）② `APP_ENCRYPTION_KEY_ESCROW`（GitHub Secret＝鍵の控え）③ `RENDER_API_KEY`（GitHub Secret）④ `OPS_PROBE_CONTACT_EMAIL`（Render）を登録する。値は表示しない。**鍵を Render 側で変えたら同じコマンドで控えを更新する**（`key-check` が不一致を通知する）。
- **必要な Secrets / 環境変数**: GitHub Secrets = `OPS_JOB_TOKEN`, `RENDER_API_KEY`, `APP_ENCRYPTION_KEY_ESCROW` ＋ 通知系（`uptime-alert.yml` と共通）。Render 環境変数 = `OPS_JOB_TOKEN`, `OPS_PROBE_CONTACT_EMAIL`。 `render-sync.yml` は `RENDER_API_KEY`（key-restore と共通）＋通知系を使う。
- **PostgreSQL 同時実行チェックは CI に移した**: `ci.yml` の `pg-concurrency` ジョブが push ごとに PostgreSQL 16 サービス上で実マイグレーション→API 起動→`scripts/pg_concurrency_check.py` の 6 シナリオを回す。ローカルの Docker は不要。
- **復旧の通知（原則: 失敗を通知した経路には必ず復旧も届く。復旧の連絡が来ないものは未解決）**: ①Ops cron は失敗が続いたあと正常に戻ったときに「[RECOVERED] {ジョブ名} が正常に戻りました」が1回届く（前回の成否を Actions のキャッシュ `.ops_state.json` でジョブ別に持ち回す。スクリプト到達前に落ちた場合も `notify-failure` ジョブが失敗状態を保存するので、次回成功で同じ復旧通知が出る）。②CI（`ci.yml` 末尾の `notify` ジョブ・`scripts/run_transition_notify.py`）は main への push で失敗すると「[カタヅケCI][FAILED]」、直前の完了実行が失敗で今回成功なら「[カタヅケCI][RECOVERED]」を LINE／メールへ送る（直前の結論は GitHub API の実行履歴から引く。concurrency で打ち切られた cancelled は数えない）。③Render Blueprint 同期（`render-sync.yml`・`scripts/render_sync_check.py`）は render.yaml を含む push のあと同期結果を確認し、error なら「[FAILED] Render Blueprint 同期が失敗」、直前が error で今回 success なら「[RECOVERED]」を送る（Render 自身は失敗メールしか送らない。エラー本文は dashboard の Blueprint ページ）。④外形監視は down→up で「[RECOVERED] 復旧しました」。⑤アプリ内アラートも「メール送信失敗（Brevo）」「ADMIN_EMAILS の棚卸し不整合」「5xx 急増」は解消時に ✅【Recovered】が届く（発報していない異常の復旧は送らない・再起動をまたいだ復旧は次回から）。
- **アラートの宛先**: メールは `ALERT_EMAILS`（GitHub Secrets・現在は katazuke.support@gmail.com と ko.13.hei@gmail.com）、LINE は運営用公式アカウント。GitHub の「Run failed」や UptimeRobot の Down/Up は ko.13.hei@gmail.com に直接届くため、**復旧通知が同じ受信箱に届くよう宛先を揃えておくこと**（INC-2026-09-11-3）。日次ジョブ ①-2 がズレを検知する。
- **障害台帳と再発防止ガード**: `docs/ops/incidents.md`。障害対応は台帳への追記とガード化（drift 検査・通知の対ガード等）まで済んで完了。render.yaml と Render 実態のズレは `render-sync.yml`（push 後・毎週月曜）が検査する。
- **止めたいとき**: Actions の Ops cron を Disable workflow。アプリ側の `OPS_JOB_TOKEN` を Render から消せば `X-Ops-Token` 経路そのものが閉じる。
