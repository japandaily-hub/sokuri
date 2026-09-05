# r10 — 買取業者 導線監査（申込→審査→登録→初入札→成約→訪問→完了→評価）

対象: ローカル main（01c53f8 時点の作業ツリー）。読み取りのみ。
除外: `docs/TODO.md` 01（仮定）・03（意図的未対応）、`.agent-state/audit/r3〜r8` の既起票分は再指摘しない。
判定: 実在確認（該当行の読み取り）済みの High / Medium のみ。

---

## High

### R10-V-H1 / High / (5)(6) 取引一覧・取引詳細・チャット
**事象**: 確定した訪問日時が業者UIのどこにも表示されない。`TransactionDetail` は `visit_date` / `visit_time_slot` を持ち（`web/src/lib/katadzuke-api.ts:243,245`）、`TransactionListItem` も `visit_date` を持つ（同 `:203`）。しかし `formatVisitSchedule`（`web/src/lib/categories.ts:20`）の呼び出しは admin 2件・依頼者 `cases/[id]/page.tsx:848`・`review/page.tsx:171` のみで、**`web/src/app/operator/` 配下は 0 件**（`grep -rn "visit_date\|formatVisitSchedule" web/src/app/operator` → 0 hit）。`/operator/transactions/[id]/layout.tsx:6` は description に「取引の詳細・訪問日程」と謳っている。
**根拠**: `web/src/app/operator/transactions/[id]/page.tsx:165-477`（visit の描画なし）／`web/src/app/operator/transactions/page.tsx:104-130`（同）／`web/src/app/operator/chat/[id]/page.tsx`（同）／`backend/app/services/notify.py:191-200`（「訪問日程が **{visit_date}** に確定しました」→ リンク先 `/operator/transactions/{id}`）
**再現**: 依頼者が候補日を確定 → 業者にメール／LINE で「訪問日程が確定しました」＋`/operator/transactions/{id}` のリンク → 開いても日時はどこにもない。チャットのスクロールバックで `schedule_confirmed` メッセージ本文を探すしかない。取引一覧でも「今日どこへ行くか」が分からない。
**修正案**: `/operator/transactions/[id]` の概要カードに `formatVisitSchedule(txn.visit_date, txn.visit_time_slot)` を「訪問予定」として常設（依頼者 `cases/[id]/page.tsx:848` と同一実装）。取引一覧の `txn-row-meta` にも `visit_date` を追加し、`status==="visiting"` の行を訪問日昇順で見分けられるようにする。

### R10-V-H2 / High / (5) 全業者画面（入金・精算の説明）
**事象**: 買取代金の支払い（当事者間精算・カタヅケは送金しない）の説明が業者UIに **1文字も無い**。`grep -rn "精算|当事者間|入金|支払" web/src/app/operator/ web/src/components/kdz/DisclosureNotice.tsx` → **0 hit**。依頼者側には明示がある（`web/src/app/mypage/bank-account/page.tsx:5` 「カタヅケは買取代金の送金を行わない（当事者間精算）」）。落札した業者は、誰に・いつ・どの手段で代金を払うのか、依頼者が登録した口座を使うのか、現金手渡しか、を画面から知る術がない。`/operator/transactions/[id]` の住所開示カードも `address` と `contact_email` を出すだけ（`web/src/app/operator/transactions/[id]/page.tsx:227-238`）。
**根拠**: 上記 grep 結果／`web/src/app/operator/transactions/[id]/page.tsx:227-238`／`web/src/app/mypage/bank-account/page.tsx:5`
**再現**: 業者として初落札 → 訪問 → 現地で代金を渡す段になって支払方法の定義がどこにもない。手数料8%の記載（`operator/page.tsx:259`・`profile/page.tsx:734`）はあるが、本体代金の流れは無記載。
**修正案**: `/operator/transactions/[id]` の住所開示カード直下と `/operator/chat/[id]` の手数料カード（`operator/chat/[id]/page.tsx:544-555`）に、依頼者側と同一文言で「買取代金は業者と依頼者の当事者間で直接精算します（カタヅケは送金しません）。依頼者が振込を希望する場合は口座を業者へお伝えします」を追加。`/business` の FLOW にも同項を入れる。

