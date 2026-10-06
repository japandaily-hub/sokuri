# 運営オペレーション手順（管理画面）

更新: 2026-10-06（業者退会時の削除・管理者の再設定・規約改定時の版数・Brevo の送信量を追記）。管理画面は https://sokuri.vercel.app/admin（管理者ロールのアカウントでログイン）。定期的な確認作業は GitHub Actions「Ops cron」が自動で回す（下記「自動運用」）。

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

## 本番への反映順（pdca/integ の早送り push。マイグレーション先行の段階反映）
列・表を読み書きするコードより先にマイグレーションを出す。同意を必須にする backend は**最後**（先に出すと、旧 web からのメール登録・LINE 新規登録がすべて 422 になる）。**SHA は最終の統合後に決まるため、役割で呼ぶ。各段の前に、その時点のコミットで CI が通ることを確かめ、各段の後に下の確認をしてから次へ進む。**
1. **マイグレーション 0047 単独コミット** → `/readyz` の head が 0047。
2. **再設定の backend ＋ web（再設定画面）** → デプロイ成功をログで確認（GitHub Deployments／Render ログ）。
3. **マイグレーション 0048 単独コミット** → `/readyz` の head が 0048。
4. **同意を送る web（signup／LINE）** → Vercel の反映を確認。
5. **同意必須化の backend** → 新規登録（メール・LINE）が通ること、`/readyz` が ok のこと。
- 順序を守る理由と各段の中身は `.agent-state/PROJECT_STATE.md` の「現在フェーズ」先頭。start.sh は alembic 失敗でも起動し、/health はスキーマを見ない。確認は必ず `/readyz`。

## 業者の退会時に消えるもの・残るもの
- **消すもの**（本人・運営の強制退会とも、退会と同じトランザクションで `services/operator_pii_erasure.py` が実行。冪等）: ①許可証画像・許可番号・会社名（表示は「退会済み業者」）②本人に紐づく事前申込（代表者名・所在地・担当者・電話・メール・許可番号・口座・メッセージ・申込時の IP など。文字列列は空文字、NULL 可の列は NULL）③本人が使った招待に控えたメールアドレス ④プロフィールの営業情報（対応エリア・得意カテゴリ・人数・営業時間・紹介文。非公開化）。
- **特定の仕方**: 本人の `operator_id`、または本人が使った招待コード（他の業者に紐づかないもの）だけ。**メールアドレスの一致では特定しない**（同じメール宛ての別の招待・申込を巻き込まないため）。
- **残すもの**: 取引・メッセージ・入札履歴・口コミ・キャンセル記録、運営の監査ログ（依頼者側の記録でもあり、紛争対応のため。保存期間は運営判断）。依頼者の取引画面では会社名が「退会済み業者」になる。
- 運営が手で消す必要はない。退会後に個人情報が残っていると報告を受けたら、`/admin` ではなく DB で該当業者の上記の列を確認する（値はチャット・ログに貼らない）。

## 管理者アカウントのパスワード再設定
- **メールの再設定（/password-reset）は管理者には効かない**（`role=admin` と、`ADMIN_EMAILS` に載る `role=user` は対象外。要求は同じ 202 を返し、メールは送られない。運営へは「管理者アカウントへの再設定要求」のアラートが出る）。乗っ取りの足がかりにさせないための仕様。
- **手順（別の管理者が手動で対応する）**:
  1. 管理者本人から、メール以外の経路（電話・対面・既知の別連絡先）で依頼を受け、本人であることを確かめる。再設定のアラートが届いていれば、その日時と依頼が符合するか見る。
  2. **別の管理者**が対応する（自分自身のパスワードを自分で復旧する経路は無い）。管理者が1人しか居ない場合は、アカウントの所有者（Render・DB の権限を持つ人）が DB で対応する。
  3. 管理画面（/admin/users）に他人のパスワードを変更する機能は無い [要確認: 実装を確認した範囲では見当たらない]。DB 上で該当ユーザーのパスワードハッシュを、アプリと同じ方式で作ったハッシュに更新する [推測: 運用スクリプトは未整備。整備するなら `scripts/` に値を表示しない形で用意する]。新しいパスワードは安全な経路で本人に渡し、初回ログイン後に本人が /mypage で変更する。
  4. 終わったら、依頼・本人確認の方法・対応者・日時を `docs/ops/incidents.md` ではなく運営の記録に残す（パスワードの値は残さない）。
