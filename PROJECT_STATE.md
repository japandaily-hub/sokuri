# PROJECT_STATE — カタヅケ クローズドβ

## 🚀 2026-07-18 [claude] 認証系レート制限を本番デプロイ完了（main=0f08b87・本番実測で全項目検証）
- **経緯**: security レビュー Medium-2（`/auth/login` に総当たり対策がない・パスワード変更/退会がパスワードオラクル）への対処。task_012a348f 消化。architect設計→backend実装→**security/qa 各2巡**→デプロイ。指摘は計16件（High 4・Medium 10・Low 多数）を全て是正。**pytest 330 passed**（既存218 + レート制限68 + 追加分。2回連続・順序変更でも安定）。
- **方式**: 新規依存ゼロの自前実装（slowapi 不採用＝「失敗のみカウント」「二軸同時判定」を素直に書けないため）。固定ウィンドウ・in-memory・プロセス内シングルトン。将来の水平スケールに備え `RateLimitStore` を Protocol 化（Redis 実装の追加＋生成1行差し替えで移行可能）。
- **制限値**: login/operator_login=失敗のみ（IP軸20・アカウント軸5 / 15分、成功でアカウント軸リセット）/ パスワード変更・退会=失敗のみ（user.id軸 5 / 15分）/ signup=全リクエスト（IP軸 10 / 1時間）/ line_exchange=全リクエスト（IP軸 20 / 15分。外部API2本を呼ぶ最も安いDoSベクタ）。**login の2軸は文言・窓長を完全同一**にし「アカウント軸で止まった＝そのメールは実在」という列挙オラクル化を防ぐ。
- **⚠️ 最重要の実測結果 — TRUSTED_PROXY_HOPS=3**: 本番の XFF 連鎖は **client(133.106.x) → Cloudflare(162.159.x/172.6x.x) → Render内部(10.x)** の3段。既定の hops=1 だと**末尾の Render 内部プライベートIPを掴み、全ユーザーが同一バケット＝認証全断**のモードに入る構成だった。実装した `is_private_or_loopback` によるIP軸スキップで全断自体は回避されていたが、IP軸の保護（signup/line_exchange は IP軸のみ）が実質無効になるため 3 に確定。**偽装耐性は実測で確認**: XFF に偽値を1個/3個 padding しても、重複XFFヘッダで送っても `resolved_ip` は実クライアントIPのまま（追記が必ず右側に積まれるため）。
- **⚠️ Render の仕様（運用に効く新発見）**: **render.yaml の envVars に新しいキーを追記して push しても、既に作成済みのサービスには同期されない**（Blueprint 再適用が必要）。TRUSTED_PROXY_HOPS=3 を render.yaml に書いてデプロイしても未設定のままだったことを `/api/v1/_diag/client-ip` で実測して確定（コード側の env 読み取りは正常であることを切り分け済み）。→ **本番で効かせる必要のある既定値は `backend/start.sh` で `${VAR:-default}` export する**方式に変更し、起動ログに実効値を出すようにした。**緊急停止スイッチ `RATE_LIMIT_ENABLED=false` も render.yaml では効かないため、Render dashboard で設定する必要がある**（この点を render.yaml/start.sh 双方に明記済み）。
- **レビューで潰した主な穴**: ①**重複XFFヘッダ**で `headers.get()` が先頭1件（=攻撃者の値）しか返さず右端保持が破れる（Starlette の実挙動を手元で実証 → `getlist()` 結合に修正） ②HMACキーに `jwt_secret` を直接流用し先頭12桁をログ出力→**ログ漏洩から JWT_SECRET のオフライン攻撃が成立**（用途ラベル付き派生鍵に変更） ③キャップ到達後に毎リクエスト1万要素ソート（CPU DoS）＋**退避が「最古＝ロックしたい被害者」優先**（sweep+ヒステリシス＋超過比率順に変更、RL_MAX_KEYS を10万へ） ④user/operator が同一メールでログインバケットを共有し**無認証5リクエストで相手をロックできるDoS**（QAが実際に再現。名前空間分離で是正） ⑤`compare_digest` が非ASCIIトークンで500（`/readyz` にも同じ問題があり同時修正） ⑥警告が「プロセス内1回きり」で**攻撃者が先回りして焼き切れる**（60秒スロットリングに統一）。
- **RFC6598 の落とし穴**: 内部IP判定に `100.64.0.0/10`（k8s/クラウドがコンテナ間ネットワークに最も一般的に使う帯）を追加。**Python 標準の `ipaddress.is_private` はこのレンジを False と判定する**ため、標準に委ねると全断検知に失敗する。逆に標準は RFC5737 文書用レンジ（203.0.113.x 等・テストで公開IPとして多用）を True にするため、そのまま使うとテストが壊れる。両方向に外れるので明示列挙が正解。
- **本番実証**: `/health` の commit で新版稼働を捕捉 → `/api/v1/_diag/client-ip` で IP解決4パターン検証 → **実際に 429 を発火**（5回401 → 6回目で 429 + `Retry-After: 897` + 設計どおりの日本語文言）→ **別アカウントは同一IPから正常ログイン200**（アカウント軸の分離を実証）→ ロック中アカウントは429継続 → テストアカウントは退会APIで削除。
- **申し送り**: (1) `/api/v1/_diag/client-ip` は DIAG_TOKEN 未設定時は無認証公開（`xff_raw`/`xff_count`/`resolved_ip` のみ。`peer`/`trusted_hops` はトークン必須）。**dashboard で DIAG_TOKEN を設定すれば閉じる**ので、実測が済んだ今は設定推奨。(2) CDN構成が変わって hops が合わなくなると、増えた場合は Cloudflare の公開IPを掴んで全断（プライベート判定に掛からない）、減った場合は偽装可能になる。`CF-Connecting-IP` 優先などの構成非依存化は未対応→チップ化。(3) ログイン時のタイミングサイドチャネル（ユーザー不在時はscryptを実行しないため応答時間差で列挙可能）は本タスク対象外→チップ化。

## 🚀 2026-07-18 [claude] /healthビルド識別子+intro_message連絡先ガード拡大を本番デプロイ完了（main=1980a20）
- **検証（新方式の初運用）**: /health 監視ログが旧→新ビルド切替を実捕捉（00:29 `{"status":"ok"}`＝旧版 → 00:30 `{"status":"ok","commit":"1980a20"}`＝新版稼働の直接証拠）。/readyz=`ready/db:ok/alembic 0013_user_profile_fields=expected_head`。GitHub Deployments API=3環境（Vercel Production/sokuuri production/Render sokuri-backend）すべて success・sha=1980a20。**以後のデプロイ検証は「curl /health → commit照合」が正**。
- 実装・レビュー詳細は下記エントリ参照。

## ✅ 2026-07-18 [claude] /healthビルド識別子+intro_message連絡先ガード拡大（デプロイ検証恒久化+勧誘対策の残面塞ぎ）
- **①/health に commit フィールド**: config.py Settings に `render_git_commit`（env RENDER_GIT_COMMIT、Render自動注入）を追加し、/health が `{"status":"ok","commit":<先頭7桁|None>}` を返す。**以後のデプロイ検証は curl /health の commit 照合一発**（GitHub Deployments API は補助に降格）。既存消費者（render.yaml healthCheckPath・.tools各スクリプト）はステータスコードのみ参照で後方互換確認済み。
- **②intro_message ガード**: 公開プロフィール（show_message=true で無認証表示）に出る intro_message の更新時に contains_contact_info を適用、検知時 422「自己紹介文に連絡先（電話番号・メールアドレス）やURLは記載できません。」（_get_or_create_profile 前で行作成すら発生しない配置）。OperatorApplication.message は全4露出経路が admin ゲート下と裏取りしガード対象外（将来 message を公開UIに出す際は要再ガード）。
- **レビュー**: security/qa 並列 → **双方承認・Critical/High/Medium 0**。qa Low 4件中2件（env経由の実読込テスト・intro_message省略時の非発動テスト）は即日取込、残2件（既存プロフィール多フィールド巻き戻しテスト・test_api.py の /health 手製モック乖離）は非対応でも可の設計負債メモ。
- **gate_status**: pytest=**225 passed** / ruff=変更7ファイルクリーン。
- **申し送り（security Info）**: ガード導入**前**に保存済みの intro_message には連絡先が残り得る（新規PUTのみ阻止のため）。本番DBの operator_profiles.intro_message 一度きりスキャン/バックフィル推奨。クローズドβで件数僅少のため優先度低。