### R10-V-H3 / High / (5) 取引詳細（完了操作の主体）
**事象**: 「作業完了の確定は依頼者のみが行える」ことが業者UIに一切書かれていない。backend は明確に 403（`backend/app/api/v1/endpoints/transactions.py:418-422` `"完了確定はユーザー側のみ行えます。"`）。業者の取引詳細には完了に関する説明も導線も無く、評価カードは `txn.status === "completed"` になって初めて現れる（`web/src/app/operator/transactions/[id]/page.tsx:339`）。訪問・搬出を終えた業者は、次に何が起きれば取引が閉じるのか分からないまま `pending`/`visiting` の画面を見続ける。
**根拠**: `backend/app/api/v1/endpoints/transactions.py:406-434`／`web/src/app/operator/transactions/[id]/page.tsx:339`（completed 以外では評価も完了案内も非表示）／同ファイル全体に「完了」の説明文 0 件（`grep -n "完了" web/src/app/operator/transactions/[id]/page.tsx` → 0 hit）
**再現**: 業者が訪問・作業完了 → 取引詳細は「訪問予定」バッジのまま。依頼者が確定操作をするまで無変化で、業者は督促の仕方も知らない。
**修正案**: `active`（pending/visiting）の取引詳細に「作業完了の確定はお客様が行います。完了後にこの画面から評価を投稿できます」を常設。チャットに「お客様に完了確定を依頼する」定型文ボタンを置くとさらに良い。

### R10-V-H4 / High / (1)(2) /business → /operator/signup の接続
**事象**: 申込直後の完了画面が「招待コードでアカウントを作成」CTA で `/operator/signup` へ誘導する（`web/src/app/business/page.tsx:723-727`）。しかし招待コードはこの時点では未発行（承認後にメール）。`/operator/signup` は招待コード **任意** で登録できてしまう（`web/src/app/operator/signup/page.tsx:62-69`・backend `auth.py:323,349`）ため、申込者がそのまま登録すると同一メールの `Operator`（`vendor_status="pending"`）が先に生成される。その後、運営が同じ申込を承認しようとすると `backend/app/api/v1/endpoints/admin.py:1252-1261` の重複メール検査で **409「このメールアドレスの業者アカウントは既に存在します。招待コードは発行していません。」** となり、当該 `OperatorApplication` は `status="received"` のまま**永久に承認できない**（`reject` 以外の遷移が無い）。
**根拠**: `web/src/app/business/page.tsx:714-731`／`web/src/app/operator/signup/page.tsx:24,63,110-133`／`backend/app/api/v1/endpoints/auth.py:322-349`／`backend/app/api/v1/endpoints/admin.py:1243-1261`
**再現**: 1) `/business` から申込（`received`）→ 2) 完了画面の「招待コードでアカウントを作成」を押す → 3) `/operator/signup` でコード空欄のまま同じメールで登録（成功・pending）→ 4) 運営が `/admin/operator-applications` で承認 → 409。申込は宙に浮き、業者側は招待コードを待ち続ける。
**修正案**: 完了画面の CTA を「招待コードが届いたらこちらから本登録」の**説明テキスト**に変え、リンクは出さない（または `?from=application` を付けて signup 側で「招待コードの到着をお待ちください」を表示）。加えて admin の 409 分岐で「既存業者アカウントに紐付ける」操作（`application.operator_id` を埋めて `approved` にする）を用意し、詰みを解消する。

---

## Medium