- 降格（/admin/users の「管理者を解除」）で一般ユーザーにしても、`ADMIN_EMAILS` に載っているアドレスはログイン時に管理者へ戻り、自己再設定の対象外のままになる。メール再設定を使いたいだけなら、この方法は使えない。

## 利用規約・プライバシーポリシーを改定したとき（版数を同日に揃える）
改定の公開と**同じ日に、次の4か所を同じ日付（YYYY-MM-DD）へ上げる**（backend は、画面が送った版数が現行と食い違うと **409 `terms_version_outdated`** で新規登録を止める。版数を送らない旧画面は現行版として記録して通す。食い違いをログに残し、記録の意味が曖昧になる）。
1. backend `CURRENT_USER_TERMS_VERSION`（`backend/app/schemas_katadzuke.py`）＝依頼者の規約の版数。業者向けは `CURRENT_OPERATOR_TERMS_VERSION`（同ファイル。業者規約を改定したときだけ）。
2. web `USER_TERMS_VERSION`（`web/src/lib/line-consent.ts`）＝画面が送る版数（メール登録・LINE）。
3. `/terms`・`/privacy` の「最終改定」の日付（`web/src/app/terms/page.tsx`・`web/src/app/privacy/page.tsx`）。
4. 規約本文（`web/src/app/terms/TermsTabs.tsx`）。公開ページの表記ガード（`public-copy-guard.test.mts`）が「手数料」「査定」を許可しているのは TermsTabs だけなので、本文を直すときに許可リストの要否も見直す。
- **反映順**: 版数を変えるときは backend と web を**同じコミット（同じ push）**で出す。片方だけ先に出すと、出そろうまでの間、新規登録（メール・LINE）が 409 `terms_version_outdated` で止まる（画面は再読み込みを案内する）。
- 既存ユーザーには再同意を求めない（`agreed_terms_version` は NULL のまま・新規作成時だけ記録）。再同意が必要な改定かは運営判断（弁護士確認）。

