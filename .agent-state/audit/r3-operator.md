# 運営導線 監査台帳（第3周・追加観点）
最終更新: 2026-09-04 / 監査方式: 静的読解（Read/Grep/Bash、読み取り専用）/ 対象: 運営（admin）視点のみ
前提: `.agent-state/PROJECT_STATE.md`・`docs/TODO.md`・`.agent-state/audit/{operator-crosscut,verify-operator,review-qa}.md` を先読みし、既知＆意図的未対応の項目（A1〜A7/B1-H1〜H3/B3-H1〜H2、口コミ非表示UI未実装、停止解除トークン世代カウンタ未実装 等）は再指摘しない。以下は前2周の台帳に記載のない新規観点のみ。

---

## High

### H1. `/contact` お問い合わせフォームがバックエンド未配線で、送信内容が実際にはどこにも届かない（「トラブル・クレーム」区分含む）
- 該当: `web/src/app/contact/page.tsx:1-6`（実装者自身のコメント「送信はバックエンド未配線。クライアント側で必須項目の簡易バリデーションを行い、通過したら『送信を受け付けました（デモ）』の完了表示に切り替える」）, `:29-58`（`onSubmit` は `e.preventDefault()` 後 `setSent(true)` するのみで `fetch`/`mailto`/API呼び出しが一切ない）, `:257`（完了画面の文言「送信を受け付けました（デモ）」）, `:165-183`（種別セレクトに「トラブル・クレーム」「個人情報の取り扱いについて」を含む）。
- 事象: ユーザーが名前・メール・種別・本文を入力して送信すると、内容はブラウザの state に一瞬保持されるだけで即座に破棄され、メール送信・DB保存・Slack通知等の永続化/転送は一切行われない。それにもかかわらず画面は「通常3営業日以内にご返信します」と断定表示する。ページ全体に `mailto:`・電話番号など送信以外の代替連絡手段も存在しない（grep確認、該当0件）。
- 再現手順: `/contact` にアクセス→全必須項目を入力→「送信する」をクリック→「送信を受け付けました（デモ）」の完了画面に遷移することを確認。その後サーバーログ・DB・メール受信箱のいずれにも当該内容が残らないことを確認（バックエンドに `/contact` 相当のエンドポイントが存在しないことは `find backend/app/api/v1/endpoints` の全ファイル一覧で確認済み・該当なし）。
- リスク: 運営はこの経路で来た問い合わせ・クレームの存在を一切知り得ない。ユーザーには「返信します」と約束しておきながら黙殺する形になり、信頼毀損・特商法上の問い合わせ対応義務との整合性の観点でも本番リリース前に必ず解消すべき。
- 修正案: 最小構成は (1) バックエンドに `POST /contact-messages` 等を新設し `notify.py` 経由で運営宛メール（Brevo）を送る、(2) 難しければ暫定措置として画面文言を「デモ」実装である旨排除しつつ、フォームを撤去し `mailto:support@...` 等の直接連絡手段のみを案内する。いずれか実装するまでは、少なくとも「3営業日以内に返信」という断定文言と偽の完了画面は外すべき（`create/complete` を偽成功表示是正した際の方針（`docs`記載・review-qa.md H1と同種の問題）と平仄を合わせる）。

