# R3 修正差分 QA再検証（前回とは独立・コード無変更）

実施日: 2026-09-04 / 実施者: qa-reviewer（2巡目）
対象外: config.py / main.py / core/alert_middleware.py / services/alerts.py / tests/test_alerts.py

## 総合判定

**条件付き合格**。Critical 0 / High 0 / Medium 5 / Low 4（新規回帰または残存）。
前回 High 3 のうち H1・H2 は塞がった。H3 は**一部**（β注記は追記されたが 8% 予定額の
計算表示が残り、注記と正面から矛盾）。リリース可だが Medium 5 件は本番前に判断が要る。

## 実行検証

| コマンド | 結果 |
|---|---|
| backend/.venv/Scripts/python.exe -m pytest -q | **696 passed**, 0 failed, 643 warnings (172.51s) |
| web> npx tsc --noEmit | **exit 0**（エラー0） |
| web> npx eslint src | **0 errors / 3 warnings**（notifications/page.tsx:191, operator/transactions/[id]/page.tsx:92, signup/page.tsx:59 — 前回と同一の既存warning） |
| next build | 指示により未実行 |

自己申告「696 passed」「tsc/eslint 0エラー」は再現確認済み。

---

## 項目別判定

### QA-H1 /create 離脱モーダル → **塞がった**

`web/src/app/create/page.tsx:216-220` が window.history.go(-2) を廃し
allowLeaveRef.current = true → setLeaveConfirmOpen(false) → router.push("/mypage") に統一。
履歴段数への依存が消えたため、新規タブ・直接アクセス（履歴 index 0）でも確実に離脱できる。
正常送信は `:432-433` で同じく allowLeaveRef を立ててから push しており、popstate ガード
（`:184-189` の allowLeaveRef 早期return）は誤発火しない。写真0枚時の早期return
（`:165` beforeunload / `:186` popstate）も維持。**主目的は達成**。
残る副作用は R-L1（番兵履歴の残存・Low）。

### QA-H2 /admin/users の ID 検索 → **塞がった**

`backend/app/api/v1/endpoints/admin.py:573-575` に _try_parse_uuid(q_norm) →
or_clauses.append(User.id == parsed_id) が追加され、admin_list_cases（`:395`）/
admin_list_transactions（`:490`）と同型になった。ilike も escape 付き（`:570-571`）。
web 側 placeholder は `web/src/app/admin/users/page.tsx:117`「メール／表示名（部分一致）または
ユーザーIDで検索」に修正済みで、UUID厳密一致という実装と文言が矛盾しない
（「前方一致」の語を落としたのは正しい）。CopyableId は常に完全UUIDをコピーするため実用上も一致。
テスト `backend/tests/test_admin_user_controls.py:287`（ID完全一致）/ `:307`（ワイルドカードのエスケープ対照）が回帰を押さえる。
残るのは R-L4（OpenAPI 記述の陳腐化・Low）。

### QA-H3 業者向け手数料表示 → **一部**

`web/src/app/operator/chat/[id]/page.tsx:530` に他画面と1文字一致のβ注記
「※ サービス開始当初（β期間）は手数料を請求しません。請求開始の際は事前にメールでお知らせします。」
が併記された（伝播漏れは解消）。**しかし `:517-519` の表示ロジックは未変更**で、
未完了時は yen(Math.round(amount * 0.08)) +「（予定額・完了時確定）」を計算表示し続ける。
結果、同一カード内に「手数料 8,000円（予定額・完了時確定）」と「請求しません」が同居する。
さらに `backend/app/db/models/transaction.py:40` の fee_amount は default=0 かつ加算実装が
無いままなので、完了後は必ず「手数料 0円」に切り替わる（前回指摘の実装矛盾は未解消）。
前回の修正案「β期間中は予定額を計算せず 0円固定表示」は採られていない。

### 契約一致（403 detail.code / open_case_count / ContactCategory）