## 🚀 2026-07-18 [claude] アカウント管理3機能を本番デプロイ完了（9ed9025・Render/Vercel外形+本番E2E実証）
- **main合流**: worktreeブランチ(05d366d)→main。合流中に並行pushを3回検出し都度fetch→merge（PROJECT_STATE両エントリ保持）。**最重要検出=並行の 0012_fix_status_defaults とマイグレーション番号衝突**（両者down_revision=0011の2ヘッド→本番alembic必敗）→ 0013_user_profile_fields へ付替・ScriptDirectoryで単一ヘッド機械検証→push(9ed9025)。マージ後ツリーで pytest 218 passed / tsc クリーン。
- **backendデプロイ実証**: /readyz のスキーマ自覚型遷移をライブ観測=①旧コード+旧スキーマ(ready/0012) → ②**degraded（DB=0013先行・コード期待=0012）** → ③新コード(ready・alembic_version=0013_user_profile_fields==expected_head)。新API `/users/me/profile` が404→**401**（ルート存在=新版稼働）。GitHub Deployments API=3環境success。
- **本番E2E（使い捨てアカウント・退会機能自体でクリーンアップ）**: kdz-e2e-verify-20260718@example.com を本番signup→/mypage/profile が redirect でなく**実フォーム描画**（新版証明）→姓名カナ・エリア保存=本番PostgreSQLの0013カラムに永続化実証（API読み戻し一致）→/mypage/withdraw で3チェック+PW→DELETE 200→完了パネル→**セッションnull・再ログイン401**（匿名化実証）。残存は匿名トムストン1行のみ（PIIなし）。
- **検証手法の学び**: /mypage/* は未認証curlでは認証ミドルウェアが307→/login を返すため、**無認証面から新旧ビルドを判別できない**（6分ポーリングは空振り。Location先の確認で判明）。認証必須ページのデプロイ検証= Deployments API のコミット単位success + 認証済みE2E が正。
- **申し送り**: レート制限（task_012a348f）未着手。私の合流後も並行セッションが成約時開示是正等を積んでおり、本push（本記録コミット）にはそれらも同乗する（下記エントリ参照・いずれもレビュー通過済）。

## ✅ 2026-07-18 [claude] 成約時開示の過大記載是正+privacy第2条収集表の実装整合（申し送り2件を推奨案aで完走）
- **方針**: ユーザー指示「推奨で完走」→ 案a=コピーを実装に整合。実装の真実=成約業者に渡るのは TransactionDetailOut の address（都道府県・市区町村・番地）+contact_email のみ（LINE専用ユーザーは is_placeholder_email 判定で「LINEにて連絡」に置換）。氏名・電話は業者向けの全経路（スキーマ・通知メール・LINE Push）に不使用 → 「**お名前や電話番号は業者に渡らない**」というより強い安心訴求へ転換。
- **変更（7ファイル・15箇所）**: ①成約時開示コピー7箇所=terms第5条/privacy第4条note/legal:196（「住所」→「詳細住所」+開示内容具体化）/page.tsx FAQ・trustカード/faq/landing Faq（デッドコード） ②privacy第2条 COLLECTED表を実収集に差し替え（ユーザー側の電話・郵便番号・数量/状態/メモ=未収集を削除。**業者申込フォームの実収集**=代表者名・担当者名・法人登録住所・電話・事業形態・対応エリア・カテゴリ・インボイス番号・**振込先口座(暗号化保存・bank_account_enc)** を明記）③レビュー指摘反映=assure帯「氏名・番地は伏せたまま」→「氏名・電話は渡りません」（番地は成約後開示のため不正確だった）・「連絡用のメールアドレス」表記統一・privacy第4条noteにLINE分岐追記・収集表の係り受け/業者パスワード明確化。
- **統合の注意点（main合流時の意味的競合を解決）**: 並行のアカウント管理機能（05d366d）で User に phone 等8列が追加され、/mypage/profile が氏名（姓・名・フリガナ）・電話番号・お住まいのエリアを任意収集するようになっていた。開示系の断定コピーは**マージ後ツリーで再検証し真のまま**（phone/氏名は users.py の本人向け /users/me のみで使用・TransactionDetailOut 不変・退会時匿名化）。収集表には「プロフィール情報（マイページでの任意入力）」行をマージコミット内で追加して再整合。
- **検証**: tsc クリーン（ブランチ+マージ後ツリー）/ worktreeレシピ SSR実測= / /faq /terms /privacy /legal 新文言描画・旧文言/表記ゆれ0件 / /contactフォームは未配線（fetch無し=電話収集なし）を確認。
- **レビュー**: security/qa並列 → **Critical/High/Medium 0**（securityは反証走査で全経路の非開示を確認: 通知メール notify.py・LINE Push line_notify.py・チャットMessageOut・レビュー・減額・adminゲート下のOperatorApplicationOut。qaのMedium1=assure帯矛盾は即応済・test_line_integration.py:718で「LINEにて連絡」も裏付け）。申し送り（任意）: 開示するメールアドレス文字列自体が氏名を含み得る／チャット自由記述はユーザー自身の自己開示経路／アクセス情報行のUA等はover-listing（アナリティクス導入時に実配線と突合推奨）。
- **🚀 本番デプロイ検証済み（2026-07-18 03:00 UTC・sha=692dbfd）**: 本是正はアカウント管理3機能のデプロイ記録push（上記エントリ）に同乗して本番反映。ユーザー承認「デプロイまで推奨で進めて」を受け、push前に `git fetch`→分岐チェック（origin/main が local main の祖先=巻き戻しなしを確認。既に同乗push済みだったため追加pushは不要）。GitHub Deployments API=**3環境すべて success**（Vercel Production 03:00:50Z / Render sokuri-backend 03:00:21Z / sokuuri production 02:59:30Z）。**本番HTML実測**= sokuri.vercel.app の / /terms /privacy /faq /legal で新コピー全描画（「氏名・電話は渡りません」「氏名・電話番号を業者に開示することはありません」「LINE連携のみの場合はLINEでの連絡のご案内」「振込先口座（暗号化して保存）」「プロフィール情報／マイページでの任意入力」）・**旧過大記載および旧収集表（本人確認情報・数量・状態・メモ）は5ルートすべて0件**。backend=/health 200・/readyz `ready`（alembic_version=0013_user_profile_fields==expected_head）。

## ✅ 2026-07-18 [claude] 全断障害の申し送り2件を完走（2a7a3d1・本番0012適用実証済み）
- **①status既定値の二重引用是正**: 0004の`server_default="'draft'"`等→裸文字列化+**0012_fix_status_defaults**新設（既存DBへSET DEFAULT+防御的UPDATE）。オフラインSQL実測で`DEFAULT 'draft'`正規化を確認（旧は`DEFAULT '''draft'''`=引用符込み7文字の壊れ既定値。cases/bids/transactions/reduction_requestsの4箇所・ORM明示値送信のため未発現だった休眠バグ）。
- **②/readyz診断のDIAG_TOKENゲート化**: 未設定=β運用（スキーマ未達時のみ公開・URLリダクト済）、設定時は`?token=`一致必須（hmac定数時間比較）。JWTゲートは「認証系が死ぬ障害時にこそ診断が要る」ため不採用（設計判断）。render.yamlにsync:false項目追加済。
- **検証**: pytest 141 passed / TestClientでゲート3態（無し/誤り=非表示・一致=表示）+リダクト実証 / **本番実測11:42 JST=`/readyz` ready・alembic_version=0012_fix_status_defaults==expected_head・login 401・health 200**。
- **運用メモ**: 正式リリース時はRenderダッシュボードで**DIAG_TOKEN**にランダム値を設定（閲覧は`/readyz?token=<値>`）。

## 🚀 2026-07-18 [claude] /examples 架空成約事例の景表法（優良誤認）是正 → mainへマージ+push（本番デプロイ・task_83692f21）
- **方針**: 実データ集計(a)はバックエンド未配線+βで対象データなし→不可、ページ非公開(c)は主要ナビ導線で損失大→**(b)モデルケース明示を厳格化**。ただし計測実績風統計（¥68,000/7.4件/78%/2.1日）は打消し表示では治癒しない判断で**撤去**し、事実ベースのサービス条件（¥0無料・選んだ1社だけ連絡・4都県・12カテゴリ）へ差し替え。
- **変更**: examples/page.tsx（h1「実際の成約事例」→「成約イメージ（モデルケース）」・多層打消し=ヒーロー注記+全カード「モデルケース」チップ+金額ラベル「（イメージ）」+**体験談ごと引用直下の近接注記**+グリッド末尾注記）/ examples.css（注記13.5px・チップ・引用注記スタイル）/ examples/layout.tsx（title/description をモデルケース明示に）/ SiteHeader・chrome（ナビ「成約事例」→「成約イメージ」）/ business/page.tsx（数値帯の「実績」誤称→aria-label「サービスの特徴」。数値は全て事実のため維持）。
- **レビュー**: security/qa並列 → **Critical/High 0**。共通Medium（体験談の近接打消し欠如・打消し12.5pxは主張数値比で小）→引用直下注記「※人物・セリフを含め、架空の利用イメージです」+13.5px化で対応済。**申し送り**: 打消し表示の最終的な十分性（消費者庁の打消し表示指針に照らした近接性・明瞭性）は法務観点の確認推奨。実データ蓄積後は STATS を実集計に差し替え可（examples/page.tsx 冒頭コメントに手順）。
- **統合の注意点（重要）**: fork元が4d7cbb3（上位3社是正）より古く、新設STATSの「上位3社/連絡が来るのは査定上位のみ」が**是正一掃後の再導入**になっていた→mainマージ後に「1社/連絡が来るのは、選んだ相手だけ」へ是正（49e56f6）。並行セッションのpush（35842bc=真因修正取り込み・2a7a3d1=申し送り完走）とは fetch→merge→push HEAD:main で衝突なく合流。
- **検証**: tsc クリーン / worktreeレシピ（junction+launch.json一時エントリ・復元済）でSSR実測=旧文言0件・全注記描画・computed style確認（12.5→13.5px反映・チップdashed 5枚+featuredバッジ）/ 本番=push（origin/main=c8e290b）後に sokuri.vercel.app/examples を外形確認（「モデルケース」描画・「実際の成約事例」「¥68,000」「上位3社」0件）。
- **メモリ**: katazuke-keihyoho-fictional-data-policy（架空データ掲載ポリシー4原則）を保存済。

## 🚀 2026-07-18 [claude] 入札メッセージガード+7/17コピー是正2件を本番デプロイ完了（main=35842bc・3環境success確認）
- **push前に分岐検出**: origin/main(f6dd33f=7月全断恒久修正+readyz診断+start.sh の3コミット)がローカルmain未取込で分岐していた。競合ファイルゼロを確認しマージ(35842bc)→マージ後ツリーで pytest 193 passed 再確認→push。**教訓: ローカルmainへの合流前に必ず fetch して origin/main との分岐を確認すること**（ホットフィックスが直接origin mainに載る運用があるため。今回そのままpushしていたら稼働中の障害修正を巻き戻すところだった）。
- **デプロイ検証（コミット単位の証拠）**: GitHub Deployments API（公開リポジトリのため無認証curlで可: `api.github.com/repos/japandaily-hub/sokuri/deployments`）で3環境すべて **success**・sha=35842bc（Vercel Production 02:37:49Z / sokuuri production 02:37:38Z / Render sokuri-backend 02:37:54Z）。gh CLI はこの環境に無いが不要だった。
- **外形実測**: トップHTML=「上位3社」0件・新コピー（「あなたが選んだ1社だけ」「写真・品目・地域」）描画確認。/health=200。/readyz=`{"status":"ready","db":"ok","alembic_version":"0011_line_user_id"=expected_head, 主要7テーブル全true}`（Render success の21秒後のプローブ＝新ビルド応答）。backendガード自体は認証必須のため無認証面に観測点が無く、Deployments API success が新版稼働の主証拠。
- **申し送り**: /health にビルド識別子（RENDER_GIT_COMMIT等）を露出させるとデプロイ検証が単純化する（チップ化）。7/17両エントリの「未push」注記は本デプロイで解消済み。intro_message拡大適用チップ(task_a86c49cc)は未着手。

## ✅ 2026-07-17 [claude] アカウント管理3機能（プロフィール更新/PW変更/退会）実装+profile/withdraw復元実配線（05d366d→main合流）
- **経緯**: task_74d343ae（redirect化していた /mypage/profile・/mypage/withdraw の復元用API）を architect設計→backend→frontend→security/qa並列レビューの規約フローで完遂。ブランチ=claude/musing-archimedes-f1622f。**ユーザー指示「推奨で完走」により main 合流・本番デプロイ実施（結果は最新デプロイ記録参照）**。
- **backend**: User拡張8列（family_name/given_name/カナ2列/phone/residence_area/deleted_at/password_changed_at・全nullable、name は表示用キャッシュとして「姓 名」同期）+ alembic 0013（当初0012で作成→並行pushされた 0012_fix_status_defaults との2ヘッド衝突をマージ時に検出し0013へ付替・単一ヘッド化を機械検証済）。新規 `endpoints/users.py`: GET/PUT `/users/me/profile`・PUT `/users/me/password`（成功時に新JWT返却）・DELETE `/users/me`。deps.py に失効ゲート2種（deleted_at 論理削除・iat<password_changed_at、SQLite tz-naive補正/秒切捨て比較）。JWT7日長命のため PW変更後の旧トークン即時失効は必須と判断し当初設計の[将来]を前倒し実装。
- **退会設計（architect決定）**: 進行中取引(pending/visiting)は409ブロック（自動キャンセルしない）・未成約case(draft/open/bidding)は自動cancelled化+address_detail除去・User行はPII匿名化（email=deleted-{id}@deleted.katazuke.internal、氏名/電話/LINE連携null化）・完了取引/メッセージ/レビューは業者側記録として保持・同一email再登録可。
- **frontend**: 2ページを git 5362359^ から復元し実配線（モック山田花子・偽装完了パネル全廃）。auth.ts jwt callback に trigger==="update" マージ追加→PW変更後 `update({accessToken})` でセッショントークン差替（忘れると全API401になる急所）・保存後 `update({name})` でヘッダー即時反映。LINE専用（has_password=false）はPW変更セクション説明化・退会はconfirmのみ。通知トグルはデータ源なしのため削除、退会画面は実件数表示+文言を実挙動に忠実化（「全データ完全削除」と言わない）。
- **レビュー**: security=Critical/High 0（IDOR/権限昇格/SQLi/XSS/CSRF/失効ゲート網羅を確認済み判定）。qa=合格。是正済み=退会トムストンメールの業者向け露出（is_placeholder_email に @deleted.katazuke.internal 追加+「退会済みユーザー」表示）・profile頁危険ゾーン文言矛盾・空白のみ氏名（str_strip_whitespace）・カナregex制御空白・auth.ts nameガード。**未対応（別タスク化）**: 認証系レート制限（/auth/login 総当たり・task_012a348f）・LINE専用退会のstep-up認証（設計割り切りとして許容）・メッセージ本文PII残存の告知（文言側で対応済み）。
- **gate_status**: pytest=**166 passed**（新規 test_account_api.py 25件）/ tsc=クリーン / build=成功 / **ローカルE2Eブラウザ実証**=登録→プロフィール保存（PUT200・name同期・エリア永続化）→PW変更（旧トークン失効+新トークンでリロード生存）→退会（3チェックゲート→DELETE200→完了パネル→セッションnull・再ログイン401）。
- **申し送り**: worktreeの .claude/launch.json はworktreeパスに書換済（gitignore対象・正典側は無変更）。web/.env.local を正典からコピーして使用。ブラウザペインの computer クリックは本セッションでも誤検知多発→JS .click() が確実（既知癖の再確認）。同一Tick内でチップclick→保存clickを連続実行するとReact state未反映で旧値保存になる（検証手法側の注意）。

## ✅ 2026-07-17 [claude] 入札メッセージに連絡先/URL検知ガード追加（脱プラットフォーム勧誘対策・security Lowフォローアップ）
- **背景**: BidCreateRequest.message（2000字）は選定前ユーザーに表示され、電話番号/URL/メール埋込みによる規約禁止の脱プラットフォーム勧誘の片方向経路だった（07-17「上位3社」是正時のLow申し送り(2)）。
- **実装**: 新規 `backend/app/services/message_guard.py`（純粋関数 `contains_contact_info`）を `create_bid` で呼び、検知時 422「入札メッセージに連絡先（電話番号・メールアドレス）やURLは記載できません。」（サイレント削除は不採用）。検知=NFKC正規化+Cf(ゼロ幅)除去→①電話: 区切り文字（ハイフン類/空白/./()/,、/:;・|_*）対応の候補抽出+「全連結」と「最大4グループ窓」の二段判定（10-11桁・先頭0・00始まり除外、+81=81始まり12桁も対象）②URL: https?://とwww.（裸ドメイン対象外）③メール: TLDをASCII英字2字以上に限定（「単価@1.5万円」誤検知回避）。3桁カンマ区切り金額（800,000-1,000,000円等）は事前に#置換で電話判定から除外。
- **レビュー往復（3ラウンド）**: 初版→qa High「カンマ/スラッシュ区切りで全回避」→区切り拡張+窓判定→qa **Critical**「窓判定が金額レンジの断片を橋渡し連結し1,000,000-1,200,000円等を誤422」（実運用頻出・追加テスト自身が見逃していた）→3桁カンマ無害化+00始まり除外→**security/qa双方承認**（ReDoSなし・退行なし・逆算探索でも新規誤検知なし）。既知の制限はdocstringに明文化（カナ表記/LINE ID/裸ドメイン/3桁カンマ偽装は原理的or意図的に非検知、先頭0の10-11桁見積番号等は過剰検知許容）。
- **gate_status**: pytest=**193 passed**（+30、単体+API 422/201+422時DB無副作用アサート）/ ruff=変更4ファイルクリーン。
- **申し送り**: intro_message等の他フィールドへの拡大適用はチップ化済（task_a86c49cc）。**未push**: mainへローカルマージのみ（push=Vercel/Render自動デプロイはユーザー承認事項。7/17のコピー是正3cc03e8も未デプロイのまま積まれている）。
## ✅ 2026-07-17 [claude] 「写真と品目のみ」過小記載是正（security Low申し送りフォローアップ）— 査定段階の開示範囲コピーを実装に整合
- **方針**: 実装が正=CaseMaskedOut（backend/app/schemas_katadzuke.py:164-181）は査定段階で purpose/prefecture/city/housing_type/floor_plan/floor_number/has_elevator/ai_summary も業者に開示。マーケ面は統一表現「写真・品目・地域（都道府県・市区町村）・住居情報などの出品内容のみ」、法的文書（terms第5条・privacy第4条note）は利用目的・住居情報内訳・AI要約まで完全列挙（スキーマと1対1一致をqa/securityが照合済）。「氏名・電話・詳細住所は成約1社にのみ開示」の核心はタスク指示どおり維持。
- **変更**: 8ファイル11箇所・文字列リテラルのみ（page.tsx×4=FAQ/assure帯「氏名・番地は伏せたまま」/オークション手順1/trustカード、faq:55、terms第4・5条、privacy第4条note、landing/Faq:19=未importデッドコード予防、create:280確認画面、business:50構成文）。タスク指定5箇所に加えgrep発見の同種3箇所（privacy第4条・terms第4条・business:50）も是正。「写真と品目」残存4箇所（complete:98/business:44/page:32/photo-guide:87）は排他主張なしの意図的残置。docs/design_handoff_katazuke/ は対象外。
- **検証**: tsc クリーン / worktreeレシピ（junction+launch.json一時エントリ3102・復元済）でSSR HTML実測= / /faq /terms /privacy /business 旧文言0件・新文言描画確認。/createは認証ガード307のためソース+tsc（ヒントバナーは確認ステップ限定client）。
- **レビュー**: security/qa並列 → qaがHigh1（create:280 直上の確認行に「利用目的」表示があるのに列挙から脱落+「のみ」排他）・Medium1（business:50 統一表現逸脱）→即修正→再レビュー**合格**。securityは「是正は正確・新規虚偽なし・AI要約の生成入力にも非開示項目混入なし（cases.py:138-143）・マージ可」。
- **⚠️重要検出（ユーザー判断事項・コード未変更）**: 核心コピー「氏名・電話番号・詳細住所は成約業者にのみ開示」自体が**過大記載**と判明。TransactionDetailOut（schemas:231-241）は address（都道府県・市区町村・番地）+contact_email のみで氏名・電話を含まず、**Userモデルに電話番号カラム自体が無い**（user.py:26はnameのみ）。該当=terms:81/privacy:83/page.tsx:26/landing Faq:19（legal:196「成約後に必要な情報が開示されます」は抽象表現で正確）。是正方向=(a)コピーを実装に合わせる か (b)実装に氏名開示+電話収集を追加、はユーザー判断→チップ化+メモリ katazuke-transaction-disclosure-scope。privacy第2条の収集項目表の乖離（電話番号・郵便番号・数量/状態/メモは未収集）も別チップ化。
- **未push**: mainへローカルマージのみ。push（=Vercel自動デプロイ）はユーザー承認事項のため未実施。

## ✅ 2026-07-17 [claude] 「上位3社」コピー不一致是正（task_7de2d145）— コピーを実装に合わせ全面書き換え
- **方針**: ユーザー選択=(a)コピー修正（AskUserQuestionで確認済）。実装が正: bids.py=全入札を所有ユーザーに提示→任意の1社を選択、transactions.py=成約後に選ばれた1社のみ連絡先開示。top-3制限・成約前チャットは実装に存在しない。新コピーの核=「連絡が来るのは、あなたが選んだ1社だけ（選ぶまで連絡先非開示・選ばなかった業者には自動お断り）」＝旧コピーより強い安心訴求で整合。
- **変更**: web/src 14ファイル・文字列リテラルのみ21箇所（page.tsx×7 / layout.tsx SEO×3 / business/page.tsx×6（STATS「上位/3社」→「下見/0回」含む）/ operator入札モーダル / create/complete×2 / legal特商法 / examples体験談×2（bidCountと数字整合）/ faq / terms利用規約×2 / landing 4コンポーネント）。`docs/design_handoff_katazuke/` は静的設計資料のため意図的に残置。
- **検証**: ワークツリーdev実機（node_modulesジャンクション+port3102）で8ルートのSSR HTML実測=「上位3社」0件・新コピー描画・meta description反映。qa側で tsc クリーン+next build 41ルート成功。
- **レビュー**: security/qa並列 → **Critical/High/Medium 0**。Low申し送り: (1)「査定段階は写真と品目のみ」は過小記載（実際は都道府県・市区町村・間取り等もCaseMaskedOutで業者に開示。terms:81/page.tsx:219,287/faq:55/landing Faq:19→チップ化） (2)入札message(2000字)が選択前の業者→ユーザー片方向経路＝連絡先埋込み勧誘の抜け道、サーバー側パターン検知推奨（→チップ化） (3)landing/{ServiceIntro,Features,Faq,Comparison}は現在どのルートからも未import（デッドコード。修正済みなので将来復活しても旧文言は出ない）。
- **未push**: mainへローカルマージのみ。push（=Vercel/Render自動デプロイ）はユーザー承認事項のため未実施。※正本チェックアウトは feat/design-handoff-katazuke（42956c8=state記録のみ、main未反映）に居る点に注意。

## 🚀 2026-07-16 [claude] 導線監査是正一式を本番デプロイ完了（main=d8d0013）+ security/QAレビュー通過
- **デプロイ**: 下記ウォークスルー是正（3コミット）+レビュー是正（d7d63cf）を2段でmainへマージ（639e6a0→d8d0013）。Vercel=反映確認済み（/login「ログイン | カタヅケ」・/company 二重タイトル解消・/business /faq 新title、いずれも本番HTML実測）。Render=autoDeploy:true・/health=200・/readyz=`{"db":"ok"}`（**DBはユーザーが差し替え済みで全快**。Codexの起動チェーン修正fab45c2/9622e61もmain反映済み）。
- **security-reviewer（Medium 1→修正済d7d63cf）**: 無認証の公開プロフィール `/vendors/{id}` に (a)業者が顧客について書いたレビューが混入（reviewer_type未フィルタ） (b)内部transaction_idが露出 → 顧客→業者レビューのみ+PublicReviewOut（最小フィールド）に限定、回帰テスト追加。IDOR/クライアントゲート誤用/redirect系は問題なし判定。
- **qa-reviewer（Medium 1・Low 5→全て修正済d7d63cf）**: vendor_status取得中の入札フォームチラつき→3状態化（取得中=Spinner）。日本語403のテストアサーション追加・孤児CSS削除・layoutスタイル統一・無効style除去。
- **追加検出（レビュー過程）**: `/admin/cell-density` の生SQL `datetime('now','-30 days')` がSQLite専用で**本番PostgreSQLでは500になる**バグ→SQLAlchemy式へ書換（d7d63cf）。※ローカルの「案件数1」表示は正しい集計だった（open/biddingのみ対象のため）。
- **gate_status**: pytest=**141 passed** / tsc=クリーン / build=41ルート / 本番外形=Vercel4ページ+Render health/readyz実測。
- **申し送り**: /examples架空事例(task_83692f21)・「上位3社」コピー不一致(task_7de2d145)・profile/withdraw復元用API(task_74d343ae)はタスクチップ化済み。無料PG30日期限は再発するため運用注意（[[render-free-postgres-30day-expiry]]相当の恒久策検討推奨）。

## ✅ 2026-07-16 [claude] 新デザイン全画面ウォークスルー+導線監査→P0導線欠落4件を含む10件是正（ローカル実機検証済）
- **背景**: ユーザー指示「トップ以外の全画面（業者/admin/査定フロー等）をプレビュー確認し、デザイン/導線を全方向から再確認→修正→デプロイ完走」。ローカル実機（backend=run_local_e2e.py:8000 + web dev:3100、seed=4案件4状態: 入札選択待ち/入札なし/取引中(減額申請中)/完了評価済み + active/pending業者 + admin）で全41ルートを巡回。入札→落札→チャット双方向→減額申請→完了→評価投稿の全サイクルをUI実操作で検証、コンソールエラー0・モバイル375px横はみ出し0。
- **P0是正（導線の孤児ページ解消）**: ①`/chat/[id]`・`/schedule`にユーザー側から到達する導線がゼロ→`/cases/[id]`成約パネルに「業者とチャット（未読数付き）」「訪問日程を調整する」「訪問予定表示」を追加 ②`/operator/chat/[id]`も業者側導線ゼロ→`/operator/transactions/[id]`に「お客様とチャット（日程調整）」を追加。
- **P0級UX是正**: pending業者に通常の入札フォームが表示され、送信すると生英語「Account not yet approved.」が露出→(a)`operator/cases/[id]`でvendor_status取得(getOperatorProfile)しactive以外は承認待ち案内に差し替え (b)backend deps.pyの403 detail 3箇所を日本語化。
- **P1是正**: ③`/cases`・`/cases/[id]`がAppHeader無し=ナビ行き止まり（SiteChrome H-1コメントの意図が未実装だった）→AppHeader追加 ④`/mypage/profile`(モック山田花子・全フォーム未配線)・`/mypage/withdraw`(偽の削除完了デモ)が本番ルートに露出→ユーザー情報更新/削除APIが実装されるまで`/mypage`へredirect化（旧実装はgit履歴参照） ⑤backend `GET /vendors/{id}`がプロフィール行未作成の業者を一律404（公開デフォルトtrueと矛盾・チャット「プロフィールを見る」が壊れる）→行なし=既定公開の仮想プロフィール扱いに修正+回帰テスト追加（suspendedは404化）。
- **P2是正**: ⑥terms/privacy/legal/companyのtitle「…| カタヅケ | カタヅケ」二重化解消 ⑦business/faq/examples/contact/unsubscribe/login/signup/verify-email/password-reset にmetadata layout新設（client pageでtitle欠落だった9ルート） ⑧モーダル閉時がopacity:0のみで支援技術から到達可能→visibility切替をCSSに追加（operator-shared/dashboard） ⑨時限失敗テスト修正（schedule confirmの固定日2026-07-15→動的未来日）。
- **gate_status**: backend pytest=**140 passed** / web tsc=クリーン / web build=**成功（41ルート）** / 修正は全てローカル実機で表示・動作確認済み（dev HMR環境のためスクショ不可＝CSSTransition凍結・read_page/computed styleで検証）。
- **ユーザー判断待ち（コード未変更・報告のみ）**: (A)`/examples`の成約事例・統計値（¥68,000/7.4件/78%/2.1日等）が架空のまま実データ風に表示＝景表法（優良誤認）リスク。デモである旨の注記か実データ差し替えを推奨 (B)`/business`・トップ・ダッシュボードモーダル等の「上位3社だけが交渉」コピーは実装（ユーザーが全入札から1社選択・3社制限なし）と不一致 (C)ユーザー側`/cases/[id]`の確認がwindow.confirmのまま（業者側はB-2でブランドモーダル化済み・機能は正常）。
- **その他**: `.claude/launch.json`の旧C:\sokuriパスを現リポジトリへ修正（3エントリ）。seedスクリプトはscratchpad（セッション限り）。admin cell-densityの案件数集計が直近作成4件中1件しか数えていない疑い（P2・未調査）。

## ✅ 2026-07-16 Renderバックエンド全断→復旧（HTTP層）: fab45c2をmainへデプロイ済み・残るはDB差し替えのみ
- **18:38 JST 本番実証**: e77f6ab(=fab45c2 cherry-pick)デプロイ後、`/health`=200復活（7/6以来初）。`/readyz`=503 `{"db":"unreachable"}`で**DB断を外形確定**。x-render-routingヘッダも`hibernate-wake-error`（wake失敗=起動時クラッシュ）を捕獲済みで診断と完全一致。
- **残るユーザー操作（DBのみ・下記詳細は次節）**: Renderダッシュボード→sokuri-dbのExpired確認→(データ要)有料化して救出7/26頃まで／(不要)新規無料DB作成→sokuri-backendのDATABASE_URL差し替え→再起動でalembicが新規スキーマ構築→`/readyz`が`ready`になれば全快。

## 🔬 2026-07-16 Renderバックエンド無応答: 根本原因診断完了+コード側修正済み（fab45c2・デプロイ待ち）
- **確定(確度~90%)**: 無応答の直接原因は「uvicornが一度もポートbindしていない」。start.shが`set -e`で`alembic upgrade head`成功をuvicorn起動の前提にしており、DB接続不能→alembic失敗(asyncpgデフォルト60sタイムアウト)→コンテナ即死→再起動ループ。RenderのLBは常時TLS終端するため「TCP/TLS成立・HTTP無応答」はインスタンス不在の典型症状(2026-07-16の再プローブでも継続確認: 存在しないサービス=即404に対し本件=無限ハング)。
- **最有力トリガー(40%)**: **Render無料PostgreSQLは作成後30日で期限切れ→接続不能**(render.com/docs/free。「90日無期限」という旧render.yamlコメントは誤り)。DB作成~6/12なら期限切れ~7/12。**+14日猶予後(~7/26)にデータごと削除**。次点: Blueprint初回デプロイがsync:false変数入力待ちで未開始(20%)/DATABASE_URL未注入→localhostフォールバック(12%)/本番起動ガード発動(8%・発動時はログに「CRITICAL 起動中断:」が出る)。
- **コード修正済み(fab45c2)**: ①start.sh=alembic失敗でもuvicorn起動(degraded) ②alembic接続タイムアウト3点セット ③実行時エンジンにもtimeout ④**/readyz新設**(=デプロイ後、/health 200+/readyz 503なら「DB断」と外形判別可能) ⑤localhostフォールバック時CRITICALログ ⑥render.yamlコメント訂正 ⑦pyproject packages find化。pytest 138緑(1 failedは既存=task_21185600)。
- **残るユーザー操作**: (1)Renderダッシュボード→sokuri-dbページで**Expired表示と作成日**確認(期限切れなら:データ要るなら~7/26までに有料化してエクスポート/不要なら新規無料DB作成+DATABASE_URL差し替え) (2)sokuri-backend→Deploysタブで"Live"到達履歴有無(履歴ゼロ=sync:false入力待ち) (3)fab45c2をmainへ反映しRender再デプロイ(このデプロイ自体が最強の診断: /health復活+/readyzでDB状態が外から見える)。※ログ保持7日のため7/6当時のログは消失済み。
- **⚠️30日おきに再発する**: 無料PG継続なら「期限前に再作成+URL差し替え」の運用が必要。恒久策=DB有料化($7/mo~)か外部マネージドPG(Neon/Supabase無料枠)移行。