## メール送信量（Brevo 無料枠 300 通/日）の見方
- アプリはプロセス内で当日（UTC）の送信数を数える（**概数**。再起動で 0 に戻り、複数台では台ごと。Brevo 側の実消費とは一致しない）。
- **250 通**に達したら運営アラート（LINE／メール）を1日に1回出す。本文は件数だけ。日付が変わって数え直したときに「日次枠が切り替わりました」の復旧通知で閉じる。
- **280 通を超えたら**、新着チャットのお知らせメール（`send_message_received`）だけを送らない（再設定・成約・キャンセルなど取引に必須のメールに枠を残すため）。チャット本文は画面・LINE で読めるので取引は止まらない。止めた日は backend ログに1回だけ記録される。
- アラートが出たら: ①実際の消費は Brevo の管理画面（Transactional → Statistics／ログ）で見る ②急増なら送信元（再設定の連打・問い合わせ・チャット通知）を backend ログで確認 ③常態的に超えるなら Brevo の有料プランへ（運営判断・金銭が動くためユーザー承認が要る）。UTC の日付切り替えは日本時間の 9:00 [要確認: Brevo 側の枠のリセット時刻]。
- 警告ログは 150・200・250・290 通でも出る（アラートは 250 通だけ）。

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
- **反映確認**: `/readyz` の `config.client_ip_relay` が `true`（値そのものは返らない）。実際に採用されたかは、backend ログの `client_ip_relay: 起動後初めて署名付き中継の利用者IPを採用しました…key_slot=N` という WARNING（`(scope, key_slot)` の組ごとに1回だけ出る。2回目 security review L-B により鍵を入れ替えるたびに新しい key_slot で再度出るようになった）で確認する。2回目以降は INFO へ格下げされるが、**本番では INFO は出力されない**（`app.*` のロガーにレベルが明示設定されておらず、デフォルトの WARNING 以上しか実際には出力されないため。2026-09-27 実測: 本番起動23回分のログを確認したが INFO ログが1件も見つからなかった。ロギング未設定の是正は別セッションで対応中）。したがって鍵入れ替え等の反映確認は必ず「初回 WARNING」で行うこと（2回目以降の INFO 採用ログを探しても見つからないのはログ保持期間の問題ではなく仕様である）。
- **鍵の妥当性チェック**: `/readyz` の `config.client_ip_relay_secrets_valid` が `false`（＝`degraded_config` に `client_ip_relay_secrets_valid` が含まれる）の場合、`CLIENT_IP_RELAY_SECRETS` に設定した候補のどれかが除外されている（短すぎる・既知のテストベクトル鍵/命名パターンと一致・使用文字が偏っている、のいずれか）。`client_ip_relay`（鍵が1本以上有効か）とは独立したフラグで、こちらが `false` でも有効な鍵が残っていれば中継自体は動く。原因の詳細（何番目の候補か・理由）は backend ログの `client_ip_relay: CLIENT_IP_RELAY_SECRETS の…番目の鍵が…` という ERROR（値・長さは出ない）で確認する。鍵は `python -c "import secrets; print(secrets.token_urlsafe(48))"` 等、十分にランダムな値で生成すること（コピペミスやドキュメント例示値をそのまま貼っていないか疑う）。
- **Vercel 側の環境変数設定**: `CLIENT_IP_RELAY_SECRET` は **Production 環境のみ**に設定し、**Sensitive（値をマスクする）** を有効にする。**Development / Preview のチェックは外す**（プレビューデプロイは URL を知っていれば誰でも触れるため、本番と同じ鍵を晒す経路になる）。本番以外の環境で試す必要がある場合も、**本番の鍵をそのまま使い回さない**（環境ごとに別の値にする。使い回すと、プレビュー環境の漏洩がそのまま本番の署名偽造に直結する）。
- **本番投入後の偽装耐性の確認手順（security review M-2・2回目レビューで是正。必ず中継の採用 WARNING を確認した「後」に行う）**: 中継が効いていない状態でこの手順を行うと**全利用者のログインが最大15分止まる**ため、順序を厳守すること。自宅などの固定回線で行い、**直前15分に同じ回線でログイン失敗をしていないこと**（社内など共有 NAT 配下や、MAP-E・DS-Lite 方式の家庭用回線（IPv4 アドレスを他の契約者と共有する）で行うと、同じ出口を使う他人も巻き添えで最大15分ログインできなくなる）。実行は**Git Bash** で行うこと（PowerShell 5.1 の `curl` は `Invoke-WebRequest` のエイリアスで `-4` 等のオプションの意味が異なり `/dev/null` も無いため、本手順のコマンド例はそのままでは動かない）。
  - **旧手順の欠陥（是正済み）**: 同じメールアドレスで20回送ると、IP軸より先にアカウント軸（5回/15分）の 429 に当たってしまい偽装の成否を誤判定する。また送り手から直接見えるのは backend の 401/429 ではなく、web（NextAuth）がそれを変換した後のリダイレクト先であり、旧手順はこの変換を経由しない前提で書かれていた。
  1. **事前確認（1）**: backend を起こしておく（`curl -4 https://<backend>/health` がすぐ200で返ることを確認。Render 無料枠はアイドルでスピンダウンしており、コールドスタート中に開始すると `expired` 等で「判定不能」になりやすい）。
  2. **事前確認（2）**: Render の環境変数に `RL_LOGIN_*` 系の上書きが無いこと（本手順は本番既定値＝IP軸20回・アカウント軸5回/15分を前提にしている）、および backend のインスタンスが1台であること（複数インスタンスだとインメモリのカウンタが分散し、20回失敗させても上限に達しないことがある）を確認する。
  3. **事前確認（3）**: 開始前に `curl -4 https://<backend>/api/v1/_diag/client-ip` を叩き、応答の `resolved_ip` を控える（事前確認（4）と事後確認で使う）。
  4. **事前確認（4）**: 開始の直前に、自分の実アカウントで**正しいパスワード**で1回ログインし（ブラウザでよいが、VPN・iCloud プライベートリレー等は切る。出口の IP が curl と変わるため）、その時刻に backend ログで `(scope=login, key_slot)` の初回採用 WARNING（`起動後初めて署名付き中継の利用者IPを採用しました`）が出ていること、**その `ip_net` が事前確認（3）の `resolved_ip` の /24 と一致すること**、`中継IPが Cloudflare の公開レンジです` の WARNING が出ていないことを確認する（最終 security review N-I1: 採用されていても x-real-ip が本人の IP でなければ、この手順を進めると全利用者が止まる）。WARNING が出ていない場合、直前の再デプロイ直後でなければ「既に採用済みのため出ない」だけの可能性があるので、Render を再起動して**事前確認（1）からやり直す**。それでも出ない・`ip_net` が一致しない場合はここで中止し、本手順を進めない。
  5. **22回すべて別々の・backend の入力検証を通る未登録メール**（例 `spoofcheck-01@example.com` から連番で `spoofcheck-22@example.com` まで）を使う（アカウント軸の429に先に当たらないようにするため）。送信は **`curl -4` に固定**する（デュアルスタック環境だと実IPがIPv4/IPv6で揺れ、偽装の成否と無関係な要因で結果がぶれるため。2026-09-27 時点では web・backend とも AAAA レコードが無く `-6` では接続できない。AAAA が出たら `-6` でもこの手順を行う）。
  6. CSRF トークンを取得する: `curl -4 -c jar https://<web>/api/auth/csrf`（応答 JSON の `csrfToken` を控える。以降の全リクエストで同じ `jar` を使い回す）。
  7. 1〜21回目は TEST-NET の値 A（例 `203.0.113.10`）を、22回目だけ値 B（例 `203.0.113.20`）を使い、`x-real-ip`・`x-forwarded-for`・`x-vercel-forwarded-for`・`forwarded` の4ヘッダすべてに同じ値を付けて、誤ったパスワードで `spoofcheck-NN@example.com`（NN は連番）宛に送信する:
    `curl -4 -b jar -o /dev/null -w '%{redirect_url}\n' -H 'x-real-ip: 203.0.113.10' -H 'x-forwarded-for: 203.0.113.10' -H 'x-vercel-forwarded-for: 203.0.113.10' -H 'forwarded: for=203.0.113.10' --data-urlencode csrfToken=<控えた値> --data-urlencode email=spoofcheck-NN@example.com --data-urlencode password=wrong-password https://<web>/api/auth/callback/user-credentials`
  8. **判定条件（満たさない場合は原因を断定せず「判定不能」とする）**: **1〜20回目は全て `code=credentials` であること**（途中に `server_error`・`MissingCSRF`・リダイレクト無し等が1回でも混じったら、その時点で「判定不能」）。**21回目（値 A のまま・新しいメール）は `code=rate_limited` であること**（内部対照: 自分の枠が20回に達したことを、間引かれるログに頼らず確かめる。`code=credentials` なら、途中で中継が落ちて失敗が別の枠に積まれた等の可能性があり「判定不能」。最終 security review N-L1）。**22回目（値 B）は `code=rate_limited`（偽装は効いていない＝想定どおり）か `code=credentials`（偽装できてしまっている）の2値だけで判定する**（それ以外の値・リダイレクト無しは「判定不能」。21回目・22回目は IP軸の事前判定で止まるので失敗として記録されず、巻き添えも増えない）。**判定不能になった場合**は原因を断定せず、15分待ってから（IP軸の窓が明けるのを待つ）、新しい連番のメールアドレス（例 `spoofcheck2-01@example.com` 〜）で最初からやり直す。`code=credentials` が出た場合の切り戻し（Vercel 側の `CLIENT_IP_RELAY_SECRET` を削除して再デプロイし hops 方式のみへ戻す）自体は即座に行ってよいが、「偽装できた」という原因の断定は、上記の判定条件と後述の事後確認を満たしてから行うこと。（`code=` の値の出典: web/src/auth.ts の `RateLimitedError`（`code="rate_limited"`。backend の429を変換）と NextAuth 標準の `CredentialsSignin`（`code="credentials"`）。値は今後の web 側の実装変更で変わりうるため、実施前に必ず該当ファイルを読んで確認すること。）
  9. **陽性対照（判定後に必ず行う）**: 別の回線（スマホのテザリング等、上記と異なる実IPになる経路）から1回、`spoofcheck-` シリーズとは別の未登録メールで誤ったパスワードを通常どおり送信し、`code=credentials` になることを確認する（直前の 429/`rate_limited` が「テスト用に共有した特定の枠」ではなく「自分のIPで正しく数えられていたこと」の裏付け。ここでも `code=rate_limited` になる場合、20回分の失敗が想定と違うバケット（例えばIP以外の軸）に乗っている疑いがあり、手順・実装の双方を疑うこと）。
  10. この手順による影響は**自分（と、共有 NAT・MAP-E・DS-Lite 経由の場合は同じ出口の他人）が最大15分ログインできなくなるだけ**（scope="login" の IP軸の窓が15分のため）。
  11. **事後確認（1）**: 終了後に `curl -4 https://<backend>/api/v1/_diag/client-ip` を再度叩き、`resolved_ip` が事前確認（4）で控えた値と同じであること（試験の途中で自分の IPv4 アドレスが変わっていないことの確認。変わっていた場合、21回目・22回目が別の枠に乗った可能性があり「判定不能」）。
  12. **事後確認（2）**: **開始の10分前〜終了の1分後**の Render ログに、`reason=expired`・`reason=bad_signature`、および鍵ありの場合の `absent`（「鍵が設定されているのに中継ヘッダの無い要求」）の WARNING が出ていないこと、同じ時間帯の Vercel の関数ログに `[client-ip-relay] 中継ヘッダを付けずに送信` が出ていないこと（出ていれば、その時間帯は中継が不安定だった可能性があり「判定不能」。これらの WARNING は60秒〜10分に1回に間引かれるため、範囲を開始前まで広げて見る）。
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
  6. **IPv6 の /64・/56・/48 の3段（`rate_limit_deps._IPV6_TIERS`）は「正規の IPv6 利用者がまだいない」前提の暫定運用**: 2026-09-27 に公開DNS（dns.google）へ照会し、`sokuri.vercel.app`・`sokuri-backend.onrender.com` とも AAAA レコードが無い（＝IPv6 の利用者も IPv4 で来ている）ことを確認済み。**web（Vercel）または backend のいずれかが AAAA を返すようになったら**、段ごとの倍率（/56 は2倍・/48 は8倍）と緊急停止スイッチの要否を見直すこと（詳細は `rate_limit_deps.py` の `_IPV6_TIERS` 定数近くのコメント参照）。

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

