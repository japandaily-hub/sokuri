# カタヅケ 業者導線 監査台帳（第3周・2026-09-04）

対象: /business /operator/signup /operator/login /operator /operator/profile /operator/cases /operator/cases/[id] /operator/chat/[id] /operator/transactions /operator/transactions/[id] /vendors/[id]
前提: `vendor-journey.md`（H-1〜H-7）・`verify-vendor.md`（全件CONFIRMED済み）・`review-qa.md` の既指摘は再指摘しない。本台帳は同一シンボルを grep 済みの上で未捕捉の欠陥のみを起票する。

---

## High

### R3-H1. セッション失効時、業者画面に英語の生エラー文言がそのまま表示され、再ログイン導線もない
- 画面: `/operator` `/operator/cases` `/operator/cases/[id]` `/operator/chat/[id]` `/operator/transactions` `/operator/transactions/[id]` `/operator/profile`（業者の全認証必須画面）
- 事象: JWTが失効・無効（ログアウト漏れの旧トークン、長時間放置後の再操作、パスワード変更後の旧セッション等）な状態で業者がAPIを叩くと、バックエンドは401 `"Invalid credentials. Please log in again."`（英語固定文言）を返す。フロントの共通エラー変換 `toDisplayMessage` は5xx以外・空文字/`HTTP \d+`以外のdetailをそのまま画面表示するため、日本語UIの業者画面に突然英語の生エラーが出る。加えて、この401をトリガーに `/operator/login` へ自動遷移させる処理はweb/src/app/operator配下のどこにも存在しない（業者は英語メッセージを見たまま同じ画面に留め置かれる）。
- 根拠 file:line:
  - `backend/app/api/deps.py:21-25`（`_CRED_EXC = HTTPException(..., detail="Invalid credentials. Please log in again.", ...)`。`get_current_user`/`get_current_operator`/`get_current_actor` 全てがこの例外を共有・使用）
  - `web/src/lib/katadzuke-api.ts:1415-1424`（`toDisplayMessage`: `err.status >= 500` のみフォールバック文言に置換。401はこの分岐を通らず、`detail.trim()` が空でも `/^HTTP \d+$/` でもない限り**そのまま**返す）
  - `web/src/app/operator/page.tsx:301-311`（`listOpenCases`/`listTransactions` 失敗時 `setError(toDisplayMessage(e, ...))` のみ。401判定・ログイン誘導なし）
  - grep確認: `grep -rn "401" web/src/app/operator/` はヒット0件（業者画面側に401専用ハンドリングが一切存在しないことを確認済み）
- 再現手順: 1) 業者としてログイン 2) DevTools等でlocalStorage/sessionのトークンを破損させる（または長時間経過でJWT exp切れ相当を再現）3) `/operator` を再読み込みし案件一覧取得が走る 4) 画面上部のエラー表示に "Invalid credentials. Please log in again." がそのまま出る（日本語文言に置き換わらない）。ページ遷移しても再ログインへは誘導されない。
- 修正案: `katadzuke-api.ts` の `request()` 共通層で401検知時に (a) 日本語フォールバック文言（例:「セッションが切れました。再度ログインしてください。」）へ強制的に差し替える、(b) `/operator/login`（またはユーザー側は`/login`）へ自動リダイレクトする処理を追加する。バックエンド側の英語文言自体も日本語化が望ましいが、フロント側の防御だけでも即効性がある。

### R3-H2. 減額申請の承認／却下結果が業者に一切通知されず、発見手段は該当取引詳細ページの手動再訪のみ
- 画面: `/operator/transactions`（一覧）, `/operator/transactions/[id]`（詳細）
- 事象: 依頼者が減額申請を承認／却下しても、業者へのメール・LINE通知は一切発生しない（`decide_reduction` にnotify呼び出しが無い）。一覧ページの「減額申請中」バッジと`OperatorHeader`の注意ドットは `has_pending_reduction`（=`status==="pending"`のみ）を根拠にしており、決定された瞬間に静かに消える。詳細ページ側もポーリング等の自動更新は無く、業者が偶然そのページを再訪しない限り、承認されたのか却下されたのかを知る手段が存在しない。承認された場合は最終成約額（`final_amount`）が変わるため、業者が古い金額のまま現地対応・請求してしまうリスクに直結する。
- 根拠 file:line:
  - `backend/app/api/v1/endpoints/reductions.py:103-132`（`decide_reduction`: `session.commit()` のみでnotify/dispatch呼び出しなし）
  - `backend/app/services/notify_dispatch.py:71-` に定義された `dispatch_*` 関数一覧（`grep -n "def dispatch_"` の結果、reduction関連の関数が存在しないことを確認済み）
  - `web/src/app/operator/transactions/page.tsx:45,92`（`attentionCount`/バッジは `has_pending_reduction` のみを見る。決定後は`false`になり無表示化）
  - `web/src/app/operator/transactions/[id]/page.tsx:145,170`（`pendingReduction`/`hasAttention`も同様に`status==="pending"`限定。ポーリング・`setInterval`・`useEffect`による自動再取得は本ファイルに存在しない＝grep確認済み）