## 🔴 2026-07-06 本番デプロイ後点検: Renderバックエンドが応答なし（→2026-07-16診断完了・上記参照）
- **状況**: `feat/design-handoff-katazuke`→`main`マージ+push、Vercel(`sokuri.vercel.app`)・Render(`sokuri-backend.onrender.com`)へ初回デプロイ実施済み(いずれもuser承認下で進行)。Vercel側は`vercel inspect`で該当コミットのビルドが`Ready`(全ルート含むbuild成功、`/operator/login`等ローカルbuildと同一サイズで一致確認)。
- **問題**: `https://sokuri-backend.onrender.com/health` が**複数回・累計10分超の試行で一度も正常応答なし**(1回目=503(420秒後)、以降3回=完全タイムアウト(60秒/150秒/45秒、TCP/TLS確立はできるがHTTPレスポンスなし)。DNS解決・TCP/TLS接続自体は正常("Established connection"まで到達)なため、ネットワーク疎通ではなくアプリ/コンテナ側の起動停滞の可能性が高い。
- **推定原因(要Renderダッシュボードでのログ確認・[推測])**: このBlueprintは今回が初回デプロイで、Web Service(Docker/free)+Postgres(free)とも新規プロビジョニング。(a)初回Docker起動+`alembic upgrade head`(全テーブル新規作成)+freeプランDBの初回接続が重なり異常に長い、または(b) `sync:false`指定の必須env var(`GOOGLE_API_KEY`/`BREVO_API_KEY`/`APP_ENCRYPTION_KEY`)がRenderダッシュボード側で未入力のまま起動しクラッシュループしている可能性。Render CLI/API未接続のためログを直接確認できず、断定不可。
- **次にすべきこと**: ユーザーがRenderダッシュボード(sokuri-backendサービス→Logsタブ)で実際の起動ログ・crashの有無を確認。上記3つのsync:false env varが入力済みか要確認。
- **影響**: バックエンドが応答しない間、フロント(Vercel)の認証・データ取得系機能は全て機能しない状態(表示のみのページは影響なし)。

## ✅ 2026-07-06 業者/admin/エラー系導線 デザイン統一パッチ適用（zip指示書・strategy-agents Leader・/loop自走）
- **入力**: ユーザー提供zip`design_handoff_operator_flow_fixes/`（2026-07-05導線別レビューB/C/A計10件の是正コード。README.md=指示書）。
- **適用**: 新規5+変更16=21ファイルを`web/src`へ適用（commit `1ebdcad`）。パッチが想定していた`app/cases/cases.css`が正典に未実装だったため、`operator-shared.css`に`.lot-card`/`.status-chip`/`.modal-overlay`等の実体スタイルを自己完結で追加。CSSコメント誤爆（`.modal-*/`→コメント早期終了でcssnano全体崩壊）も検出・修正。
- **内容**: OperatorHeader共通化(B-5)・業者ログイン/登録のAuthBar統一(B-3)・案件/取引画面のkatazukeトークン移植(B-1)・キャンセル/減額のwindow.confirm→ブランドモーダル化(B-2)・通知ベル誤リンク修正(B-4、以前は`/notifications`でmiddlewareに弾かれていた)・SiteChrome BARE_PREFIXESに`/cases`・`/admin`追加(C-1)・error.tsxを404意匠に統一(A-1)・unsubscribe再スキン(A-2)・analyzing/condition孤立レガシーをredirect化(A-3)。
- **検証フロー**: frontend(適用+tsc/build green・41ルート)→security-reviewer(Critical/High無し)∥qa-reviewer(独立tsc/build再実行込み・Medium1件検出=モーダルにaria-modal/role/フォーカス制御が皆無)→frontend是正(commit `3022a7b`)→tsc/build再green。
- **ブラウザ実機確認**（backend=`run_local_e2e.py`:8000+web=本番ビルド:3100、e2e-op/e2e-admin seedアカウント。`.claude/launch.json`に`katazuke-backend`エントリ追加）: signup/login/dashboard/cases(空状態)/transactions一覧・詳細/admin(bare chrome確認・LINEドック等マーケchrome非表示)/unsubscribe(`.done-circle`緑確認)/analyzing→condition→create→loginリダイレクト連鎖/920px hamburger開閉、いずれもconsole・serverエラー0。**未確認(seedデータにアクティブ案件・未完了取引が無いため)**: `/operator/cases/[id]`の入札送信・`/operator/transactions/[id]`のキャンセル/減額モーダルの実クリック・`error.tsx`の強制発火表示。いずれもコードレビュー(security+qa+リーダー自身の読解)では問題なしと確認済み。
- **フォローアップ（本パッチのスコープ外・spawn_task `task_ab009ee7`）**: `OperatorHeader`の「ログアウト」リンクがトークンを破棄せず`/operator/login`へ遷移するのみ（本パッチ以前から存在する既存不具合）。
- **gate_status**: build=GREEN(41ルート) / typecheck=GREEN / security=レビュー済（Critical/High=0、Low3件は既存事項） / QA=レビュー済（Medium是正済、Low2件は次点） / ブラウザ実機=12項目中9項目確認・3項目はコードレビューのみ
- **未push**（ブランチ`feat/design-handoff-katazuke`、`83e60cd`→`1ebdcad`→`3022a7b`）。無関係な既存未追跡ファイル(`.kdz-status.txt`/`kdz-commit.ps1`/`test-room.jpg`)は不変。mainマージ・デプロイ・pushはユーザー承認事項のため未実施。

## 🎨 2026-06-27〜 デザインハンドオフ実装（/loop 自走・strategy-agents Leader）
- **ブランチ**: `feat/design-handoff-katazuke`（main=本番には未マージ。デプロイはユーザー承認操作のため自動実行しない）
- **タスク**: 新デザインハンドオフ（`docs/design_handoff_katazuke/` 33画面・高忠実度）を `web/` にピクセル忠実実装。DoD正本=リポジトリ直下 `KATAZUKE_REDESIGN_PLAN.md`。
- **正本の確定**: 稼働ファイルは **C:\sokuri**。OneDrive側（…\Projects\ソクウリ）は**ソース脱水の空殻（.tsx 0件・package.json無）＝編集禁止**。
- **完了（イテレーション1・基盤）**:
  - `src/app/katazuke.css`（ハンドオフCSS移植）+ `globals.css`（layer順宣言→`@import ... layer(components)`）+ `tailwind.config.ts`（kdz-* トークン・container無効化）+ フォント（Zen Kaku/Noto Sans を @import url 実行時ロード）
  - 共通部品 `src/components/kdz/`（Icons / interactions / SiteHeader / chrome / SiteChrome / Logo）
  - `src/app/layout.tsx`（薄シェル化・共通クロム・SEO維持）+ `src/app/page.tsx`（**トップLP全16セクション再実装**）
  - **検証**: `npx tsc --noEmit` クリーン / `npm run build` 緑（23ルート・lint通過）。**視覚QAは未実施（次イテレーションで実施）**。
- **完了（イテレーション2）**: `/login` 再スキン（commit 8331765）。認証/フォーム共通基盤を新設: `katazuke-pages.css`（auth-bar/auth-card/field/btn-line-auth/モーダル/トースト）+ `components/kdz/auth.tsx`（AuthBar/Field/PasswordField/LineAuthButton/TrustRow）。既存 signIn 配線維持。
- **QA所見（重要）**: ①ローカル `next start`/`dev` で NextAuth が動くには `web/.env.local` に `AUTH_SECRET` 必須（追加済・gitignore）。②**preview_screenshot は本アプリで networkidle に達せず常時タイムアウト**（dev=HMR websocket / prod=フォントCDN待ち。ページ自体はSSR200・markup健全・console errorなし）。視覚QAはユーザーがブラウザで `localhost:3100`（`.claude/launch.json` の katazuke-web）を直接確認する方式に切替。プレビュー起動コマンドは `npm --prefix C:\sokuri\web run start -- -p 3100`。
- **完了（イテレーション3・Workflow並列）**: コンテンツ/法務6ページ（terms/privacy/legal/company/contact/404）を Workflow `wr9anbg0v`（6エージェント並列）で実装、統合build緑(25ルート)・commit `50bfa69`。各ページは SiteChrome配下でmainのみ描画、固有CSSは各ルートに co-located。
- 🔴 **リリースブロッカー（spawn task task_b62c0b43）**: `/company`・`/legal` にデザインモック由来の**架空事業者情報**（古物商許可 第303291234号・代表者 山村大輔・資本金8000万・実績数値 等）。公開前に実値/明示プレースホルダへ差替必須。**未デプロイのブランチなので本番影響なし**。
- **次アクション（loop P1）**: ①content残り（faq/photo-guide/examples）+ 単純auth（verify-email/password-reset/create-complete）を Workflow 並列 → ②複雑な既存配線ページ（signup 3step/create 多step/result）を個別に丁寧に再スキン（既存wiring維持）→ ③ユーザーアプリ/業者クラスタ。
- **既知の要対応**: 実画像アセット未投入＝`PhImg` プレースホルダ（ユーザー決定: 進行）。LINE認証=未実装（準備中トースト）。contactフォーム送信=未配線（デモ文言）。
- **完了（イテレーション4・Workflow w97tixiok）**: クラスタ2=faq/photo-guide/examples/verify-email/password-reset/create-complete、build緑(31ルート)・commit `2755886`。
- **進行中（イテレーション5・Workflow wzqnc87jc）**: クラスタ3=business + mypage/applications/notifications/mypage-profile/mypage-withdraw（bareクロム・AppHeader統一・commit `44cb307`で基盤先行）。
- 補足: ログイン後アプリ画面は `AppHeader`（ロゴ+通知ベル）に統一。`SiteChrome` BARE_PREFIXES に /mypage・/applications・/notifications・/business 追加。
- **次アクション（loop P1）**: クラスタ3完了→build検証→コミット。次クラスタ4=動的/対話系（vendors/[id]・chat/[id]・schedule・review・operator-chat・operator-profile）。**最後に複雑な既存配線ページ（signup 3step・create 多step・result・operator dashboard）を既存wiring維持で個別再スキン**。
- **完了（イテレーション5・Workflow wzqnc87jc）**: クラスタ3=business/mypage/applications/notifications/profile/withdraw、build緑(37ルート)・commit `beb69d7`。business.css のコメント内 `.faq-*` +スラッシュが `*/` を形成→cssnano崩れを修正。
- **進行中（イテレーション6・Workflow wec8yvvzf）**: クラスタ4=vendors/[id]・chat/[id]・schedule・review（bareクロム拡張・commit先行）。※初回は自作スクリプトのテンプレート文字列に `*/` 混入で失敗→array.join方式で再投入。
- **次アクション（loop P1）**: クラスタ4完了→build→コミット。**残=複雑な既存配線ページのみ: signup(3step)/create(多step)/result(3状態)/operator dashboard + operator-chat/operator-profile**。これらは既存の signIn/katadzuke-api/middleware 配線を読み込み**維持したまま**個別丁寧に再スキン（Workflow agentに既存ファイルを渡すか、リーダー直実装）。
- **完了（イテレーション6-8）**: クラスタ4(vendors/chat/schedule/review・commit `379c7e5`)＋クラスタ5(operator dashboard/chat/profile・commit `ae7336f`)＋**signup 3ステップ再スキン**(既存signupUser→signIn配線維持・commit `709e628`)。共有フローCSS(flow-header/footer/form-card/pw-strength)を katazuke-pages.css に集約。
- **次アクション（loop P1）**: **残2のみ＝/create と /result**（最も複雑な既存配線）。/create は useToken/uploadCasePhoto/createCase→/cases/{id} 配線を読み込み**維持**しつつ新デザインのflow-header/footer/form-cardで再スキン。/result は既存セッション/状態配線を維持。リーダー直実装で慎重に（並列しない）。
- **✅ 完了（イテレーション9-10）**: create(commit 67c9f8b)・result(業者入札選択・旧AssetWise置換・commit e474612)再スキン → **全33ページ新デザイン実装完了**。security-reviewer + qa-reviewer 並列レビュー実施、指摘是正(commit 4817cd9): オープンリダイレクト/虚偽成功断定/BlobURLリーク/business.cssスコープ/メール検証/aria。
- **gate_status**: build=GREEN(41ルート) / typecheck=GREEN / **security=レビュー済(Critical/High=0, Medium 1件是正)** / **QA=レビュー済(blocker是正)** / 全33ページ=**33完了** / visualQA=ローカル(localhost:3100)でユーザー確認可
- **🏁 デザイン実装タスク完了（/loop 停止）**。リリース前のユーザー対応項目は KATAZUKE_REDESIGN_PLAN.md 末尾「✅全33ページ完了」節を参照（架空事業者情報の差替=task_b62c0b43 / 実画像 / 新ページのバックエンド配線 / LINE認証 / デプロイ）。

## 🔐 2026-07-02〜03 ウォークスルー是正＋本番セキュリティ堅牢化（/loop 自走・strategy-agents）
- **commit `c24549e`**: ウォークスルーP0/P1是正＋LINE統合の一式（65ファイル）を保全コミット。P0-1(Failed to fetch日本語化)/P0-2(認証ガード8パス)/P1-1(license必須+vendor_status 3値)/P1-2(LINEログイン+落札落選日程通知)/P1-3(チャット・日程・プロフィール実配線)/P1-4(規約同意サーバー検証)。詳細= `docs/reviews/walkthrough_review_2026-07-02.md` とメモリ katazuke-ux-walkthrough-p0-issues。
- **commit `06abd12`**: 既存の別課題2件をクローズ。①CORS `allow_origins=["*"]` 廃止→ALLOWED_ORIGINS設定制（危険トークン"*"/null除外・末尾スラッシュ正規化・productionフォールバックはFRONTEND_BASE_URLのみ）②本番起動ガード（APP_ENV=production×弱鍵JWT_SECRET or ワイルドカード混入→起動失敗、logger.critical付き）③create_app() DI化＋test_main.py/test_config.py新設。security/qa独立レビュー3巡でHigh2・Medium4全解消。
- **task_bd221d4e（middleware業者検証）は by-design と裁定**: 権限ゲートはバックエンド deps.get_verified_operator（vendor_status=="active"）＋transactions._assert_party（当事者スコープ）。pending業者の/operator閲覧許可は意図した非対称（閲覧可・入札不可）。middleware.ts ヘッダコメントに明文化済み＝再指摘は誤検知。
- **gate_status**: backend pytest=**138 passed** / web=前回green（今回webは middleware コメントのみ変更） / security=2巡通過(Critical/High 0) / QA=2巡通過(High 2→解消)
- **残存リスク（文書化済み・低）**: APP_ENV未設定の非正規デプロイ経路ではガード不発（render.yamlは明示済み）／main.pyとconfig.pyの危険トークン判定が二重化（次回リファクタで共有ヘルパー化推奨）／ADMIN_EMAILSがrender.yamlに平文（ユーザー判断でsync:false化を推奨）。
- **リリース前のユーザー対応項目（コード側は完了）**: ①/company・/legalの架空事業者情報→実値(task_b62c0b43) ②実画像アセット投入 ③LINEクレデンシャル設定（フロント: LINE_CLIENT_ID/SECRET・コールバックURL登録、バックエンド: LINE_CLIENT_ID/LINE_CHANNEL_ACCESS_TOKEN）④Render環境変数の確認（APP_ENV/ALLOWED_ORIGINSはrender.yaml反映済み・デプロイ時に実ログで起動確認）⑤mainマージ→デプロイ（承認操作）。

## 🧪 2026-07-03 フルスタック実機E2E（初のバックエンド接続ウォークスルー・/loop 自走）
- **環境**: backend=SQLite起動スクリプト `backend/run_local_e2e.py`（Docker/PostgreSQL不要・使い捨てDB e2e_local.db・conftestと同じJSONB→JSON方式）＋ web=本番ビルドを :3100（.claude/launch.json katazuke-web）。
- **APIレベルE2E全通**: user/admin/業者signup→admin承認(pending→active)→案件→入札→落札選択→取引→チャット往復→日程提案→確定(status=visiting)→業者プロフィール。シードは scratchpad の seed_e2e*.ps1（admin=e2e-admin@example.com/業者承認はPATCH verify {verified:true}）。
- **ブラウザ実機で配線確認済み✅**: /login /cases /cases/[id] /chat/[id]（**UI送信→業者側到達まで実証**）/schedule、/operator/login /operator/cases /operator/transactions(+詳細=住所連絡先開示+減額フォーム) /operator/chat /operator/profile。ミドルウェア分離（業者セッションでuser専用ページ→/loginへ）も実機実証。**全巡回でconsoleエラー0**。
- 🔴 **未配線＝ログインユーザーに架空データを表示する6ページ（次ラウンドの主対象）**: /mypage(山田花子) /applications(架空入札) /notifications(架空通知・**通知APIは未実装**) /result(「デモ表示」ラベル) /vendors/[id](**GET /vendors/{id}は実装済みなのに未配線**) /review(架空取引)。
- ⚠️ /operator ダッシュボード: 「交渉中」ハードコード0（operator/page.tsx の「チャットAPI未実装のため」コメントが陳腐化）・「今月の成約」はcompletedのみでvisiting非計上。
- **✅ 完了（2026-07-03・commit `a2675ef`）**: 上記6ページ＋ダッシュボード集計を実配線し**架空データ露出を全廃**。architect設計→frontend実装→実機E2E再検証（3欠陥発見: 虚偽完了バナー/訪問日時TZずれ/mypage分類不整合→即修正）→security/qa独立レビュー（Critical/High 0・Medium2件=e2e_local.db gitignore/評価待ち通知恒久残存→解消）→backend `TransactionListItem.has_review`追加（pytest 139全緑）。最終実証=取引完了→評価待ち通知→UI評価送信→通知消滅のフルサイクルをブラウザ実クリックで確認・コンソールエラー0。
- **設計判断の記録**: /applications・/resultは/cases系へのリダイレクタ（正本を/cases/[id]に一本化・旧査定ファネル/analyzing→/condition→/resultは流入ゼロの孤立レガシー）。/notificationsは通知API無しのため実データ導出サマリ方式（本格通知APIはP2候補）。/reviewのタグ/公開トグルはBE未対応のためコメント末尾付与/UI装飾（POST /reviews拡張はP2候補）。
- **P2候補（露出問題なし・任意の質向上）**: 通知専用API新設／POST /reviewsのtags・is_public対応／TransactionListItemのunread_count／CaseOutの入札締切時刻／main.py・config.pyの危険トークン判定一本化。

---

最終更新: 2026-06-13 / **本番デプロイ&E2E全合格済み（β稼働中）。現フェーズ＝業者獲得（量・スケール）。プラン正本: 業者獲得スケールプラン_v1.md**

## 🔧 2026-06-16 デプロイ前是正（strategy-agents Leader）— push-vendor-engine.ps1 の本番事故を2件修正
**push前検証で、スクリプトのままだと本番デプロイが失敗することを検出・修正した:**
1. **migration採番ズレ（致命）**: 新規 `0005_invites_lot_name.py` の `down_revision` が `"0004_auth_tables"` を指していたが、正典C:\sokuriでは auth_tables の revision ID は `"0005_auth_tables"`。そのままだと Render の `alembic upgrade head` が `Can't locate revision '0004_auth_tables'` でクラッシュ。→ `down_revision="0005_auth_tables"` に修正。チェーン検証で単一HEAD `0006_vendor_status`・全7本線形連結を確認（C:\sokuri実HEAD=0005_auth_tables から新規2本=追加系のみ適用）。
2. **コピー漏れ3ファイル（機能欠落）**: pushスクリプトのコピー対象に `endpoints/auth.py`（オープン業者登録）・`cases.py`・`transactions.py`（vendor_status住所マスク）が無く、これらを入れないと業者登録が旧挙動(招待コード必須→403)のまま。→ copy/git-add 両方に3ファイルを追加。
- **実機ゲート**: C:\sokuri\backend\.venv に不足依存(pyjwt/aiosqlite/email-validator/dnspython)を導入し、`pytest` を実行 → **61 passed, 0 failed**（beta E2E 57 + vendor 4。当初4 failedだった vendor テストが3ファイル追加で全緑）。
- **未対応(非ブロッカー・後続)**: フッターの /legal・/unsubscribe リンクは `web/src/app/layout.tsx` 内にあり、同ファイルは rebrand(a471a5f) と衝突するため今回は触れず。/legal・/unsubscribe の**ページ本体は配信される**。フッター導線は layout.tsx へ手動マージが必要（P2の /legal 実値記入と同時推奨）。

## ⚠️ 重要訂正（このファイルの以下旧記述を上書き）
- 正典repoは **C:\sokuri**（github.com/japandaily-hub/sokuri）。OneDrive側は作業コピー
- 本番バックエンドは **Render**（sokuri-backend.onrender.com）。Railwayは廃止済み
- C:\sokuriはアルバム機能(0003_add_albums, 無効化中)を持つため、カタヅケmigrationは
  **0004_katadzuke_schema / 0005_auth_tables** に振替済み
- 統合検証: backend pytest **56 passed** / web build **成功(21ページ, next 15.5.18)**
- 本番ブランドは当面ソクウリのまま（HP/layout色は不変更、カタヅケ画面を追加。layoutはProviders挿入のみ）
- katadzuke-api.ts / auth.ts に FALLBACK_PROD_API_URL（Vercel Sensitive env対策）
- render.yaml: JWT_SECRET(generateValue)/ADMIN_EMAILS/STORAGE_DIR=/tmp/uploads(エフェメラル・β許容)/
  BREVO_API_KEY(sync:false)/MAIL_FROM/FRONTEND_BASE_URL 追記済み
- ✅【完了 2026-06-12夜】push(7ffa097, 7084d8d)・Render稼働・Vercel AUTH_SECRET+NEXT_PUBLIC_API_URL修正(/api/v1付与)+Redeploy — **本番デプロイ完了**
- ✅【スモークテスト全合格 2026-06-12深夜・本番E2E】招待発行→業者登録→未承認403→承認→案件作成(写真PUT)→業者一覧住所マスク→入札→落札→業者へ住所/連絡先開示→減額(理由必須422検証)→承認(final 25000)→完了→双方レビュー→rating 5.0反映。UI側もsignup→/create 4STEP、業者ログイン→落札管理表示を実機確認
- **リリース直前状態。残りはユーザー操作のみ**: ①ご本人 https://sokuri.vercel.app/signup 登録(=admin) ②/adminで実業者3社へ招待コード発行・送付 ③(任意)RenderにBREVO_API_KEY設定でメール有効化
- probe検証データ: users=probe-check/probe-ui/ko.13.hei+kdzadmin(admin)、operator=片付けプローブ(株)、case/txn各1件(完了済) — βでは無害。ADMIN_EMAILSに+kdzadminエイリアス追加済(Render env+render.yaml)
- 既知マイナーバグ(非ブロッカー): ai_summaryフォールバック文の「写真N枚」がAI解析可能枚数基準（case.photos数を渡すべき）/ UI写真アップロードがRender再起動と重なると「失敗しました」(リトライで成功)
- 修正済み追加: backend/Dockerfile（app/コピーをpip installの前へ）
- ✅【最終磨き込み 78f51b0 push済・本番反映確認済】①セッション対応ヘッダーナビ（ログイン/ログアウト/マイ案件/管理/業者メニュー）②写真アップロード自動リトライ ③ai_summary写真枚数バグ修正 ④フッターに業者ログイン導線 ⑤招待業者向け案内文面 docs/beta-operator-onboarding.md（送付用テンプレ）。render.yamlもコミット済
- C:\sokuri未コミットの残作業ファイル: kdz-commit.ps1 / push-katadzuke.ps1 / .kdz-*.log / test-room.jpg（一時物・削除可）
- sandboxマウント注意: ホストWrite/Edit直後のファイルはbashから截断して見える（C:\sokuriでも発生）。
  bash経由Writeは整合。検証は/tmpでheredoc再生成方式

## フェーズ進捗
- [x] Phase A: バックエンドAPI（pytest 80/80）
- [x] Phase B: 認証（NextAuth v5 Credentials → backend JWT）
- [x] Phase C: フロントエンド全画面（npm run build 成功・18ルート）
- [x] Phase D: メール3種実装済み + env/デプロイ手順整備
- [ ] 本番デプロイ実行（→ deploy-katadzuke.ps1 / ユーザー操作）

## 完成定義チェック（13項目）
- [x] 案件作成（写真+住居情報+AI要約）
- [x] 業者が案件一覧・詳細を閲覧（承認制・住所マスク）
- [x] 業者が入札（1案件1回・金額+メッセージ）
- [x] ユーザーが入札一覧確認・1社選択
- [x] 落札後に業者へ住所詳細開示（バックエンド制御・テスト済）
- [x] 減額申請フロー（理由必須10字+DB NOT NULL→ユーザー承認/却下）
- [x] 成約完了・キャンセル（業者キャンセルはcancel_count記録）
- [x] ユーザー認証（email+password / ADMIN_EMAILSでadmin）
- [x] 業者認証（招待コード1回限り+email+password）
- [x] 管理画面（招待コード発行KDZ-XXXXXXXX・業者承認/取消）
- [x] メール通知3種（案件化完了/入札/落札 — Brevo、キー未設定時スキップ）
- [x] npm run build エラーなし（sandbox検証済）
- [x] pytest エラーなし（80 passed）
- [ ] Vercel+Railway本番デプロイ → **次アクションP1**

## アーキテクチャ要点
- 認証: backend発行JWT（scrypt+PyJWT HS256）。NextAuth v5はCredentials Providerで
  /auth/login・/auth/operator/login を呼びtokenをセッション保持。middleware.tsで
  user(/create,/cases)・operator(/operator)・admin(/admin)を分岐
- 写真: POST /upload/presign → PUT /upload/{key} → GET /files/{key}（ローカルディスク、
  STORAGE_DIR。RailwayはVolume /data 必須。R2移行はstorage.pyのURL差し替えのみ）
- AI要約: services/summary.py が vision.analyze_image を写真ごとに呼び集約。失敗時フォールバック文
- 住所統制: cases系は常にマスク。GET /transactions/{id} のみ当事者に開示（cancelled後は非開示）
- migrationチェーン: 0001→0002→0003→0004（railway.json起動時にalembic upgrade head自動実行）

## 新規/変更ファイル一覧
backend: alembic/versions/0004_auth_tables.py / models{user,invite,operator+,__init__+} /
core/security.py / api/deps.py / schemas_katadzuke.py / services{storage,summary,notify} /
endpoints{auth,case_photos,cases,bids,transactions,reductions,reviews,admin} / router+ /
main+(CORS PUT/PATCH/DELETE) / config+ / pyproject+ / tests/{conftest+,test_katadzuke_api.py} /
.env.example+ / **seed.py修復**（同期コンフリクト破損→440行正版でWrite済）
web: auth.ts / middleware.ts / types/next-auth.d.ts / lib/katadzuke-api.ts /
components/{AuthCard,kdz/Ui}.tsx / app/{providers,login,signup,operator/{login,signup,cases,
cases/[id],transactions,transactions/[id]},create,cases,cases/[id],admin}/page.tsx /
api/auth/[...nextauth]/route.ts / layout.tsx(カタヅケ化+Providers) / package.json(next-auth beta.29) /
**tailwind.config.ts修復**（WEEK1書き換えで欠落したcontainer/cta/xs/accent/fade-*を復元。teal維持）/
.env.example新規
root: deploy-katadzuke.ps1

## 本番デプロイ手順（ユーザー実行）
1. Railway Variables: DATABASE_URL/GOOGLE_API_KEY/ALLOWED_ORIGINS(=Vercel URL)/
   JWT_SECRET(rand 64hex)/ADMIN_EMAILS/STORAGE_DIR=/data/uploads/BREVO_API_KEY/
   MAIL_FROM/FRONTEND_BASE_URL(=Vercel URL) + Volume /data
2. Vercel: Root=web, NEXT_PUBLIC_API_URL(=Railway URL/api/v1), AUTH_SECRET
3. `.\deploy-katadzuke.ps1 -RailwayUrl https://... -VercelUrl https://...`
4. スクリプト末尾のスモークテスト6手順を実施

## 既知の地雷（再発防止）
- **sandboxマウントはOneDriveの最近書いたファイルを截断して見せる**（旧版/null/途中切れ。
  syntaxは通るが実行で壊れるパターンあり）。テストは/tmpコピー後に
  compileall+import+sentinel末尾照合、壊れていたらheredocで再生成してから実行
- sandboxはbash呼び出し終了で子プロセスをkill（nohup無効）→ npm installは
  `--omit=optional`+package-lock事前生成で1回完結、大物バイナリはcurl -C - で取得
- 正典側の実破損2件は修復済み: seed.py（重複断片）/ tailwind.config.ts（トークン欠落）
- pyproject requires-python>=3.11 vs sandbox 3.10 → テスト時は依存個別pip

## 次アクション（2026-06-15更新 — 業者獲得エンジン実装完了）
| P | アクション | 担当 |
|---|---|---|
| **P1(即)** | **push-vendor-engine.ps1 を実行**（C:\sokuri へコピー → git push → Render自動 alembic upgrade head） | ユーザー |
| P2 | /legal の [運営者名][住所][電話番号] を実際の値に書き換えてからアウトリーチ開始 | ユーザー |
| P3 | 業者リスト_首都圏（遺品整理士認定協会/JRRC/ポータル掲載）上位100社へ §9 文面でアウトリーチ開始 | ユーザー |
| 済✅ | TASK-1 バルクコード一括発行（POST /admin/invites/bulk・最大500件・CSVダウンロード） | 完了 |
| 済✅ | TASK-2 オープン業者登録+vendor_status制（Migration 0005/0006・招待コード任意・limited/active） | 完了 |
| 済✅ | TASK-3 GET /admin/cell-density（需給比率ヒートマップ） | 完了 |
| 済✅ | TASK-4 /unsubscribe・/legal・フッターリンク（コンプラページ） | 完了 |
| 旧(済) | 本番デプロイ・E2E14ステップ全合格・最終磨き込み78f51b0 push済 | 完了 |

## 実装完了サマリ（2026-06-15 strategy-agents 自走）
- pytest 22/22 PASS（新規5テスト含む）
- Migration chain: 0001→0002→0003→0004→0005→0006（整合確認済み）
- 重要設計決定: vendor_status は3値(pending/limited/active)・invite_code部分ユニークINDEX・認可ゲートOR条件移行
- npm build: Windows Node.jsバイナリのためsandbox確認不可 → push後 Vercel 自動ビルドで確認
- ⚠️ /legal の運営者情報はプレースホルダー[要記入]のまま → アウトリーチ前に必ず埋めること

> 業者獲得の核心: 0円の冷たいGmap営業のみだと月7〜16社稼働が実力値。月40社級は「団体名簿/ポータル掲載業者/紹介」など反応率の高いチャネルを先に回して初めて到達。北極星KPI＝週次・新規“稼働”業者数（登録後14日以内に1入札）。
