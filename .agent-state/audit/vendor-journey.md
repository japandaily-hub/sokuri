# カタヅケ 業者導線UX監査台帳（2026-09-03）

対象ルート順: /business → /operator/signup → /operator/login → /operator（ダッシュボード）→ /operator/cases → /operator/cases/[id] → /operator/chat/[id] → /operator/transactions → /operator/transactions/[id] → /operator/profile → /vendors/[id]

権限ゲートは `vendor_status`（"pending"|"active"。"limited"はレガシー値でauth.pyでは発生しない）。`verified_at` は古い手動承認フィールドであり、admin検証エンドポイント経由（vendor_status連動）以外の経路では乖離しうる点に注意（下記 H-3 は実コードで乖離を確認済み）。

---

## High以上（優先度順・最大12件、7件確認）

### H-1. /business 申込完了画面のCTAが「業者ログインへ」だが、この時点でログイン用アカウントは存在しない
- ルート: `/business`
- file:line: `web/src/app/business/page.tsx:715-732`（特に725-728）／根拠: `backend/app/api/v1/endpoints/operator_applications.py:112-131`（`OperatorApplication`はリード情報のみ保存、`password_hash`等のOperatorアカウントは作成しない）／承認メールの正しい導線: `backend/app/services/notify.py:181-194`（`/operator/signup` + 招待コード）
- 現状: フォーム送信は `POST /operator-applications` に申込データを保存するだけ。送信後の「お申し込みを受け付けました」画面は `<Link href="/operator/login">業者ログインへ</Link>`（page.tsx:725-728）を主要CTAとして表示し、「審査通過後、ダッシュボードから案件への入札が始められます」（page.tsx:721-723）とだけ案内する。
- 問題: 申込者はメール/パスワードを持たない（アカウント未作成）ため、このボタンを押すと必ずログインに失敗する。実際の正しい次アクションは、承認メール（招待コード付き）を受け取ってから `/operator/signup` で本登録すること。画面内の案内文には招待コード取得〜本登録という中間ステップの言及が一切ない。
- 修正案: サンクス画面のCTAを削除するか `/operator/signup` への案内（「承認メールに記載の招待コードでアカウントを作成してください」）に差し替える。案内文に「審査結果は3営業日以内にメールでご連絡します（承認時は招待コードをお送りします）」を明記する。

### H-2. ダッシュボード／案件一覧の「審査待ち」バナーが実質デッドコードで、pending業者に状態が伝わらない
- ルート: `/operator`, `/operator/cases`
- file:line: `web/src/app/operator/page.tsx:260-279,387-401`／`web/src/app/operator/cases/page.tsx:119-152`／根拠: `web/src/lib/katadzuke-api.ts:769-771`（`listOpenCases`は`GET /cases`を叩く）／`backend/app/api/v1/endpoints/cases.py:281-293`（コメント「案件の閲覧はvendor_statusを問わず許可（pending/limited/active いずれも可）」で、業者向けlist_casesは200を返す。403は発生しない）
- 現状: 両ページとも `listOpenCases()` の catch で `e.status === 403` を判定して `pendingApproval` バナーを出す実装だが、このエンドポイントはpending業者にも常に200を返すため到達不能。
- 対比: `web/src/app/operator/cases/[id]/page.tsx:70-75,124-126,230-233` は `getOperatorProfile()` の `vendor_status` を明示取得してフォーム出し分けをしており正しい。3画面で実装方針が割れている。
- 影響: pending業者はダッシュボード/一覧を見ても審査中と気づかず、入札を試みて初めて403トーストで知る（H-4関連）。審査観点①に直結する欠陥。
- 修正案: dashboard/cases一覧も `/operator/cases/[id]` と同じパターン（`getOperatorProfile().vendor_status` を取得してバナー表示）に統一する。

### H-3. プロフィールの審査バッジが `verified_at` 依存で、招待コード登録の稼働業者が永久に「審査中」表示になる
- ルート: `/operator/profile`
- file:line: `web/src/app/operator/profile/page.tsx:227,337-343,526-533`／根拠: `backend/app/api/v1/endpoints/auth.py:212-222`（招待コードありは`vendor_status="active"`即時付与だが`verified_at=None`のまま。コメント「admin approveで更新」）／`backend/app/api/v1/endpoints/admin.py:165-179`（`verified_at`が更新されるのはこのadmin手動検証エンドポイントのみ）
- 問題: 招待コードで登録した業者はvendor_status=activeで即入札可能だが、`verified_at`は誰も更新しない限りnullのまま。プロフィール画面は`verified_at`の有無だけで「確認済み／審査中」を出し分けるため、実際は稼働中の業者が恒久的に「審査中」バッジ（line343）・「審査中」ステータス（line531）を表示し続け、実態と矛盾する。
- 修正案: バッジ判定を`verified_at`ではなく`vendor_status === "active"`に変更する。

### H-4. ダッシュボードの「入札額を更新する」ボタンは常に失敗する（更新APIが存在しない）
- ルート: `/operator`
- file:line: `web/src/app/operator/page.tsx:127-129,189-224`／根拠: `web/src/lib/katadzuke-api.ts:827-837`（`createBid`は`POST /cases/{id}/bids`のみ）／`backend/app/api/v1/endpoints/bids.py:125-137`（既存入札があれば理由を問わず409「この案件には既に入札済みです。」。PATCH/PUT等の更新系エンドポイントは存在しない）
- 現状: `lot.myBid`がある場合、送信ラベルが「入札額を更新する」（line127）になり金額変更→送信を促すが、実行される処理は新規`createBid`と同一で必ず409になる。
- 矛盾: `web/src/app/operator/cases/[id]/page.tsx:240`は同じ入札行為について「入札は1案件につき1回のみです。」と正しく案内しており、ダッシュボードのラベル・挙動と直接矛盾する（審査観点④の一覧⇔詳細不一致に相当）。
- 修正案: `lot.myBid`がある場合は入札フォームを非表示にし、「入札済み・金額変更不可」の案内に統一する（cases/[id]と同じ扱い）。