- 再現手順: 1) 業者が成約案件で減額を申請（`POST /transactions/{id}/reduction`）2) 依頼者が承認または却下（`PATCH .../reduction/{reduction_id}`）3) 業者はメール・LINEいずれも受け取らない 4) `/operator/transactions` 一覧の該当行から「減額申請中」バッジが消え、ヘッダーの注意ドットも消灯 5) 業者が能動的にその取引の詳細ページを開かない限り、承認額での対応が必要なことに気づけない。
- 修正案: `decide_reduction` に `notify_dispatch.dispatch_reduction_decided`（新設）を追加し、承認/却下いずれもLINE優先→メールフォールバックで業者へ通知する（`dispatch_bid_selected`等と同型）。あわせて `TransactionListItem` に「直近decidedのreduction」有無フラグを足し、一覧上でも「減額の回答があります」等の一時的な案内を出すとより堅牢。

---

## Medium

### R3-M1. 入札金額の8%手数料という規約上の断定と、実装が常にfee_amount=0である実態が矛盾しており、β期間の説明が業者向け画面のどこにも無い
- 画面: `/business` `/operator/profile` `/operator/chat/[id]`（取引パネル）、`/terms`（利用規約タブ）
- 事象: `/business`・`/operator/profile`・`/terms` はいずれも無条件に「成約時のみ買取金額の8%が手数料」と表示・規約化しているが、成約(select_bid)確定時に `fee_amount` は常に `0` で作成され、これを事後に8%相当へ更新するコードはbackend全体に存在しない（grep確認済み・テスト以外の参照なし）。結果として `/operator/chat/[id]` の取引パネルは、進行中は「予定額（final_amount×8%・完了時確定）」を表示するのに、実際に `status==="completed"` になった瞬間 `detail.fee_amount`（常に0円）を表示し、業者からは「8%取られるはずが¥0円のまま」に見える。βの手数料無料方針自体は`docs/beta-operator-onboarding.md`にのみ存在し、規約(`/terms`)・登録要件(`/business`)・プロフィール(`/operator/profile`)・取引画面のいずれにも「β期間中は無料」という説明が一切無いため、業者は規約と実際の請求額の不一致に困惑しうる。
- 根拠 file:line:
  - `backend/app/api/v1/endpoints/bids.py:277`（`fee_amount=0`。成約作成時点で固定）
  - `backend/app/api/v1/endpoints/transactions.py:220-246`（`complete_transaction`: `final_amount`と`status`のみ更新、`fee_amount`の再計算なし）
  - `web/src/app/operator/chat/[id]/page.tsx:515-520`（`status==="completed"` 分岐で `yen(detail.fee_amount)` をそのまま表示、それ以外は `final_amount×0.08` の予定額を表示 — 完了後に表示元が切り替わり数字が食い違う）
  - `web/src/app/terms/TermsTabs.tsx:144-147`、`web/src/app/business/page.tsx:43,54,76`、`web/src/app/operator/profile/page.tsx:697` （いずれも無条件「8%」表記。「β期間中無料」の文言はgrep 0件）
  - `docs/beta-operator-onboarding.md:35`（「手数料は無料です（β期間中）」— 招待メール本文にのみ存在し、アプリ内画面・規約に反映されていない）
- 再現手順: 1) 業者が成約→訪問→完了まで進める（`POST /transactions/{id}/complete`）2) `/operator/chat/[id]` を開く 3) 完了前は「¥xxx（予定・完了時確定）」と表示されていたのが、完了後は「¥0」に切り替わる。同時に `/terms` や `/business` は8%課金を明言したまま。
- 修正案: (a) β期間中は無料である旨を `/terms`・`/business`・`/operator/profile` に明記し、`/operator/chat/[id]` の完了後表示との整合を取る。(b) 本課金運用開始時に備え、`complete_transaction`（またはselect_bid時点）で`fee_amount`を実際に算出・保存する経路を実装する。