| 契約 | 判定 | 根拠 |
|---|---|---|
| 403 detail.code="account_suspended" | **一部** | `backend/app/api/deps.py:79-82` が dict、`web/src/lib/katadzuke-api.ts:615-618` が status===403 かつ detailCode==="account_suspended" で受ける。形は完全一致。ただし①`deps.py:110-111` の assert_operator_not_suspended は**文字列 detail のまま**で非対称（停止業者は共通処理に乗らない）②ログイン経路は R-M1 で機能しない |
| open_case_count の型 | **一部** | backend `backend/app/schemas_katadzuke.py:869` は int（default=0）。web `web/src/lib/katadzuke-api.ts:1629-1632` の AdminUserSuspendResponse に**フィールドが存在せず**、`web/src/app/admin/users/page.tsx:68` も戻り値を捨てている。実行時エラーは無い（additive）が、機能が運営に到達しない |
| ContactCategory Literal vs select value | **完全一致** | `backend/app/schemas_katadzuke.py:1110-1112` の service/pricing/area/privacy/trouble/partner/press/other と `web/src/app/contact/page.tsx:227-234` の8つの option value が順序・綴りとも1文字単位で一致。`:224` の未選択 option は空文字かつ disabled で送信対象外 |

### AbortSignal.timeout フォールバック → **塞がった**

`web/src/lib/katadzuke-api.ts:629-636` に createTimeoutSignal を新設し、
typeof AbortSignal.timeout === "function" で分岐、未対応環境は
AbortController + setTimeout + DOMException("The operation timed out.", "TimeoutError") で abort。
`web/src/app/create/page.tsx:430` が置換済み。呼び出し側の isTimeout 判定
（`web/src/app/create/page.tsx:440-443`）とも DOMException 名で互換。残課題は R-L2（Low）。

### /forbidden ページ → **塞がった**

`web/src/app/forbidden/page.tsx` が実在（not-found.css の nf-* 意匠を流用・新規CSSなし）。
`web/src/middleware.ts:73-76` が needsAdmin かつ role が admin でない場合に /forbidden へ送る。
`web/src/app/login/page.tsx:27-36` に callbackUrl 到達可否ガードが入っており、
/login と /admin の相互リダイレクトループは成立しない（ループ経路を実コードで追跡済み）。
リンクはトップページ1本のみで、権限のあるページ（/cases・/mypage）への導線は無い（許容範囲）。

### 前回 Medium の台帳整合 → **一部**

| 指摘 | 実装 | 台帳記載 |
|---|---|---|
| QA-M1 landing/Faq.tsx 死にコード | 未対応（残存） | `r3-fix-frontend.md:37` に「M1〜M7 その他は対象外のため未着手」と記載あり ✅ |
| QA-M2 admin一覧の deleted_at 除外 | 未対応（`admin.py:565-577` に条件なし） | **backend台帳に記載なし ❌** |
| QA-M3 ページング tie-breaker | 未対応（`admin.py:411` / `:510` / `:583` とも単一キー） | **backend台帳に記載なし ❌** |
| QA-M4 offset > total の逆転表示 | 未対応（`web/src/app/admin/_components/AdminPagination.tsx:19-20`） | frontend台帳:37 に包含 ✅ |
| QA-M5 件名escape・Reply-To | 未対応（`backend/app/services/notify.py:278` の件名 escape / replyTo 無し） | **backend台帳に記載なし ❌** |
| QA-M6 成功送信後の番兵残存 | 未対応（`create/page.tsx:187,197` の番兵を消費しない） | frontend台帳:37 に明記 ✅ |
| QA-M7 テスト網羅性 | 一部（ID検索・escape・open_case_count・Literal・改行許容は追加。停止ユーザーの一般API 403／analyze のアカウント軸429／admin一覧の境界値は依然不在） | frontend台帳:37 に包含・backend台帳は個別テストのみ △ |
| SEC-M2 停止操作の監査ログ | 未対応（`admin.py:670` の logger.info のみ、`:653` で解除時に suspended_reason を None 上書き） | **backend台帳に記載なし ❌** |

`r3-fix-backend.md` は M2/M3/M5・SEC-M2 の未対応を明示していない。台帳の欠落として是正すべき。

---

