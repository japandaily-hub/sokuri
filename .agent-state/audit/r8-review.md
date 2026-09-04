# r8 レビュー（QA + セキュリティ・未コミット差分の実コード検証）

日付: 2026-09-05 / 対象: `git status` の未コミット変更全て（backend/app・0030・backend/tests・web/src）
方針: 自己申告（r8-fix-backend.md / -backend2 / -frontend / -frontend2）は根拠として扱わず、全て実コードで再確認した。

## 総合判定

**条件付き合格**（Critical 0 / High 4 / Medium 6 / Low 5）。
実装の骨格（終了取引ガード・cancellation 露出・減額上限・admin 強制終了・業者退会）は仕様どおり動く。
ただし「理由の逐語開示」に対する当事者への告知が欠落（High 2件）、退会と落札の競合が直列化されていない（High 1件）、
宣言されたレート制限が実質無効（High 1件）。いずれも修正は局所的。

## 実行検証（実測）

| 項目 | コマンド | 結果 |
|---|---|---|
| pytest | `backend/.venv/Scripts/python.exe -m pytest -q` | **811 passed, 837 warnings in 205.23s**（自己申告 811 と一致） |
| tsc | `web && npx tsc --noEmit` | **exit 0 / エラー 0** |
| eslint | `web && npx eslint src` | **exit 0 / 0 errors, 3 warnings**（3件とも差分外の既存: notifications/page.tsx:196・operator/transactions/[id]/page.tsx:89・signup/page.tsx:59） |
| alembic heads | `alembic heads` は cp932 で実行不能 → ScriptDirectory で走査 | **単一ヘッド `0030_operator_deleted_at`**（全31リビジョン、最長 revid 45字＝既存分） |
| next build | 指示により未実行 | — |

## Critical（0件）

なし。

## High（4件）

### H-1 業者退会と落札の競合が直列化されておらず「退会済み業者の進行中成約」が生成されうる
- 該当: `backend/app/api/v1/endpoints/operator_profile.py:402-421`（進行中取引カウント → pending 入札の一括 rejected → deleted_at 付与）／`backend/app/api/v1/endpoints/bids.py`（deleted_at の参照が **0件**。is_suspended は :256、vendor_status は :266 で post-lock チェック済）
- 問題: 退会処理は Case 行ロックを一切取らない。select_bid は Case 行をロックするが、ロック対象が重ならないため排他されない。
- 再現条件:
  1. 業者 X が案件 C に pending 入札を持つ
  2. `DELETE /operator/me`（X）が active_txn_count=0 を読む
  3. 直後に依頼者が `POST /cases/C/bids/{id}/select` → Case ロック取得 → X の入札を selected 化・Transaction 作成・commit
  4. 退会側の `UPDATE bids SET status='rejected' WHERE status='pending'` は既に selected の行に当たらず、deleted_at だけが commit される
  → 業者はログイン不能（deps.py:172-173）、依頼者は日程調整も完了もできない成約を抱える。脱出は依頼者キャンセルか admin 強制終了のみ。
- 修正案:
  (a) `bids.select_bid` の post-lock ガードに `target.operator.deleted_at is not None → 409` を追加（is_suspended と同じ位置・同じ形。多層防御）。
  (b) 退会側は「pending 入札の rejected 化 → flush → **その後に** active_txn_count を再計測 → 非0なら rollback + 409」の順に変更する（READ COMMITTED で 3 の commit を観測できる）。または対象業者の pending 入札が付く Case 行を lock_case_row でまとめて掴む。
- 補足: SQLite テストでは FOR UPDATE が no-op のため、この race は 811 件のどのテストでも検出不能。