### H2. 運営は案件・成約（取引）を横断的に閲覧・介入する手段が皆無 — 強制終了もトラブル介入も事実上不可能
- 該当: `backend/app/api/v1/endpoints/cases.py:266-294`（`list_cases` は `actor.typ == "user"` 分岐で常に `Case.user_id == actor.user.id` に絞り込み、`role=="admin"` の特別扱いが無い。admin は User 行として `typ="user"` でログインするため（`backend/app/api/deps.py:117-125` `get_current_admin` は `get_current_user` の上に role チェックを乗せるだけで `typ` は変わらない）、`GET /cases` を叩いても自分自身が作成した案件しか返らず、実質常に空配列になる）, `backend/app/api/v1/endpoints/transactions.py:54-77`（`list_transactions` も同様に `Case.user_id == actor.user.id` のみで admin 分岐なし）, `backend/app/api/v1/endpoints/reductions.py:103-114`（`decide_reduction` は `user.role != "admin"` の条件で admin による代理回答自体はコード上許可されているが、一覧APIが admin 向けに何も返さないため、どの取引にどの減額申請が pending かを admin が知る手段が無い＝到達不能）, `web/src/app/admin/page.tsx`（全642行を grep しても「案件」「取引」への言及は cell-density の集計表（`open_cases` 件数のみ）以外に存在せず、個別案件・成約への一覧/検索/リンクが一切ない）。
- 事象: 運営が「この依頼者とこの業者の間でトラブルが起きている」という情報を（メールやLINEでの直接申告以外から）把握しても、案件IDや成約IDを本人からヒアリングして手動でAPIを叩く以外に中身を見る方法がない。`GET /cases/{case_id}` と `GET /transactions/{id}` 自体は `role=="admin"` を個別に許容しているが（cases.py:310, transactions.py 該当箇所参照）、一覧が空を返すため「どのIDを見ればいいか」への到達経路が管理画面に存在しない。さらに、案件を強制的に終了させる・成約を運営主導でキャンセルする専用エンドポイントも `backend/app/api/v1/endpoints/{cases,transactions}.py` に存在しない（grep確認、`get_current_admin` を使う case/transaction 系エンドポイントは0件）。
- 再現手順: admin アカウントで `/login` → 取得したトークンで `GET /cases` を呼ぶ→ 空配列（または admin 自身が過去に一般ユーザーとして出品した案件のみ）が返ることを確認。`/admin` 画面内をすべて確認しても案件一覧・成約一覧へのリンクが存在しないことを確認。
- リスク: 「取引トラブル時の介入」「案件の強制終了」という運営の基本業務が、コード上も画面上も実行不可能。減額申請（reductions）の未回答放置も運営からは検知不能（依頼者自身が回答するのを待つのみ）。リリース後にトラブルが発生した場合、運営はDB直接操作以外に対応手段がない。
- 修正案: 最小構成として (1) `backend/app/api/v1/endpoints/admin.py` に `GET /admin/cases`（全件・依頼者名/業者名/ステータスで検索）と `GET /admin/transactions`（同様、pending reduction の有無を含む）を追加し、既存の `get_case`/`get_transaction`/`decide_reduction` へ導線として使う、(2) `web/src/app/admin/` に一覧画面を追加しリンクする。強制終了・キャンセル権限の付与は業務要件の確定（誰の承認で・どのステータス遷移を許すか）が必要なため、まずは「見える化」だけでも先行して着手可能。

---

## Medium

### M1. AI画像解析（Vision）の失敗が管理画面はおろかDBのどこにも記録されず、運営は連続失敗を把握できない
- 該当: `backend/app/api/v1/endpoints/analyze.py:46-67` — `analyze_image` が `ValueError`（422）・`GenAIAPIError`（503）を送出した場合、そのまま `HTTPException` に変換してユーザーへ返すのみで、`logger.error`/`logger.warning` 等のログ出力も、失敗回数を残すテーブルへの `INSERT` も一切ない（該当関数内に `logger` の呼び出し自体が存在しない、grep確認）。
- 事象: Gemini 側のレート制限・タイムアウト・5xx が連続発生しても、運営が気づく手段はサーバー標準出力（Renderのログ、7日保持）を能動的に読みに行くことのみで、`/admin` 側には失敗件数・直近失敗時刻を示す指標が一切無い。依頼のBlock2(3)が対象外とする「通知そのもの」ではなく、「管理画面での可視化の有無」の観点として、可視化する仕組みが存在しないことを指摘する。
- 修正案: 最小構成は analyze.py の except節に `logger.error` を追加した上で、`GET /admin/cell-density` 相当の軽量集計として直近N時間の失敗回数を返す `GET /admin/health-summary` 等を新設し `/admin` にカード表示する。テーブル追加が重ければ、まずは構造化ログ出力だけでも先行して入れる。

### M2. 業者一覧・招待コード一覧・本人確認書類一覧のいずれもバックエンドに件数上限（LIMIT/ページング）が無く、全件を無条件に返す
- 該当: `backend/app/api/v1/endpoints/admin.py:161-176`（`list_operators` は `select(Operator).order_by(...)` のみで `limit`/`offset` パラメータが無い）, `:161-167`（`list_invites` も同様）, `:495-527`（`list_identity_documents` も `status_filter` はあるが `limit`/`cursor` は無い）。
- 事象: フロント側（`web/src/app/admin/page.tsx`）は検索ボックスとステータスフィルタをクライアントサイドで実装済み（前回監査 A6 は解消済みと確認）だが、これは「全件を一度に取得してからJSでフィルタする」実装であるため、業者数・招待コード数・書類件数が数千件規模に増えると、初期表示のたびに全件をネットワーク越しに取得し続けることになる。ベータ期の現状規模では実害は軽微だが、依頼のBlock2(4)「データ量増加時の使い勝手」の観点で、成長を見込んだ場合に上限が無いことは設計上の抜けとして記録する。
- 修正案: `limit`（既定100〜200）・`offset` または `cursor` をクエリパラメータとして各 `GET /admin/*` に追加し、フロントの検索は既存のクライアントサイド実装をサーバーサイド検索（`company_name`/`email` の `ILIKE`）に段階的に置き換える。件数が現状少ないうちは優先度低でよい。

---

## 確認したが問題なし（観点別）