## 新規回帰（Critical 0 / High 0 / Medium 5 / Low 4）

### R-M1（Medium）停止アカウントがログインすると「パスワードが違う」と誤表示される

- **該当箇所**: `web/src/auth.ts:60`（!res.ok で null を返す）、
  `backend/app/api/v1/endpoints/auth.py` の user_login（assert_user_not_suspended へ統一）、
  `web/src/app/login/page.tsx:63`
- **問題**: backend は停止ユーザーのログインに 403 の dict detail（code=account_suspended）を返すが、
  backendLogin は !res.ok でボディを一切読まず null を返す。NextAuth は CredentialsSignin となり、
  login ページは「メールアドレスまたはパスワードが正しくありません」を出す。
  reason=suspended バナー（`login/page.tsx:85`）は**ログイン済みセッションが 403 を踏んだ場合にしか出ない**。
  L-2 の目的（停止ユーザーに「壊れている」表示を出さない）は**ログイン経路で未達**。
- **再現条件**: admin が依頼者を停止 → 当該依頼者がログアウト状態から /login でメール＋正しいパスワードを入力
  →「メールアドレスまたはパスワードが正しくありません」。本人はパスワードを何度も試す。
- **修正案**: backendLogin で 403 かつ detail.code が account_suspended の場合に専用エラーを throw し、
  authorize から専用 error コードを返す。login/page.tsx:25-27 で分岐して停止案内を出す。

### R-M2（Medium）/contact と POST /cases が同一 IP バケットを共有し相互に 429 で巻き添える

- **該当箇所**: `backend/app/api/v1/endpoints/contact.py:79`（RateLimitGuard の引数が case_create）
- **問題**: スコープ名が文字列一致するため、IP軸バケットが実際の案件作成 API と共有される。
  同一 IP（集合住宅・キャリアNAT・社内NAT）から /contact を数件送ったユーザーが案件作成で 429 になり、
  逆に案件を作成したユーザーが問い合わせできなくなる。429 の文言も「案件の作成が集中しています」で
  /contact の文脈と一致しない。自己申告（`r3-fix-backend.md:39-43`）に既知の制約として記載はあるが、
  **実害は運用可能な範囲を超える**（問い合わせは救済導線であり、案件作成の失敗直後に叩かれる導線でもある）。
- **再現条件**: 同一 IP から POST /cases を10回（またはエラーで再試行）→ /contact が 429。
- **修正案**: config.py 解禁後に contact 専用スコープ（IP 5/3600s・メール 3/3600s）を追加する。
  暫定策としてバケットキーに contact プレフィックスを付けられるなら分離する。

### R-M3（Medium）プロセス内キャップが「実送信通数」基準で、正当な問い合わせを 202 のまま黙って捨てる

- **該当箇所**: `backend/app/api/v1/endpoints/contact.py:40-41,64,95-102,120`
- **問題**: 上限30は**リクエスト数ではなく宛先ごとの送信通数**を数える。ADMIN_EMAILS が2件なら
  実質 15件/時、3件なら10件/時で上限に達する。上限到達後は break で送信をスキップし、
  依頼者には 202 を返し続ける。プレスリリース・SNS拡散・障害発生直後など
  **問い合わせが最も重要な局面で全損**する。ログは WARNING のみで監視項目にも未登録。
- **再現条件**: ADMIN_EMAILS を2件設定 → 異なる IP・異なるメールから /contact を16回送信 →
  16件目は 202 だが運営に届かない（レート制限にも掛からず、ユーザーにも運営にも見えない）。
- **修正案**: 1リクエスト＝1スロット消費に変える。上限到達時は ERROR ログにしてアラート対象にする。
  理想的には未送信分を DB に永続化して後追いできるようにする。

### R-M4（Medium）モジュールグローバル deque がテスト間で共有され、実行順依存の潜在フレークになる

- **該当箇所**: `backend/app/api/v1/endpoints/contact.py:44`、
  リセットは `backend/tests/test_contact.py:132` の1テストのみ（monkeypatch で新しい deque に差し替え）