### R3-M2. 入札競合（409）でフォームが失敗表示のみで、案件の最新状態（成約済み/取り下げ済み）へ画面が更新されない
- 画面: `/operator`（ダッシュボードの入札フォーム）, `/operator/cases/[id]`（案件詳細の入札フォーム）
- 事象: 同一案件に他業者が先に落札された、または依頼者が出品を取り下げた直後に業者が入札を送信すると、バックエンドは409（例:「この案件は入札を受け付けていません。」）を返す。この時、両画面とも `catch` 節では `setError`/`showToast` でエラー文言を出すだけで、案件データの再取得（`reload()`）を行っていない。そのため入札フォーム・金額入力欄はエラー後も画面上に残り続け、業者は「一時的な失敗」と誤解して同じ入力のまま再送信を繰り返しうる。案件が既に閉じたことを示すステータス表示への更新が起きない。
- 根拠 file:line:
  - `web/src/app/operator/cases/[id]/page.tsx:96-104`（`submitBid`: `try { createBid(...); reload() } catch (err) { setError(toDisplayMessage(err, ...)) }` — catch節に`reload()`呼び出しなし）
  - `web/src/app/operator/page.tsx:380-395`（`confirmBid`: 同型。`await createBid(...); await reload();` は成功時のみ実行され、`catch (e) { showToast(...) }` はreloadを呼ばない）
  - 対比・裏付け: `backend/app/api/v1/endpoints/bids.py:120-124`（`case.status not in ("open","bidding")` で409。案件が他者落札/取り下げで閉じた場合に発生する実在の分岐）
- 再現手順: 1) 業者Aが案件詳細を開いたまま放置 2) 別業者Bが同案件に入札され依頼者が選定（成約）、または依頼者が出品取り下げ 3) 業者Aが開いていた画面で入札を送信 4) 409エラートーストは出るが、画面上の案件ステータス・入札フォームは古いまま（「入札受付中」に見え続ける）。
- 修正案: 両ファインの `catch` 節でも `void reload()`（または`getCaseMasked`/`getOperatorProfile`相当の再取得）を呼び、案件が閉じた場合はフォームを非表示にし「この案件は入札を締め切りました」等の明示的な案内に切り替える。

---

## 確認したが問題なし（観点別）

- **状態遷移(pending/active/suspended)**: `assert_operator_not_suspended`（`backend/app/api/deps.py:74-85,138,157,197`）が停止業者を全認証エンドポイントで403に統一しており、既存の停止/解除APIと整合。`get_verified_operator`（同ファイル142-162）はpending/limitedいずれも入札不可を一貫させている。
- **公開プロフィール `/vendors/[id]` の情報露出**: `OperatorPublicProfileOut`（`backend/app/schemas_katadzuke.py:993-1011`）・`OperatorPublicOut`（同107-118）とも連絡先・住所・許可番号を含まない設計を確認。`get_vendor_public_profile`（`backend/app/api/v1/endpoints/operator_profile.py:169-209`）も停止業者は404化・レビューは`reviewer_type=="user"`のみ公開でPII非露出。
- **LINE通知の遷移先リンク**: `backend/app/services/line_notify.py` 全関数を確認、`/operator/transactions/{id}` `/operator/chat/{id}` とも実在するルートへ正しく誘導。業者名等の外部入力は`_sanitize_inline`で改行注入対策済み。
- **招待コード登録 vs 通常登録の差分説明**: `web/src/app/operator/signup/page.tsx:110-133` に招待コードあり/なしの機能差（フル稼働 vs 運営承認待ち）を明記。承認待ち状態の案内は`ApprovalPendingNotice`コンポーネントで別途具体化済み（PROJECT_STATE記載の対応と一致、再指摘せず）。

## 未解決・確認できなかった点

- fee_amountの本課金実装（R3-M1の恒久対応）は設計判断が必要なため、コード監査の範囲外（実装方針の決定待ち）。
- `docs/TODO.md` に記載済みの「エリアフィルタ未実装」「422 detail配列の握り潰し」「取り下げ系レート制限の専用化」は本台帳では再指摘していない（記録より正はコードで確認済みだが、既知・意図的に未対応のため対象外）。
- モバイル375px実機スクリーンショットでの崩れ検証は今回未実施（コード監査のみ。過去2周でチャット/ダッシュボードは是正済みとの記録があり、他画面での再検証はスコープ外）。

---
判定サマリ: High 2 / Medium 2。「問題ゼロ」は不合格の基準に従い、コード実読で裏取り済みの新規4件を起票。