### H-2 業者のキャンセル理由が依頼者へ逐語表示されるのに、業者側モーダルに開示告知が無い（依頼者側と非対称）
- 該当: `web/src/app/operator/transactions/[id]/page.tsx:330` / `:436-439`（文言は「キャンセルは記録され、運営が確認します。／理由を入力してください。」のみ）
- 対比: 依頼者側は `web/src/app/cases/[id]/page.tsx:960` で「理由は業者に共有されます。」と明示済み。
- 表示先: `web/src/app/cases/[id]/page.tsx:820-824`（`理由: {txn.cancellation.reason}`）／backend は `schemas_katadzuke.py:722-735` + `transactions.py:627-630` が当事者双方に同じ内容を返す。
- 問題: 従来 Cancellation.reason はどの API からも読み出されず「運営だけが見る記録」だった。今回から相手方に逐語公開されるのに、業者は仕様変更を知らないまま入力する。「室内が不衛生で作業不能」「近隣から苦情」等が依頼者に直送される。
- 修正案: `:437` の `<strong>` を「キャンセルは記録され、**入力した理由はそのまま依頼者に表示されます**。」に変更。合わせて `:445` の textarea に maxLength（backend の TransactionCancelRequest.reason 上限と同値）と「個人情報は書かないでください」の注記を追加。

### H-3 運営の強制終了理由が当事者双方へ逐語表示されるが、admin モーダルに注意書きが無い
- 該当: `web/src/app/admin/transactions/page.tsx:253-257`（message は「…この操作は元に戻せません。」、reasonLabel="終了理由（必須）"）
- 表示・誘導先: `backend/app/schemas_katadzuke.py:732`（cancelled_by は admin も含む Literal で reason を無条件に返す）／`backend/app/services/notify.py` の send_transaction_cancelled_by_admin が「詳細と理由を確認する」と当事者を画面へ誘導する。
- 問題: 運営が内部メモのつもりで書いた文（例「依頼者Aが業者Bを通報したため」「反社チェックに抵触」）がそのまま依頼者・業者の双方に表示される。通報者の秘匿・名誉毀損リスクに直結。
- 修正案: (a) モーダル message に「入力した理由は依頼者・業者の双方に表示されます」を追記し reasonLabel を「終了理由（必須・当事者双方に表示されます）」に変更（最小・即応）。(b) AdminTransactionCancelRequest を public_reason / internal_note に分割し、TransactionCancellationOut は前者だけを返す（本筋）。

### H-4 不可逆な業者退会に再認証が無く、宣言されたレート制限も実質 no-op
- 該当: `backend/app/api/v1/endpoints/operator_profile.py:383-386`（`_rl: object = Depends(RateLimitGuard("account_delete"))` のみ。request: Request を受けず ctx.check_account() / record_failure() を一度も呼んでいない）
- 根拠: `backend/app/api/rate_limit_deps.py:375-378` で account_delete は `ip_rule=None, account_rule=sensitive_account, count_all=False`。**IP 軸を持たず全件カウントもしない**ため、ハンドラが ctx.check_account() を呼ばない限りガードは何もしない。比較対象の `backend/app/api/v1/endpoints/users.py:593-595` は `ctx = request.state.rate_limit` → `ctx.check_account(str(user.id))` を明示実行している。
- 併せて: 依頼者退会（users.py:601-606）は body.confirm + パスワード再照合が必須。業者退会はボディ無し DELETE の1発で完了する（web/src/app/operator/profile/page.tsx:159-170 も確認モーダル1枚のみ）。
- 影響: XSS・トークン漏洩・共有端末での放置いずれでも業者アカウントを1リクエストで復旧不能に破壊できる。r8-fix-backend2.md の「レート制限 account_delete 適用」という記述は**事実と異なる**。
- 修正案: delete_my_operator_account に request: Request を追加し `request.state.rate_limit.check_account(str(operator.id))` を呼ぶ（users.py と同型）。さらに /operator/reauth-token を前段に置くか OperatorAccountDeleteRequest{confirm, password} を追加してパスワード再照合を必須化する。web 側は `katadzuke-api.ts:427-429` の body 追加のみ。

## Medium（6件）

### M-1 強制終了を実行した運営アカウントが DB に残らない
- 該当: `backend/app/api/v1/endpoints/admin.py:137-144`（Cancellation(cancelled_by="admin", reason=...) のみ）／`:184-189` はアプリログのみ。
- 問題: 不可逆かつ当事者に通知が飛ぶ操作の実行者がログのローテーションで消える。運営が複数人になった時点で追跡不能。
- 修正案: cancellations に `cancelled_by_admin_id UUID NULL`（FK users.id）を 0031 で追加し admin.id を記録。既存行は NULL、API 応答には含めない。