- **問題**: 他の contact テストおよび `backend/tests/test_rate_limit_api.py` の TestContactRateLimit
  （IP軸10件超・アカウント軸10件超を送る）は deque をリセットせず、同一プロセス内で
  タイムスタンプを積み上げる。ウィンドウは 3600 秒（monotonic 基準）のため**テスト実行中に
  古い要素が消えることはない**。現在 696 passed だが、テストが数件増えるか実行順が変われば、
  30通に到達した以降のテストで送信がスキップされ「メールが送られたこと」の検証が落ちる。
- **再現条件**: contact 系テストを増やして通算送信数が30を超えた時点、または実行順のシャッフル。
- **修正案**: conftest.py に autouse fixture を置き、各テスト前に deque を clear する。

### R-M5（Medium）open_case_count が web に配線されておらず、停止判断の材料が運営に届かない

- **該当箇所**: `backend/app/api/v1/endpoints/admin.py:661-670`（集計と返却）、
  `web/src/lib/katadzuke-api.ts:1629-1632`（型に無い）、`web/src/app/admin/users/page.tsx:68`（戻り値を破棄）
- **問題**: backend は「停止しても案件・成約は自動で止まらない」ことへの運営向け情報として
  open/bidding 件数を返す設計にしたが、web の型にフィールドが無く結果は捨てられている。
  **運営は進行中案件の存在に気付けない**。前回 RISK-2（停止後の案件の扱いが未定義）は実質そのまま。
- **再現条件**: open 案件を2件持つ依頼者を /admin/users で停止 → 画面に何も出ない。
- **修正案**: 型に open_case_count を追加し、停止成功トーストを
  「停止しました（進行中の案件が2件あります。案件側の対応をご確認ください）」に変える。

### R-L1（Low）confirmLeave 後も番兵履歴が残り、戻ると空の /create に着地する

`web/src/app/create/page.tsx:187`（popstate 毎に番兵を再push）、`:197`（初回番兵）、`:219`（router.push）。
go(-2) を廃した副作用で番兵が一切消費されなくなった。モーダルで「ページを離れる」→ /mypage →
ブラウザバック → URL は /create の番兵に着地し**空の作成フォームが再マウント**される。
さらに `:187` はバック操作のたびに番兵を積むため、モーダルを3回開閉すると番兵が3つ溜まる。
修正案: confirmLeave / 送信成功時に history.state の kdzCreateGuard を見て
replaceState で番兵を潰してから遷移する（QA-M6 と同一の修正で両方塞がる）。

### R-L2（Low）createTimeoutSignal の setTimeout が解除されず、Safari 15.3 以前では TimeoutError 判定が成立しない

`web/src/lib/katadzuke-api.ts:632-635`。①戻り値が signal のみのため呼び出し側で clearTimeout できず、
送信成功後も180秒間タイマーが残る（abort 自体は no-op なので実害は軽微だがリークではある）。
②AbortController.abort に理由を渡せるのは Safari 15.4 以降。それ以前では理由が無視され
signal.reason が既定の AbortError になるため、`web/src/app/create/page.tsx:442-443` の
TimeoutError 判定が false になり、専用のタイムアウト案内でなく汎用エラーが出る（劣化のみ・クラッシュはしない）。
修正案: signal と cancel を返す形にし、finally で cancel する。

### R-L3（Low）停止業者の 403 が文字列 detail のままで共通処理に乗らない

`backend/app/api/deps.py:110-111` は detail が文字列「アカウントは停止中です。運営へお問い合わせください。」。
依頼者側だけ dict 化されたため契約が非対称になり、停止業者は自動サインアウトも
停止案内への誘導も発生せず、画面にエラー文字列が出るだけで操作を試み続ける。
修正案: SUSPENDED_ACCOUNT_DETAIL を業者側にも適用し、`katadzuke-api.ts:581-582` の役割判定で
/operator/login への停止案内付き遷移に分岐させる。

### R-L4（Low）admin_list_users の OpenAPI 記述が ID 検索を反映していない