### H-5. 業者チャット画面のヘッダーに主要ナビとログアウト導線が無く、業者が孤立する
- ルート: `/operator/chat/[id]`
- file:line: `web/src/app/operator/chat/[id]/page.tsx:270-291`／対比: `web/src/components/kdz/OperatorHeader.tsx:44-115`（ダッシュボード/案件一覧/取引/プロフィールのナビ+ログアウトボタンを持つ共通ヘッダー）
- 現状: チャット画面は独自の`ch-header`を描画し、OperatorHeaderのナビもログアウトボタン（OperatorHeader.tsx:94-100 `signOut`）も持たない。戻る矢印は`/operator/cases`固定、ベルは`/operator`固定リンクのみ。
- 問題: チャット中にログアウトしたい場合、いったん他ページへ遷移しないとできない。取引詳細（住所・手数料確認）や案件詳細への直接導線も無い。審査観点⑦「業者ヘッダーと依頼者ヘッダーの混在・ログアウト導線」に該当。
- 修正案: `ch-header`にログアウトボタンを追加する、または可能ならOperatorHeader自体を流用する。

### H-6. 入札金額の上限（1億円）がフォームに表示されず、超過時のエラーが意味不明になる
- ルート: `/operator`, `/operator/cases/[id]`
- file:line: `web/src/app/operator/page.tsx:196-207`（`min={1000} step={1000}`のみでmax属性なし）／`web/src/app/operator/cases/[id]/page.tsx:248-258`（同様）／`backend/app/schemas_katadzuke.py:444`（`amount: int = Field(gt=0, le=100_000_000)`）／`web/src/lib/katadzuke-api.ts:504`（`if (typeof body.detail === "string")`でpydanticのエラー配列は無視される）／`web/src/lib/katadzuke-api.ts:1054-1064`（`/^HTTP \d+$/`検出時はfallback文言に置換）
- 現状: 両フォームともmax指定・上限ヒントが無い。1億円超で送信するとFastAPIは422（detailはオブジェクト配列）を返すが、フロントは文字列以外のdetailを捨てるため`message`が`"HTTP 422"`のままとなり、`toDisplayMessage`が汎用フォールバック文言（例:「入札に失敗しました」）に置き換える。業者は上限超過が原因と分からない。
- 修正案: `max={100000000}`とヒント文言（「上限1億円」）を追加し、クライアント側で事前検証する。

### H-7. プロフィールの「対応エリアの案件のみ入札対象として表示されます」という案内が事実と異なる（エリアフィルタ未実装）
- ルート: `/operator/profile`, `/operator/cases`
- file:line: `web/src/app/operator/profile/page.tsx:462-463`／根拠: `backend/app/api/v1/endpoints/cases.py:281-293`（業者向け`list_cases`は`Case.status.in_(["open","bidding"])`のみで絞り込み、Operatorの`areas`/`service_area`によるフィルタは一切実装されていない）
- 問題: プロフィール画面の案内文は「対応エリアの案件のみ入札対象として表示されます」と明言するが、実際は全国どの案件も一覧に出て入札できる。業者はエリア外案件が来ないと誤認し、後から現地対応不可で成約後キャンセル（`web/src/app/operator/transactions/[id]/page.tsx:306`「業者都合のキャンセルは記録され、アカウント評価に影響します」）に繋がりうる。
- 修正案: エリアフィルタを実装するか、実装しないなら虚偽の機能説明である当該案内文を削除・訂正する。

---

## Medium以下（件名のみ・最大10件）

1. `/business` 内で審査所要日数の表記が不一致（FAQ「通常5営業日以内」`business/page.tsx:81` vs 送信前後の注記「3営業日以内」`business/page.tsx:711,721`）
2. `/operator/chat/[id]` の戻る矢印が常に`/operator/cases`固定で、`/operator/transactions`経由で来た場合に文脈が失われる（`chat/[id]/page.tsx:273`）
3. `/operator/cases` 一覧にエリア・カテゴリ等の絞り込み/並び替えUIが無い（`cases/page.tsx`全体）
4. 案件カードに締切・経過日数の表示が無く、いつまでに入札すべきか分からない（データモデル自体にdeadline系フィールドが存在しない）
5. `OperatorHeader`の通知ベルが常に`/operator/transactions`固定リンクで、対応必要件数の数値バッジが無くドット表示のみ（`OperatorHeader.tsx:67-83`）
6. `/operator/signup` の招待コード欄がデフォルト折りたたみ表示で、招待コード保有ユーザーが見落とす可能性（`signup/page.tsx:110-133`）
7. 減額申請フォームの下限が「1円」まで許容されており、極端な減額申請が入力レベルで防げない（`transactions/[id]/page.tsx:266-274`）
8. `/vendors/[id]` のエラー画面「マイ案件一覧に戻る」リンクが依頼者導線（`/cases`）のみで、業者が閲覧した場合の戻り先が用意されていない（`vendors/[id]/page.tsx:66-71`）
9. ダッシュボードの「今月の成約」集計が`visiting`（訪問予定・未引取）と`completed`を合算しており、実際の入金確定件数と誤解されうる用語（`operator/page.tsx:299-320`）
10. `/business`登録要件セクションにエリア外事業者向けの案内（対応予定表明・待機リスト等）が無く、要件を満たさない閲覧者がそのまま離脱する（`business/page.tsx:354-376`）

