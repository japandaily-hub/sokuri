# R3 実装差分 QAレビュー（独立検証）

実施日: 2026-09-04 / 実施者: qa-reviewer（独立レビュー・コード無変更）
対象: git diff（未コミット）＋ 未追跡新規（contact.py / 0025_user_suspend.py / test_contact.py /
test_admin_user_controls.py / web/src/app/admin/{cases,transactions,users}/page.tsx / admin/_components/*）
対象外（別セッション編集中・未読）: config.py / main.py / alert_middleware.py / services/alerts.py /
tests/test_alerts.py / .github/workflows/uptime-alert.yml

## 総合判定

**条件付き合格**。Critical 0 / High 3 / Medium 7 / Low 5。
High 3件はいずれもリリース前に修正すべきだが、データ破壊やセキュリティ侵害ではなく
UXデッドエンド・契約不一致・法務コピー不整合のため、修正すればそのままリリース可能。

## 実行検証

| コマンド | 結果 |
|---|---|
| backend/.venv/Scripts/python.exe -m pytest -q | **680 passed**, 0 failed, 630 warnings (167.18s) |
| web> npx tsc --noEmit | **exit 0**（エラー0） |
| web> npx eslint src | **0 errors / 3 warnings**（notifications/page.tsx:191, operator/transactions/[id]/page.tsx:92, signup/page.tsx:59 — いずれも本差分で未編集の既存warning） |
| next build | 指示により未実行（別セッションのdevサーバー保護） |

台帳（r3-impl-backend2.md）が主張する「680 passed」「tsc/eslint 0エラー」は再現確認済み。
alembic heads は日本語パス環境の cp932 問題でCLI実行不能（台帳の記載どおり・本差分とは無関係）。

---

## Critical（0件）

なし。

---

## High（3件）

### H1. /create の離脱確認モーダル「ページを離れる」が、直接アクセス時に永久に離脱できない

- **該当箇所**: `web/src/app/create/page.tsx:204`（confirmLeave 内の window.history.go(-2)）、
  番兵push は `web/src/app/create/page.tsx:188-192`、popstate再push は `:178-183`
- **問題**: 番兵1つ＋元の /create エントリ分を戻す前提で -2 を固定値でハードコードしている。
  /create がセッション履歴の**先頭**（index 0）の場合、番兵が index 1 なので go(-2) は
  index -1 を指し **完全な no-op** になる。モーダルは閉じるが画面は /create のまま。
  さらに allowLeaveRef.current = true を先に立てているため popstate ガードも無効化され、
  以後バックしても index 0（= /create 自身）に戻るだけで、ブラウザバックでは永久に離脱できない。
- **再現条件**: 新規タブ・ブックマーク・LINE内ブラウザ・SNS/メールのリンクから
  /create を**直接**開く（＝実際の流入の主要経路）→ 写真を1枚撮影 →
  ブラウザバック → 確認モーダル → 「ページを離れる」を押す → 何も起きない。
- **修正案**: 履歴段数への依存をやめる。confirmLeave() を
  「allowLeaveRef.current = true; setLeaveConfirmOpen(false); router.push("/mypage");」に変更する
  （/create は入口が複数あるため戻り先はマイページ固定が安全）。
  履歴に戻したい場合は window.history.state?.kdzCreateGuard の有無で戻り段数を実測すること。

### H2. /admin/users の検索プレースホルダと backend 実装が不一致（IDで検索しても0件）

- **該当箇所**: `web/src/app/admin/users/page.tsx:117`（placeholder「ユーザーID（前方一致）・メール・表示名（部分一致）で検索」）
  vs `backend/app/api/v1/endpoints/admin.py` の admin_list_users
  （conditions は User.email.ilike と User.name.ilike のみ。ID検索の条件が無い）
- **問題**: **同型の複製伝播漏れ**。admin_list_cases は cast(Case.id, String).ilike を、
  admin_list_transactions は cast(Transaction.id, String) / cast(Transaction.case_id, String) を持つのに、
  admin_list_users だけ ID 条件が欠落している。同画面は CopyableId でユーザーIDのコピー機能を
  提供しているため、「コピーして貼り付けて検索」が確実に空振りする。
- **再現条件**: admin ログイン → /admin/users → 任意行のIDをクリックしてコピー →
  検索欄に貼付 → 検索 → 「該当する依頼者はいません。」
- **修正案**（どちらか）:
  1. backend を揃える（推奨）: conditions.append(or_(cast(User.id, String).ilike(q_norm + "%"),
     User.email.ilike("%" + q_norm + "%"), User.name.ilike("%" + q_norm + "%")))
     （String / cast / or_ は同ファイルで import 済み）
  2. placeholder から「ユーザーID（前方一致）・」を削除し、CopyableId の用途を「他画面への転記のみ」と明示する。

### H3. 業者が実額を見る唯一の画面にβ無料注記が伝播しておらず、かつ表示額が実装と矛盾する

- **該当箇所**: `web/src/app/operator/chat/[id]/page.tsx:513-517`
  （status==="completed" ? yen(fee_amount) : yen(Math.round(amount * 0.08)) + "（予定・完了時確定）"）
- **問題（2点）**:
  1. 今回β注記「※サービス開始当初（β期間）は手数料を請求しません」を
     `operator/page.tsx:259` `operator/profile/page.tsx:698` `business/page.tsx:54,76,276`
     `faq/page.tsx:33` `legal/page.tsx:120` `terms/TermsTabs.tsx:152` `page.tsx:421` に一斉追記したが、
     **業者が円単位の実額を見る唯一の画面であるこの成約チャットだけ抜けている**（隣接チェック漏れ）。
  2. Transaction.fee_amount は `backend/app/db/models/transaction.py:40` で default=0 かつ
     加算実装が存在しない（r3-impl-backend.md「fee_amount（8%手数料）の実装は未対応」）。
     したがって完了前は「8,000円（予定・完了時確定）」、完了後は必ず「0円」に切り替わる。
     業者に「請求される」と誤認させたうえで実額が0になるため、信頼を損なう。
- **再現条件**: 業者ログイン → 成約チャット /operator/chat/{transaction_id} を開く →
  「手数料 8,000円（予定・完了時確定）」を確認 → 取引を完了 → 同画面で「手数料 0円」に変化。
- **修正案**: 同 dp-row にβ注記を併記し、β期間中は予定額を計算せず
  「0円（β期間中は手数料を請求しません）」固定表示にする。

---

## Medium（7件）

### M1. 未使用コンポーネントに、是正前の断定的クーリング・オフ文言が残存

- **該当箇所**: `web/src/components/landing/Faq.tsx:39`（および同 `:23`）
- **問題**: :39「訪問による買取には特定商取引法が適用され、法定書面の交付、**8日間のクーリングオフ**、
  その期間中の物品引き渡し拒絶権など、消費者としての保護を受けられます。」と**無条件に断定**しており、
  今回 `faq/page.tsx:64` `legal/page.tsx:176` `terms/TermsTabs.tsx:104` `page.tsx:28,306`
  `schedule/page.tsx:512` に統一した「可否は品目（家具・家電等は対象外）や経緯によって異なる」と
  正面から矛盾する。:23「業者登録は当面無料で運用しています」も 8%＋β注記と矛盾。
  grep -rn "landing/Faq" web/src は 0件＝現在どこからも import されていない死にコードだが、
  流用・復活時に景表法／特商法リスクが再燃する（是正の網から漏れた最も危険な形）。
- **再現条件**: 静的解析（grep）のみ。実行時には現れない。
- **修正案**: ファイルごと削除する。残すなら本文を faq/page.tsx:64 と1文字単位で同一にする。

### M2. admin一覧が退会済み（deleted_at）ユーザーを除外していない

- **該当箇所**: `backend/app/api/v1/endpoints/admin.py` の admin_list_users（conditions に deleted_at 条件なし）、
  admin_list_cases / admin_list_transactions の user_email バッチ取得（select(User).where(User.id.in_(...))）。
  モデルは `backend/app/db/models/user.py:85` の deleted_at。
- **問題**: 退会済みユーザーが依頼者一覧に「有効」バッジで並び、PATCH /admin/users/{id}/suspend も
  通ってしまう（実質意味のない操作）。案件・成約一覧も退会者のメールを平文表示する。
- **再現条件**: ユーザーが退会（論理削除）→ admin が /admin/users を開く → 当該ユーザーが「有効」で表示され、
  「停止する」が押せて 200 が返る。
- **修正案**: conditions.append(User.deleted_at.is_(None)) を admin_list_users に追加。
  一覧に残す方針なら AdminUserListItem に deleted_at を追加し、UIで「退会済み」バッジ＋操作ボタン非表示にする。

### M3. admin一覧3種のページングに tie-breaker が無く、境界で重複・欠落しうる

- **該当箇所**: `backend/app/api/v1/endpoints/admin.py` の admin_list_cases（order_by(Case.created_at.desc())）、
  admin_list_transactions（order_by(Transaction.created_at.desc())）、
  admin_list_users（order_by(User.created_at.desc())）
- **問題**: created_at が同値の行（同一トランザクション内バルク作成・秒未満精度が同じ環境）で
  ソート順が未定義になり、offset ページングでページ跨ぎの重複・欠落が発生する。
  既存テスト test_admin_list_cases_respects_limit_and_offset は created_at が異なる前提のため検知できない。
- **再現条件**: created_at が同一の Case を60件作成 → limit=50&offset=0 と offset=50 を取得 →
  和集合が60件にならない（DB・プラン次第で再現）。
- **修正案**: 全3箇所を .order_by(X.created_at.desc(), X.id.desc()) にする。

### M4. ページング表示が offset > total で破綻する（total=0 は正常）

- **該当箇所**: `web/src/app/admin/_components/AdminPagination.tsx:19-21`
  （const from = total === 0 ? 0 : offset + 1; const to = offset + itemCount;）
- **問題**: total = 0 は from = 0 で「全0件中 0〜0件」と正しく出るが、
  offset > total（items 空）では「全10件中 **51〜50件**を表示」という逆転表示になり、
  同時に描画される「該当する依頼者はいません。」と矛盾する。backend 側は offset に上限を設けていない
  （Query(default=0, ge=0) のみ）ため、URL直打ちや並行データ削除で到達しうる。
- **再現条件**: /admin/users で2ページ目（offset=50）を表示 → 別セッションでユーザーが削減され total<50 に →
  再読み込み → 「全10件中 51〜50件を表示」。
- **修正案**: itemCount === 0 && offset > 0 のとき件数文言を「該当なし」に切り替え、
  かつ reload 成功時に items.length === 0 && offset > 0 なら setOffset(0) して再取得する。

### M5. /contact の運営宛メールが「件名HTMLエスケープ」かつ Reply-To 未設定

- **該当箇所**: `backend/app/services/notify.py` の send_contact_received（件名に html.escape(category) を適用）、
  および同 `backend/app/services/notify.py:51-73` の _send（payload に replyTo が無い）
- **問題（2点）**: (1) Brevo の subject はプレーンテキストのため、category に & 等が含まれると
  件名に「&amp;」がそのまま出る（html.escape の適用先を誤っている。本文側の escape は正しい）。
  (2) replyTo 未設定のため運営受信箱から直接返信できず、
  `web/src/app/contact/page.tsx` の「3営業日以内にご連絡します」という約束が運用で担保されない。
- **再現条件**: 種別に & を含む値を設定した場合／運営が受信メールに返信しようとした場合。
- **修正案**: 件名は category から改行を除去した生値を使い、_send に reply_to 引数を追加して
  payload に replyTo（送信者のメール・氏名）を載せる。

### M6. /create 正常送信後に番兵履歴が残り、案件詳細からの「戻る」が2回必要になる

- **該当箇所**: `web/src/app/create/page.tsx:188-192`（番兵push）、同 `:415-416`（成功時 allowLeaveRef=true → router.push）
- **問題**: 成功送信時に番兵エントリを消費しないため、履歴は
  [..., prev, /create, 番兵(URL=/create), /cases/{id}] になる。案件詳細で「戻る」を押すと
  URLが /create の番兵に着地し、**空の作成フォームが再マウントされる**。
  もう一度戻ってようやく実体の /create（これも空）に着く。ユーザーには
  「戻るが効かない／作った案件が消えた」ように見える。
- **再現条件**: /create で案件を作成 → 遷移先の /cases/{id}?created=1 でブラウザバック →
  空の /create STEP1 が表示される → もう一度バックしても同じ /create。
- **修正案**: 成功時に window.history.replaceState で番兵を潰してから router.replace で案件詳細へ遷移する
  （作成完了後に /create へ戻す意味は無いため replace が妥当）。

### M7. 新規実装に対するテストが正常系偏重で、上記 H1〜M4 をどれも検知できない

- **該当箇所**: `backend/tests/test_contact.py`（5件）、`backend/tests/test_admin_user_controls.py`（3件）、
  `backend/tests/test_katadzuke_api.py` 追加分（8件）
- **問題（欠落しているケース）**:
  1. dispatch_reduction_requested / dispatch_transaction_cancelled の
     **LINE未連携→メールフォールバック**分岐（notify_dispatch.py の is_placeholder_email 早期returnを含む）
  2. dispatch_transaction_cancelled の recipient_party 別リンク（/chat/{id} vs /operator/transactions/{id}）の検証
  3. **停止中ユーザーが一般APIで403になること**（deps.assert_user_not_suspended の
     get_current_user / get_current_actor 経路。現状テストは suspend API の 200/409 のみ）
  4. POST /analyze の**アカウント軸**レート制限429（request.state.rate_limit.hit_account 経路。
     追加されたのは401テストのみ）
  5. admin一覧の**境界値**（total=0、offset > total、limit が上限超で422、q が空白のみ）
  6. admin_list_users の**ID検索**（H2 の欠落を検知するテストが存在しない）
- **修正案**: 上記6系統を pytest に追加する。特に(3)は「停止機能が実際に効くか」の本丸であり、
  APIが200を返すことだけを検証している現状は網羅性として不足。

---

## Low（5件）

### L1. ContactCreateRequest が空白のみの入力を通す
`backend/app/schemas_katadzuke.py` の ContactCreateRequest（name/message とも min_length=1 のみ）。
半角スペース1文字が valid になり、直接POSTで空の問い合わせが運営に届く。web側は .trim() 済みのため実害は限定的。
修正案: field_validator で strip 後の長さを検証する。

### L2. /contact 完了文言の「登録メールアドレス」が実態と不一致
`web/src/app/contact/page.tsx` 完了画面「3営業日以内に**登録**メールアドレスへご連絡します。」。
/contact は未ログインでも利用でき、送信先はフォーム入力値。
修正案: 「ご入力いただいたメールアドレスへご連絡します。」

### L3. admin の取引一覧から /chat/{id} へ遷移でき、admin がメッセージを投稿できてしまう
`web/src/app/admin/transactions/page.tsx:162` が /chat/{t.id} を指す。
`backend/app/api/v1/endpoints/transactions.py:133`（_assert_party）が role == "admin" を
party = "user" として許容するため、閲覧だけでなく **admin が依頼者名義でメッセージを送信できる**。
修正案: 一覧の導線を読み取り専用ビューに変え、create_message 側で admin かつ案件所有者でない場合は403にする。

### L4. 0025_user_suspend が server_default を落としていない
`backend/alembic/versions/0025_user_suspend.py` の upgrade()。
server_default="false" が列定義に恒久的に残り、モデル側 Python default=False と二重管理になる。
SQLite/PG両対応（SQLite の ADD COLUMN NOT NULL に必要な default を供給）と
downgrade（drop_index → drop_column ×3、down_revision="0024_operator_review_stats"、
revision id 18文字＝32文字制限順守）は**いずれも正しい**。
修正案: 既存行の埋め込み後に op.alter_column("users", "is_suspended", server_default=None) を追記。

### L5. _promote_to_admin_if_listed がメールを小文字化せずに比較
`backend/app/api/v1/endpoints/auth.py:56-68`（user.email in get_settings().admin_emails）。
admin_emails は `backend/app/config.py:271-273` で小文字正規化済み。
パスワード経路は `backend/app/api/v1/endpoints/auth.py:149` で lower 済みなので実害は無いが、
LINE経由で作成された User のメールは正規化が保証されない（line_exchange ケース2経路）。
修正案: user.email.lower() で比較する。

---

## 重点項目の判定サマリ

| 重点 | 判定 |
|---|---|
| (1) web/backend 契約一致 | adminListCases/Transactions は項目名・型・null許容・日付形式（datetime→string / date→string）とも**完全一致**。adminSuspendUser（PATCH /admin/users/{id}/suspend、body suspended+reason、応答 id/is_suspended/suspended_at）・submitContactMessage（POST /contact → 202 ok:true）も一致。adminListUsers は項目一致だが**検索仕様のみ不一致（H2）** |
| (2) 401共通処理 | 合格。typeof window === "undefined" ガードでSSR安全、sessionExpiredHandled で二重リダイレクト防止、/operator 判定で役割別ログイン画面へ分岐。line-link.ts の reauth は request() を通らず影響なし（実コード確認済み）。web/src/lib/api.ts はトークン非使用で対象外 |
| (3) /create 保護 | 写真0枚時は beforeunload / popstate とも早期returnで**誤発火しない**。正常送信はSPA遷移のため beforeunload は発火しない。ただし離脱経路にH1、成功後の履歴にM6 |
| (4) 入札409後の再取得 | 合格。operator/cases/[id]/page.tsx は reload で caseData.status 更新→canBid false→フォームが案内文に差し替わる。operator/page.tsx は listOpenCases が open/bidding のみ返すため当該案件が一覧から消える |
| (5) 新設通知 | リンク先ルートは全て実在（/cases/[id] /operator/cases/[id] /operator/transactions/[id] /chat/[id]）。宛先も正しい（減額申請→依頼者、減額決定→申請業者、キャンセル→相手方）。減額申請の回答UIは web/src/app/cases/[id]/page.tsx:699 に実在し、リンク先 /cases/{case_id} と整合 |
| (6) 文言横断整合 | 「入札期間3日」の残存は0件（grep済み・faq/terms/legal とも是正済み）。β注記は主要8箇所に伝播済みだが **H3（operator/chat）と M1（landing/Faq）で漏れ**。通知チャネル文言（notify.py の _wrap 近傍）は faq/page.tsx:113 と整合 |
| (7) alembic 0025 | 合格（L4は運用上の推奨のみ）。単一ヘッド・SQLite/PG両対応・downgrade実装済み |
| (8) ページング境界 | total=0 は正常。offset > total で表示破綻（M4）、tie-breaker欠落（M3） |

---

## 未解決リスク（4件）

### RISK-1. AbortSignal.timeout の実行環境依存が未検証
`web/src/app/create/page.tsx:415` の AbortSignal.timeout(180000) は Safari 16 / iOS 16 以降でのみ利用可能。
LINE内蔵ブラウザ・古いAndroid WebView など主要流入経路で未定義の場合、
createCase 呼び出し時に同期的な TypeError が投げられ、**送信ボタンが即座に失敗**する。
isTimeout 判定（err.cause が DOMException かつ name === "TimeoutError"）も同様に環境依存。
実機（iOS Safari / LINEアプリ内）での確認は本レビューでは未実施 [要確認]。
緩和案: AbortSignal.timeout の存在をガードし、無い環境では AbortController + setTimeout にフォールバックする。

### RISK-2. 依頼者を停止した後の「進行中案件・成約」の扱いが未定義
is_suspended は認証ゲート（deps.assert_user_not_suspended）のみで、案件・成約の状態には一切干渉しない。
停止された依頼者の案件は open のまま業者一覧に残り続け、業者は入札できるが依頼者は
業者選定も辞退も全API 403 で不可能。成約済み案件では業者が訪問予定を持ったまま
相手が消える（キャンセル通知も飛ばない）。運営手順（停止時に案件を cancel し業者へ通知する）
または実装（停止時のカスケード）が未整備。リリース前に運用手順として明文化すべき。

### RISK-3. POST /analyze 認証必須化の影響範囲が「現時点で呼び出し元ゼロ」に依存している
`web/src/lib/api.ts:173` の analyzeImage は web/src 全体で**呼び出し元0件**（grep確認済み）のため
今回の破壊的変更（無認証→認証必須）の実害は現在は無い。しかし同関数はトークンを一切扱わない実装のまま
残っており、将来AI仮査定導線（/analyzing /result /condition 等）を復活させた開発者が
そのまま呼ぶと確実に401になる。外部（他クライアント・LP・監視スクリプト）からの利用有無は
本レビューの可視範囲外 [要確認]。
緩和案: analyzeImage を削除するか、token を必須引数に変更してコンパイル時に気付けるようにする。

### RISK-4. admin_emails 未設定時、問い合わせが202のまま消える運用リスク
`backend/app/api/v1/endpoints/contact.py` は ADMIN_EMAILS 未設定時にWARNINGログのみ出して202を返す
（設計判断としては妥当）。しかし Render の環境変数は render.yaml の envVars が既存サービスに同期されない
既知の性質があるため、**本番で ADMIN_EMAILS が未設定のままリリースされると、
ユーザーには「送信を受け付けました」と表示され続けたまま問い合わせが全損する**。
リリース前に本番 /contact へ1件実送信し、運営受信箱への到達をログ＋実受信で確認すること
（GUI確認ではなく実受信で）。

---

## 末尾サマリ

⚠️ 実行検証は全て緑（pytest 680 passed / tsc 0 / eslint 0 errors）だが、静的レビューで
High 3件（/create 離脱デッドエンド、/admin/users 検索契約不一致、業者向け手数料表示のβ注記漏れ＋実装矛盾）
を検出。いずれも既存テストでは検知不能。
✅ 401共通処理・入札409再取得・新設通知の宛先とリンク先ルート・alembic 0025・
契約項目名の1文字一致（users の検索仕様を除く）は合格。
❌ ブロッカー（Critical）はなし。High 3件の修正と RISK-4（本番 ADMIN_EMAILS 実送信確認）を
リリースゲートに含めることを推奨する。