`backend/app/api/v1/endpoints/admin.py:551`（summary「依頼者一覧（admin横断閲覧・メール/表示名で検索可）」）、
`:554`（Query description「メール/表示名の部分一致」）。ID 検索を実装したのに記述が旧のまま。
admin_list_cases / admin_list_transactions の記述と突き合わせて統一すること。

---

## 文言の是正漏れ（横断 grep 結果）

対象語のうち **「LINEにも」「受取先口座」「保証制度」「3日間」は 0 件**（是正済み・残存なし）。
「最高額」は `web/src/app/cases/[id]/page.tsx:566` の入札バッジのみで事実表示、問題なし。
以下が是正漏れ。

| # | file:line | 内容 | 深刻度 |
|---|---|---|---|
| 1 | `web/src/components/landing/Faq.tsx:39` | 「訪問による買取には特定商取引法が適用され、法定書面の交付、**8日間のクーリングオフ**、その期間中の物品引き渡し拒絶権など、消費者としての保護を受けられます。」＝無条件断定。是正後の統一文言（`faq/page.tsx:64` / `legal/page.tsx:176` / `terms/TermsTabs.tsx:104` / `page.tsx:28,306` / `schedule/page.tsx:512`「可否は品目（家具・家電等は対象外）や経緯によって異なる」）と正面から矛盾。import は 0 件＝死にコードだが復活時に特商法リスクが再燃 | Medium（QA-M1 未対応・継続） |
| 2 | `web/src/components/landing/Faq.tsx:23` | 「業者登録は**当面無料**で運用しています」＝成約時8%手数料＋β注記と矛盾 | Medium（同上） |
| 3 | `web/src/app/operator/chat/[id]/page.tsx:519` と `:530` | 「8,000円（予定額・完了時確定）」と「β期間は手数料を請求しません」が同一カード内に同居。さらに完了後は fee_amount 未実装により必ず「0円」 | Medium（QA-H3 残存） |
| 4 | `web/src/app/faq/page.tsx:58` / `web/src/app/privacy/page.tsx:89` / `web/src/app/terms/TermsTabs.tsx:84` | 「古物営業法により、業者は買取の際にお名前・ご住所などを**確認する義務を負う**」を**無条件で断定**。一方 `web/src/app/mypage/identity/page.tsx:376` のみ「買取金額が**1万円以上**の場合のほか、ゲームソフト・CD/DVD・書籍・バイク等の一部の品目は、金額にかかわらず確認の対象」と条件付きで正しく記載。同一法令の説明が4箇所で粒度不一致で、1万円未満の少額買取で身分証提示を求められなかった際に「説明と違う」となる | Low〜Medium |
| 5 | `backend/app/services/notify.py:278,282` | 運営宛メールの件名・本文の「種別」が**英語スラッグ**（pricing / partner 等）で出力される。ContactCategory の Literal 化（SEC M-1対応）の副作用で、web が表示する日本語ラベル（`contact/page.tsx:228`「料金・費用について」等）と不一致。運営の受信箱で内容が読み取りづらい | Low |
| 6 | `backend/app/services/notify.py:278` | 件名に HTML エスケープを適用（Brevo の subject はプレーンテキスト）。Literal 化により実害は消えたが**誤った適用先が残存**し、将来 category を自由入力に戻すと再燃（QA-M5 未対応） | Low |

「メールでお知らせ」は依頼者向け（`cases/[id]/page.tsx:322,542` / `mypage/page.tsx:353` / `faq/page.tsx:113`）が
すべて「LINE連携済みの方はLINEで、未連携の方はメールで」で統一され、業者向け
（`operator/cases/[id]/page.tsx:220`「結果はメールでお知らせします」）は業者にLINE導線が無いため正しい。是正漏れなし。
β注記は `operator/chat/[id]/page.tsx:530` を含む10箇所で1文字一致を確認（`business/page.tsx:54,76,276` /
`faq/page.tsx:33` / `legal/page.tsx:120` / `operator/page.tsx:259` / `operator/profile/page.tsx:698` /
`page.tsx:421` / `terms/TermsTabs.tsx:152`）。伝播漏れは landing/Faq.tsx のみ。