## 戻せる下限（ロールバック）
マイグレーション 0047・0048 を本番に入れた後は、それより前のコード（0047 を知らない版・0048 を知らない版）へ戻すと、alembic が知らないリビジョンで失敗し `/readyz` が degraded になる。**戻せる下限は、0047 を入れた段のコミット（0047 まで）／0048 を入れた段のコミット（0048 まで）**。戻すときはコードだけを戻さず、`downgrade` の要否を先に検討する（0048 の downgrade は2列を消す）。

## Brevo の日次の枠のお知らせ（情報）
250 通に達すると運営へ「情報」のお知らせが1通出る（障害ではないので**復旧連絡は出ない**）。数はプロセス内の概数で、再起動すると 0 に戻る（その場合 280 通での新着チャットメールの停止も働きにくい）。正確な残量は Brevo の管理画面で確認する。

## 段階反映の注意（中間段階の CI）
反映順の5段のうち、web が backend のソースを読んで版数・コード名の一致を確かめるテスト（`web/src/lib/line-consent.test.mts`）は、**backend に同意必須化が入る前の段（④）では必ず赤くなる**。本番のデプロイは成功するので、次の段（⑤）を出して CI が緑に戻り [RECOVERED] が届くことを確認する。段④と⑤の間は、開いたままの旧画面が新しい画面に切り替わるのを待つため10分以上あける。