### R10-V-M1 / Medium / (4) 案件詳細の入札フォーム
**事象**: `/operator/cases/[id]` の入札フォームは、ダッシュボードの入札モーダルと機能が非対称。ダッシュボードは `BID_MIN/BID_MAX/BID_STEP` の事前検証と `BID_RANGE_HINT`（`web/src/app/operator/page.tsx:53-56,246-247,263`）と手数料8%・β注記（同 `:259-261`）を持つが、案件詳細側は `min={1000} step={1000}`（`web/src/app/operator/cases/[id]/page.tsx:270-271`）だけで **max 無し**、JS 検証も `value <= 0` のみ（同 `:93-97`）、手数料の記載も無い（`grep -n "8%" web/src/app/operator/cases/[id]/page.tsx` → 0 hit）。1億超を入力すると backend の `le=100_000_000` で 422 になるが、`throwHttpError` は `detail` が配列の FastAPI バリデーションエラーを拾えず（`web/src/lib/katadzuke-api.ts:724-735` は string と object のみ分岐）、`toDisplayMessage`（同 `:2103-2105`）が `HTTP 422` をプレースホルダ判定して **「入札に失敗しました」** だけを出す。TODO 03 の「入札額は事前検証で回避中」はこの画面では成立していない。
**再現**: `/operator/cases/{id}` で `200000000` を入力 → 送信 → 原因不明の「入札に失敗しました」。
**修正案**: ダッシュボードと同じ `BID_MIN/BID_MAX/BID_STEP` 検証・レンジヒント・手数料8%（β無料注記つき）を案件詳細のフォームにも展開する。定数は `lib` へ切り出して二重定義を避ける。

### R10-V-M2 / Medium / (6) ダッシュボードの集計
**事象**: 「今月の成約」が `status === "visiting" || "completed"` だけを数え、**`pending`（訪問日調整中）を除外**している（`web/src/app/operator/page.tsx:417-427`）。落札直後の取引は全て `pending` なので、今月3件落札して全て日程調整中の業者には「今月の成約 0件」と出る。同じ取引は隣の「交渉中」カードには 3件として計上される（同 `:401-403`）ため、同一画面内で矛盾する。
**再現**: 新規業者が入札→依頼者が選定（成約）→ ダッシュボードの「今月の成約」は 0 件のまま、「交渉中」は 1 件。
**修正案**: 「今月の成約」を `pending/visiting/completed`（＝キャンセル以外）で数え、`sum-sub` を「うち完了 N 件・買取総額 ¥X（完了分のみ）」に整える。または見出しを「今月の訪問予定・完了」に改める。

### R10-V-M3 / Medium / (6) ダッシュボードの集計（切り詰め）
**事象**: KPI 4枚は `listOpenCases` / `listTransactions` の **先頭 100 件**（`LIST_DEFAULT_LIMIT = 100`・`web/src/lib/katadzuke-api.ts:1530`）だけをクライアントで集計しており（`web/src/app/operator/page.tsx:317-333, 405-437`）、`hasMoreTxns` が true でも KPI 側には切り詰めの表示が無い。案件一覧側には「※ 絞り込みは読み込み済みのN件が対象です」という注記がある（`web/src/app/operator/cases/page.tsx:225-229`）のに、ダッシュボードの数字には同等の注記が無い。
**再現**: 取引が 100 件を超える業者のダッシュボードで「交渉中」「成約済み」タブのバッジと KPI が実数より小さく出る。数字を根拠に業務判断すると誤る。
**修正案**: `hasMoreTxns` が true の間は KPI に「（読み込み済み N 件時点）」を添える。恒久的には backend に業者向けの集計エンドポイント（または `GET /transactions` の `{items,total,counts}` 化）を用意し、admin の業者一覧（r5 で counts 方式に移行済み）と同じ形にそろえる。

### R10-V-M4 / Medium / (5) 取引詳細の減額申請
**事象**: 減額申請の上限は「1取引につき2回」（`backend/app/api/v1/endpoints/reductions.py:35,109-112`）だが、業者UIは上限も残回数も一切表示せず、`active && !pendingReduction` の条件でフォームを出し続ける（`web/src/app/operator/transactions/[id]/page.tsx:278`）。3回目は入力→確認モーダル「申請する」まで進んでから 409「減額申請は1つの取引につき2回までです。」で弾かれる。r8-M3 の修正案が求めた UI 側（残り申請回数の表示）が未実装。
**再現**: 減額申請 → 依頼者が却下 → 再申請 → 却下 → 3回目のフォームがまだ出る → 送信して初めて 409。
**修正案**: `txn.reduction_requests.length >= 2` でフォームを出さず「減額申請は1取引につき2回までです（2回使用済み）」を表示。1回目送信後は「残り1回」を注記する。