---

## 未解決リスク（4件）

### URISK-1. 本番 ADMIN_EMAILS 未検証のまま、問い合わせ全損の不可視経路が2本になった
`r3-fix-backend.md:20-22` の運用タスク（本番 ADMIN_EMAILS の実測）は**未実施**。
未設定時の 202 黙殺（`contact.py:87-92`）に加え、今回**プロセス内キャップによる 202 黙殺**
（`contact.py:96-102`・R-M3）が追加され、ユーザーにも運営にも見えない全損経路が2本になった。
render.yaml の envVars が既存サービスに同期されない既知の性質と合わせると、
本番で無言の全損が起きる確率は低くない。
**リリースゲート**: 本番 /contact へ1件実送信し、運営受信箱への到達を**実受信で**確認する。
併せて GET /admin/users の q 検索で admin メールに対応する行と role=admin を1回実測する（SEC R-3）。

### URISK-2. fee_amount の加算実装が無いまま「8% 予定額」を業者に提示している
`backend/app/db/models/transaction.py:40` の fee_amount は default=0 で加算コードが存在しない。
`operator/chat/[id]/page.tsx:519` は完了前に 8% を**クライアント側で計算して表示**しているため、
β終了後に請求を開始する際、この表示額を裏付ける確定データがDBに一切残らない。
β期間中に成約した取引の手数料を遡って請求する根拠も無い。
**緩和案**: β期間中は予定額の表示自体をやめ「0円（β期間中は手数料を請求しません）」固定にする。
請求開始時期が決まった段階で fee_amount の確定処理を実装し、表示はDB値のみを出す。

### URISK-3. フロントエンドに自動テストが1件も無く、H1/H3 クラスの回帰を今後も検知できない
今回検証した web 側の修正（離脱モーダル・タイムアウトフォールバック・403合流・
placeholder整合）は**すべて tsc/eslint と目視のみ**で担保されている。
web に Jest/Vitest/Playwright の設定は無く、createTimeoutSignal のような
分岐を含む純粋関数ですら単体テストが無い。次の変更で同じ場所が壊れても緑のままになる。
**緩和案**: 最低限 `web/src/lib/katadzuke-api.ts` の createTimeoutSignal と
throwHttpError（403 dict の分岐）に Vitest の単体テストを入れる。依存が薄く導入コストが低い。

### URISK-4. 停止ユーザーのログイン拒否と /create 離脱の実機挙動が未検証 [要確認]
R-M1（停止ユーザーが「パスワードが違う」と言われる）と R-L1（離脱後のバックで空フォーム）は
いずれもコード読解による判定で、実ブラウザでの確認は本レビューでは未実施。
特に /create は LINE 内蔵ブラウザ・iOS Safari が主要流入経路であり、
AbortController の abort 理由サポート（Safari 15.4 境界）も実機依存。
**緩和案**: 停止ユーザー1件・LINE内蔵ブラウザ1回の手動確認をリリース前チェックに入れる。

---

## 末尾サマリ

✅ 実行検証は全て緑（pytest **696 passed** / tsc exit 0 / eslint 0 errors・3 既存warning）。
QA-H1（離脱デッドエンド）・QA-H2（ID検索契約不一致）・AbortSignal フォールバック・
/forbidden ページとリンク・ContactCategory Literal の1文字一致は**塞がった**。
⚠️ QA-H3 は**一部**（β注記は追記されたが 8% 予定額の計算表示が残り注記と矛盾）。
403 契約は形は一致するが**ログイン経路（`web/src/auth.ts:60`）で機能せず**、
open_case_count は web に未配線。新規 Medium 5 件・Low 4 件。
前回 Medium のうち M2/M3/M5・SEC-M2 は**実装も台帳記載も無い**（`r3-fix-backend.md` の欠落）。
❌ Critical/High のブロッカーは 0 件。ただし URISK-1（本番 ADMIN_EMAILS 実送信確認）と
R-M1（停止ユーザーの誤エラー文言）はリリースゲートに含めることを推奨する。