### M-2 既存 purpose 値が全画面で「その他」に化ける表示回帰
- 該当: `web/src/lib/case-labels.ts:22-27`（CASE_PURPOSES は4値のみ）／backend は `backend/app/schemas_katadzuke.py:557-563` で「不用品処分」「断捨離」も受理する。
- 再現: 既存 DB / seed_local_e2e.py 由来の「断捨離」の案件を /cases/[id]・/operator/cases・/admin/cases で開くと「その他」と表示される。
- 修正案: case-labels.ts に LEGACY_CASE_PURPOSES を追加し、formatPurposeLabel は「CASE_PURPOSES ∪ LEGACY」に含まれる値をそのまま返す（選択肢としては出さない）。

### M-3 file.type が空文字の正当な画像をクライアント側で 422 にする回帰
- 該当: `web/src/lib/katadzuke-api.ts:1441-1443`（`if (!ALLOWED_PHOTO_TYPES.has(file.type)) throw new KdzApiError(422, ...)`）
- 従来: 未知 MIME は "image/jpeg" にフォールバックし、サーバのマジックバイト判定（storage.sniff_image_ext）が最終判断していた。
- 再現: 拡張子なし／未知拡張子の JPEG を「すべてのファイル」で選択（一部 Android ピッカー・Linux Chrome では file.type === ""）→ 従来は成功、今回から必ず失敗。
- 修正案: `file.type === ""` の場合のみ従来どおり "image/jpeg" にフォールバックしてサーバ判定に委ね、明示的な非対応 MIME（image/heic 等）のみクライアントで弾く。

### M-4 CASE_PURPOSE_VALUES が完全な未使用（Literal と二重定義）
- 該当: `backend/app/schemas_katadzuke.py:557-565`。リポジトリ全体の grep で参照は定義行のみ。
- 問題: 直下の `CasePurpose = Literal[...]`（:566-573）と同じ6値を手書きで二重管理しており、片方だけ更新されるドリフトを確実に生む。
- 修正案: CASE_PURPOSE_VALUES を削除し CasePurpose 単独にする。集合が必要なら `typing.get_args(CasePurpose)` を使う。

### M-5 業者が退会済みであることを当事者向け API が表現できない
- 該当: `backend/app/schemas_katadzuke.py:744-750`（operator_suspended はあるが operator_deleted 相当が無い）
- 影響: H-1 で成立した「退会済み業者の成約」に加え、成約前に退会した場合も住所未開示のため contact_email の「退会済み業者」分岐（transactions.py:606-614）に到達せず、依頼者は無応答の理由を一切知れない。
- 修正案: TransactionDetailOut に `operator_deleted: bool` を追加し（user_suspended と同じ実装パターン）、operator/transactions/[id]・cases/[id] に「業者が退会したためこの取引は進行できません」の導線を出す。

### M-6 減額申請の上限判定が行ロック無し（3件目が入りうる）
- 該当: `backend/app/api/v1/endpoints/reductions.py:426-430`（`len(txn.reduction_requests) >= 2`）。直前の pending 判定（:78-82）ともども `_get_txn`（:44-52）はロック無しの単純 SELECT。
- 再現: 2件目が pending の状態で依頼者の decide(reject) と業者の create が同時着弾。uq_reduction_requests_pending は「pending 2行」しか禁じないため、reject 確定後に読んだ側は len==2 を見ずに3件目を作りうる。
- 修正案: create_reduction の先頭で `lock_transaction_rows(session, transaction_id)`（`backend/app/services/case_lock.py:36`。今回 admin と共有化した関数）を呼び、ロック後に populate_existing=True で再取得してから件数判定する。

## Low（5件）