### R10-V-M5 / Medium / (8) 通知チャネル（業者の LINE 連携）
**事象**: backend は業者の LINE 連携を実装済み（`backend/app/api/v1/endpoints/auth.py:701-745` で `operator.line_user_id` を付与、`notify_dispatch.py` の各 `dispatch_*` は LINE 優先）だが、**web に業者用の連携導線が存在しない**。連携UIは `/notifications` の1箇所のみ（`web/src/app/notifications/page.tsx:212,228` → `/api/line/link/start`）で、`/notifications` は依頼者専用の保護ルート（`web/src/lib/protected-routes.ts:26`・`web/src/middleware.ts:73-81` で業者セッションは `/forbidden?reason=account_type`）。`OperatorHeader` のベルも `/operator/transactions` へ向く（`web/src/components/kdz/OperatorHeader.tsx:79`）。それでいて入札完了メッセージは「結果はLINE連携済みならLINE、未連携ならメールでお知らせします」と案内する（`web/src/app/operator/cases/[id]/page.tsx:221`）。
**再現**: 業者が LINE で受け取りたいと思っても、全画面を探しても連携ボタンが無い。文言だけが LINE を示唆する。
**修正案**: `/operator/profile` に LINE 連携セクションを追加（`/api/line/link/start` は accountType を見て operator トークンで `/auth/line/exchange` を叩けるよう分岐）。実装しない判断なら `operator/cases/[id]:221` の文言を「結果はメールでお知らせします」に戻す。

### R10-V-M6 / Medium / (9) 文言揺れ（落札／成約・取引／案件）
**事象**: 同一オブジェクト（`Transaction`）が画面ごとに別名で呼ばれる。取引一覧は「落札した案件」「落札額」（`web/src/app/operator/transactions/page.tsx:79,98,99,108`）、取引詳細は「成約情報」「この成約では申請できません」「この成約をキャンセルする」（`web/src/app/operator/transactions/[id]/page.tsx:135,322,341 付近`）、ダッシュボードのタブは「成約済み」で見出しは「今月の成約」（`web/src/app/operator/page.tsx:478,534`）、案件一覧のチップは「落札」（`web/src/app/operator/cases/page.tsx:38`）。ナビのラベルは「取引」（`web/src/components/kdz/OperatorHeader.tsx:16`）。r3 で「落札管理→取引」に統一した方針が本文コピーまで及んでいない。
**再現**: 業者がヘッダーの「取引」を押す → 見出しは「取引一覧」だが本文は「落札した案件」、その詳細は「成約」。同じものと気付くのに一拍かかる。
**修正案**: 用語表を1本に決める（推奨: イベント＝「成約」、オブジェクト＝「取引」、金額＝「成約額」）。`落札` は入札結果チップ（`operator/cases/page.tsx:38`）にのみ残し、他は「成約」へ統一する。

---

## 通しで追った結果の一覧（申込→評価）