- **admin 認可の境界**: `backend/app/api/v1/endpoints/admin.py` の全17ルートがいずれも `admin: User = Depends(get_current_admin)` を第一級の依存として持ち（grep で `@router` 22件・`get_current_admin` 使用17件超を突合、例外なし）、`get_current_admin`（`backend/app/api/deps.py:117-125`）は `user.role == "admin"` を厳格にチェックしている。業者/依頼者トークンで到達できる admin 専用の書き込み系操作は発見できなかった。
- **ファイル配信 `/files/{storage_key}`（無認証capability URL）**: `backend/app/api/v1/endpoints/case_photos.py:111-114` は無認証だが、これは商品写真専用であり、`operator_license.py:4` と `user_identity.py:5` のコメントに明記の通り「本人確認書類・許可証は絶対にこの方式を再利用しない」という設計判断が既にコード内に明文化されている。実際、本人確認書類は `GET /admin/identity-documents/{id}/file`（`admin.py:554-585`、`get_current_admin` 必須・アクセスをログ記録）という別経路で配信されており、意図的な設計として妥当。新規の指摘事項なし。
- **業者却下理由の依頼者/業者への通知経路**: `backend/app/api/v1/endpoints/admin.py:454-459`（`reject_operator_application` は `notify.send_operator_application_rejected` を background task で送信）、`:410-415`（承認時も同様）で実装済み。運営が却下操作をした後の通知経路は途切れていない。
- **本人確認書類の却下→再提出の依頼者導線**: `web/src/app/mypage/identity/page.tsx:344` に差し戻し理由の表示が実装済み、再提出フローも `backend/app/api/v1/endpoints/user_identity.py` に存在（`DOCUMENT_STATUS_PENDING` への再遷移を許可する分岐を確認）。導線は途切れていない。
- **個人情報（本人確認書類・振込口座）への運営アクセスの監査ログ**: `admin.py` の書類閲覧（`:574-580`）・口座開示（`:364-370`）・書類一覧取得（`:530-536`）のいずれも `admin.id`/`admin.email` を含む `logger.info` が実装済み（PII本体はログに含めない配慮あり）。DBの監査テーブルではなくアプリログである点は限界だが、「アクセスが一切残らない」という状態ではない。
- **CSVインジェクション対策（前回 A7）**: `web/src/app/admin/page.tsx:173-179` の `csvCell` で `=+/-@`/タブ/CR 始まりの値にシングルクォート付与＋カンマ/改行/ダブルクォート含有時のクオート処理が実装済み。解消を確認。
- **業者停止/解除導線（前回 A2）・承認ボタンの許可証ゲート（前回 A1）**: `backend/app/api/v1/endpoints/admin.py:207-229`（`suspend_operator`）、`:192-196`（`verify_operator` のサーバー側 `has_license_image` ガード）とも実装済み。フロント側 `web/src/app/admin/page.tsx:503,521-523` にも停止/解除ボタンと disabled 制御が実装済み。解消を確認。

---

## 未解決・確認できなかった点

1. `docs/ops/` は `alerting.md` のみで、他の運用手順書（`docs/beta-operator-onboarding.md` 等）との内容的な食い違いは招待コード発行URLの言及程度しか確認できておらず、全文の突合は本監査のツール呼び出し上限内では未実施。
2. `render.yaml`・`backend/start.sh` の環境変数フォールバック網羅チェックは、`backend/app/config.py` が別セッション編集中かつ指摘対象外のため深掘りを見送った。`APP_ENCRYPTION_KEY` 等、PROJECT_STATE.md に既に記載済みの未確認事項はそちらに委ねる。
3. H1・H2 とも「発見」であり、実装（バックエンドAPI追加・画面追加）は本タスクの禁止事項（ファイル編集・作成）に該当するため未着手。次アクションとして別セッションでの着手を推奨する。
4. M1の「AI失敗の可視化」は、既存の障害通知基盤（P1・別セッション担当）と実装が重複しうる。通知基盤側で `alert_middleware.py`/`alerts.py` が5xxを既にカウントしている可能性があり、その値を admin 画面に転用できないか、担当セッションとの調整が望ましい［推測］。

---

## サマリ
結論: リリース阻害級の新規 High を2件（お問い合わせフォームの送信先消失／案件・取引への運営アクセス経路の欠落）検出。いずれも過去2周の台帳（operator-crosscut/verify-operator/review-qa）に記載がない新規観点で、コード上の実在を確認済み。Medium 2件（AI解析失敗の不可視化、一覧系APIの件数上限欠如）は将来のスケール時に効いてくる設計負債として記録。
✅達成: 認可境界（admin役割ゲート）・PII監査ログ・ファイル配信設計・前回指摘の解消状況（A1/A2/A7）はいずれも健全と確認。
⚠️課題: High 2件は実装（バックエンド新規エンドポイント＋管理画面）が必要で本タスク範囲外（禁止: ファイル編集・作成）。
❌ブロッカー: なし（ブロッカーではなく「未実装の運営機能」として次アクション化すべき事項）。