- **L-1** `web/src/components/kdz/ConfirmModal.tsx:97`（背景 onClick={onCancel}）・`:71-73`（Esc）が busy を見ない。DELETE /operator/me や強制終了の in-flight 中に背景クリックでモーダルが消え、成功/失敗表示が行き場を失う。修正案: `onClick={() => { if (!busy) onCancel(); }}` と Esc 側にも同条件。
- **L-2** `web/src/app/cases/[id]/page.tsx:957` — 理由 prompt で「キャンセル」を押しても（`?? null`）確認モーダルが開く。同ファイル :753-755 の取り下げ経路は `if (reason === null) return;` で中断しており非対称。修正案: :957 も null なら return。
- **L-3** `web/src/lib/case-labels.ts:5` のコメント「backend の purpose は現状 free string（str）」が、今回の CasePurpose Literal 化で虚偽になった。修正案: 「backend は Literal で6値固定。web の選択肢は4値、残り2値はレガシー」へ更新。
- **L-4** eslint warning 3件（差分外の既存）。--fix で2件解消可。今回の commit では触らない判断で可。
- **L-5** `alembic heads` が Windows 実機で実行不能（alembic.ini が UTF-8 日本語コメントを含み、alembic が encoding="locale"＝cp932 で読むため UnicodeDecodeError）。ヘッド単一性を運用手順で確認できない。修正案: alembic.ini から非 ASCII を除去するか env.py 側へ移す。

## 重点項目に対する確認結果（(1)〜(10)）

1. **終了取引ガード**: 合格。`transactions.py:461-475` の TRANSACTION_CLOSED_DETAIL dict + `_ACTIVE_TXN_STATUSES=("pending","visiting")` は TransactionStatus の4値（`web/src/lib/katadzuke-api.ts:17`）と過不足なく対応。create_message（:640）・propose_schedule（:650）のみに適用され mark_messages_read は 200 のまま。web は `chat/[id]/page.tsx:237`・`operator/chat/[id]/page.tsx:230` で 409 受信時に reloadDetail()、isClosed で入力欄を非表示化。**契約一致**。
2. **cancellation 露出**: 機能は正しいが告知が欠落 → **H-2 / H-3**。admin の cancelled_by は `admin.py:62-70` でバッチ1クエリ、`schemas_katadzuke.py:770` → `admin/transactions/page.tsx:43-46` の未知値素通しも妥当。XSS は React の自動エスケープで問題なし。
3. **減額の回数制限**: 判定順序は正しい（pending 409 が先: `reductions.py:78-82` → 上限 409: `:426-430`）。却下後1回のみ＝計2回。ロック不足のみ **M-6**。
4. **admin 強制終了**: 認可は `Depends(get_current_admin)`（admin.py:96）。ロックは当事者経路と同一の lock_transaction_rows（Case→Transaction）。IntegrityError → 409 変換あり（:161-168）。二重実行は `txn.status in ("completed","cancelled")` で 409（:129-133）。通知は commit 前にプリミティブ抽出済み、is_placeholder_email（`notify.py:41-51`）が LINE 仮メール・退会トムストンの両方を弾くため配送不能宛への送信は起きない。案件は case.status="cancelled"（当事者経路と同じ）。cancel_count 非加算も妥当。監査主体の欠落のみ **M-1**。
5. **DELETE /operator/me**: 進行中判定は「終端以外を進行中」とする正しい向き（`operator_profile.py:326`）。トークン失効は `deps.py:172-173`。公開一覧（:296-306）・公開プロフィール（:290-293）・業者ログイン（`auth.py:207-211`）の3経路すべてで除外済み。プロフィール非公開化・intro_message 消去も実施。**穴は H-1（入札との競合）と H-4（再認証・レート制限）**。招待コード／事前申込はメールのトムストン化により同一メールでの再申込・再登録が可能＝実質的な復帰経路として機能し、意図と整合。
6. **purpose Literal 化**: /create の PURPOSES は CASE_PURPOSES（4値）を参照し backend 許容集合の部分集合 → 422 は起きない。既存 seed 値も許容集合に含む。web のフォールバック表示のみ **M-2**、未使用定数 **M-4**。
7. **auth.ts**: account_suspended の分岐（`web/src/auth.ts:104`）は 403 判定の内側にあり、後段の 429（:105）・5xx（:106）追加は到達順に影響しない。`login/page.tsx:92-104`・`operator/login/page.tsx:81-92` とも account_suspended → rate_limited → server_error → res.error の順で既存挙動は不変。**回帰なし**。
8. **写真アップロード**: backend 415/422 の文言（`case_photos.py:22-38`）と web の事前検証（`katadzuke-api.ts:1429-1447`）は形式集合が一致。PUT 失敗が throwHttpError に一本化され detail が表示されるようになった点は改善。HEIC の案内も具体的で妥当。**空 MIME の回帰のみ M-3**。
9. **ConfirmModal 共通化**: `web/src/app/admin/_components/ConfirmModal.tsx` は再エクスポートのみのシムで admin 4画面の既存 import は無改変で通る（tsc 0 error で裏付け）。aria-labelledby は adminConfirmModalTitle → kdzConfirmModalTitle に改名され id と参照が一致。onConfirm 配線・busy・error はすべて渡されている。**L-1 のみ**。
10. **operator/profile の退会導線**: `operator/profile/page.tsx:724-741` にセクション追加、409 は toDisplayMessage でモーダル内 error に表示、成功時は signOut({callbackUrl:"/operator/login?reason=withdrawn"})。受け側 `operator/login/page.tsx:41`・`:162-170` で表示。**導線は成立**（ただし role="status" に auth-error（赤系）クラスを当てているため、退会完了の中立的通知がエラー色で出る＝軽微な UI 不整合）。