| # | ステップ | 結果 |
|---|---|---|
| 1 | `/business` 申込フォーム | 必須14項目（会社名・代表者名・登記住所・担当者・メール・電話・法人/個人・エリア・許可番号・口座5項目）を `REQUIRED_KEYS`（`business/page.tsx:135-151`）で検証。口座の用途注記あり（`:572`）。手数料8%＋β無料注記は5箇所で一貫。**⚠️ 完了画面の CTA が詰みを生む（H4）** |
| 2 | 受付メール → 承認メール（招待コード） | `notify.py:222-233`（受付）／`:246-262`（承認・コード＋`/operator/signup` リンク）。admin 宛アラートも送信（`operator_applications.py:161-164`）。✅ |
| 3 | `/operator/signup` → 登録直後 | 招待コードあり＝`active`、無し＝`pending`（`auth.py:349`）。登録後 `/operator/cases` へ push（`signup/page.tsx:72`）。pending は `ApprovalPendingNotice` で「許可証の画像が必要」と具体案内（`ApprovalPendingNotice.tsx:21-31`）。**⚠️ signup の docstring `:6` は "limited" と書くが実装は "pending"（表記のみ）** |
| 4 | 審査中の閲覧と制限 | 案件の閲覧は可・入札不可を middleware ではなく backend `get_verified_operator` で担保（`middleware.ts:16-19`）。バナーはダッシュボード／案件一覧／案件詳細の3画面に出るが `/operator/transactions`・`/operator/profile` には出ない（低）。✅ |
| 5 | 承認通知 → 入札解禁 | `send_operator_verified`（`notify.py:389-416`）が LINE 優先で「入札のご利用が可能になりました」＋`/operator/cases`。✅ |
| 6 | 案件一覧の情報量 | 写真4枠（商品アルバム優先）・品目要約・都道府県/市区・作成日・商品点数・入札件数・自社入札額（`cases/page.tsx:47-114`）。エリア絞り込みと未入札フィルタあり、読み込み済み件数の注記あり。**AI要約は一覧に無く詳細のみ（`cases/[id]:216-221`）** ✅ |
| 7 | 入札フォーム | ダッシュボード＝範囲検証＋手数料注記あり。**⚠️ 案件詳細＝どちらも欠落（M1）** |
| 8 | 入札後の待ち状態 | `bidDone` の成功アラート＋「自社の入札」カード（金額・ステータスチップ・メッセージ）。1案件1回制限を明記。✅ |
| 9 | 落札 → 住所開示 | `dispatch_bid_selected` → `/operator/transactions/{id}`。`DisclosureNotice` と `decided-card` に住所＋`contact_email`（`transactions/[id]:227-238`）。氏名・電話は非開示で実装と整合。✅ |
| 10 | チャット → 候補日提案 → 確定 | 業者から候補日提案可、終了取引はガード済み（`operator/chat/[id]:290,392-398`）。確定通知は業者へ届く。**⚠️ 確定日時が画面に出ない（H1）** |
| 11 | 当日 → 減額申請 | 理由10文字以上・確認モーダル・履歴表示・pending中は再申請不可。**⚠️ 上限2回の表示なし（M4）** |
| 12 | 完了 | 依頼者のみが確定（`transactions.py:418-422`）。**⚠️ 業者側に説明ゼロ（H3）** |
| 13 | 評価 | 完了後に業者→依頼者の評価投稿カード。自社が受けた口コミは `/operator/profile:619,660` で常時確認可。✅ |
| 14 | 入金 | **❌ 説明が業者UIに存在しない（H2）** |
| 15 | 取引一覧・未読・ページング | 未読バッジ・減額申請中・依頼者停止中チップ、`limit/offset` の「さらに読み込む」あり。**⚠️ 訪問日と KPI 精度（H1・M2・M3）** |
| 16 | プロフィール編集 | 対応エリア・取扱/得意カテゴリ・人員・営業時間・自己紹介・公開スイッチ・許可番号（読取専用）・許可証画像アップロード（事前検証あり）・退会。公開プロフィールは `/vendors/[id]`。✅ |
| 17 | 通知リンクと未ログイン | 業者宛リンクは全て `/operator/...`（`notify.py:163,178,194,279,397,407`・`line_notify.py:94,114,140,187,252`）。未ログイン時は middleware が `/operator/login?callbackUrl=<path>` へ送り、login 側は `/operator` 配下のみ許可（`operator/login/page.tsx:30-34`）。✅ |
| 18 | モバイル | `OperatorHeader` は 920px 以下で展開メニュー内にログアウトを再掲（`OperatorHeader.tsx:64-76`）。r9 の a11y 実測で業者5ページ検査済み。✅ |
| 19 | 文言揺れ | **⚠️ 落札/成約・取引/案件が混在（M6）** |

---
判定サマリ: **High 4 / Medium 6**。最も業務に効くのは H1（訪問日時が業者に見えない）と H2（代金の払い方が業者に書かれていない）。H4 は運営側が承認不能になる詰みを生むため、CTA の変更だけでも先に入れる価値がある。