## 未解決リスク（6件）

1. **0030 は本番未適用。デプロイ順序を誤ると全業者が 500。** `deps.py:172` と `auth.py:209` が operators.deleted_at を無条件参照するため、カラム未追加の DB に新コードが載ると業者側の全リクエストが UndefinedColumn で落ちる。**migrate → deploy の順を強制**し、Render のログで 0030_operator_deleted_at の適用行を確認するまで完了扱いにしない。
2. **811 件のテストは SQLite in-memory（`backend/tests/conftest.py:50`）で走っており SELECT ... FOR UPDATE が no-op。** 今回追加された行ロック（case_lock.lock_transaction_rows）・部分ユニーク索引（uq_reduction_requests_pending）・uq_cancellations_transaction_id の競合防止は**1件も実証されていない**。H-1・M-6 がテストで捕まらないのはこのため。Postgres を使う競合テスト層（testcontainers 等）の追加を推奨。
3. **next build 未実行。** 過去に @import layer() が lightningcss で誤変換されトークンが全消失した事故があり、今回 components/kdz/ConfirmModal.tsx の新規追加と admin/_components/ の再エクスポート化で import グラフが変わっている。本番ビルド固有の回帰は未検出。
4. **退会業者のレビュー統計・Operator.rating を再計算していない。** delete_my_operator_account は recalc_operator_review_stats を呼ばず、GET /vendors は deleted_at IS NULL で除外するだけ。レビュー行は残り、将来「地域平均」等の集計を入れると退会業者が混入する。[要確認: 集計仕様が未定]
5. **admin 系一覧が退会業者を除外していない。** admin.py の業者一覧に deleted_at フィルタは無く、運営が退会済み業者を「承認」「停止解除」できる。退会と停止解除が競合すると状態が不整合になりうる。運営 UI に退会バッジを出すか、状態変更 API 側で 409 にすべき。
6. **Operator.cancel_count は表示されるだけで自動停止もスコア反映も無い。** `web/src/app/admin/page.tsx:588-591` にバッジは出たが運用しきい値・対応手順が未定義。合わせて業者向け文言は「アカウント評価に影響します」→「記録され、運営が確認します」へ弱められており（`operator/transactions/[id]/page.tsx:330`・`:437`）、抑止力は実質ゼロになった点は経営判断として明示すべき。[要確認: 運用ポリシー]

## 結論

- Critical 0。High 4 はいずれも局所修正。H-2・H-3 は文言追加のみ（数行）、H-4 は users.py と同型の3行追加、H-1 のみ select_bid への1ガード + 退会側の順序入れ替えが必要。
- **High 4件の修正・再レビュー通過までは完了としない**（グローバル開発プロトコルの規定）。
- 実行検証は全て緑（pytest 811 / tsc 0 / eslint 0 errors / heads 単一 0030）だが、**テスト環境が SQLite であるため競合系の緑は根拠にならない**点を明記する。

サマリ: ⚠️ 条件付き合格（Critical 0 / High 4 / Medium 6 / Low 5・High 是正後に再レビュー必要）
