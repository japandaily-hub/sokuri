# カタヅケ 業者導線 回帰監査台帳（第4周・2026-09-04）

対象コミット: 885f2ec（230b2d8→885f2ecの `web/src/app/operator` `backend/app/api/v1/endpoints` 差分）。
前提: `r3-vendor.md`（起票2件）・`r3-verify-vendor.md`（CONFIRMED3/PARTIAL1・追加High3件）・`docs/TODO.md` の既知・意図的未対応は再指摘しない。R3-H1/H2/M1/M2・ADD-1/2/3 の実装内容を再読し、修正が正しく入ったこと（通知の宛先・文面・送信タイミング、401/403共通処理、409後の再取得、手数料β表記）を確認済み（誤りなし）。本台帳は885f2ecが新たに持ち込んだ回帰のみを起票する。

---

## Medium

### R4-M1. `/operator/login` に足したアカウント切替導線が非対称で、既に業者ログイン済みの状態で開くとフォームへ行き止まりになる（`/login` 側の対称実装と機能が揃っていない）
- 画面: `/operator/login`
- 事象: 885f2ec は `/operator/login` に `useSession` を新規導入し「依頼者アカウントでログイン中なら案内バナー＋サインアウト導線を出す」機能（`otherAccountSignedIn`）を追加したが、対になる「**業者として既にログイン済みの場合は目的地へ自動遷移する**」useEffect が実装されていない。同じコミットが直接参照している `/login`（ユーザー側）は、まったく同じ意図（コメント曰く「/loginと対称に」）で両方の分岐を実装済み: `session?.accountType !== "user"` なら案内バナー、`session?.accountType === "user"` なら `router.replace(...)` で自動遷移。`/operator/login` はバナー分岐のみ移植され、自動遷移分岐が欠落している。結果、業者が既に有効なセッションを持ったまま `/operator/login` を開く（ブックマーク・トップの「業者ログイン」リンク・LINE等の外部リンク経由）と、案内もリダイレクトも出ず空のログインフォームが表示されたままになり、業者は自分がログイン済みであることに気づけずメール・パスワードを再入力する羽目になる（またはURLを手打ちで `/operator/cases` に移動するしかない）。ミドルウェアも `/operator/login` を `OPERATOR_PUBLIC` として保護対象外にしているため、サーバー側でのフォールバック救済も無い。
- 根拠 file:line:
  - `web/src/app/operator/login/page.tsx:22-38`（`useSession` を使うのは `otherAccountSignedIn` の1箇所のみ。`session?.accountType === "operator"` を条件にした `useEffect`/`router.replace`/`router.push` は本ファイルに存在しない — grep確認: `grep -n "useEffect" web/src/app/operator/login/page.tsx` はヒット0件）
  - 対比: `web/src/app/login/page.tsx:37-48`（`useEffect(() => { if (status !== "authenticated") return; if (session?.accountType !== "user") return; ...; router.replace(reachable ? callbackUrl : "/cases"); }, ...)` — 一致する役割の分岐が存在）
  - `web/src/middleware.ts:29`（`OPERATOR_PUBLIC = ["/operator/login", "/operator/signup"]`）と`:51-52`（`isOperatorPublic` の場合 `needsOperator=false` となり `!needsUser && !needsOperator && !needsAdmin` で即 `NextResponse.next()`。セッションの有無・種別に関わらずミドルウェアはこのパスを一切ガードしない）
  - git diff確認: `git diff 230b2d8 885f2ec -- web/src/app/operator/login/page.tsx` で `import { signIn, signOut, useSession } from "next-auth/react";` が新規追加されており、`useSession` の利用は今回のコミットで初めて持ち込まれたことを確認済み（＝この非対称は885f2ecが原因で生じた回帰であり、r3以前からの既知事項ではない）。
- 再現手順: 1) 業者としてログインし `/operator/cases` などに居る 2) 同一タブで `/operator/login` を直接開く（アドレスバー入力、または他画面の「業者ログイン」リンク経由）3) セッションは有効なままなのに、案内バナーも自動遷移も起きず、空のメール・パスワード入力フォームがそのまま表示される（`otherAccountSignedIn` は `session?.accountType !== "operator"` が条件のため、`accountType==="operator"` の一致ケースでは何も表示されない）。
- 修正案: `/login` の該当 `useEffect`（`web/src/app/login/page.tsx:37-48`）と同型のロジックを `/operator/login` にも追加する: `status==="authenticated" && session?.accountType==="operator"` の場合、`clearRedirectLoopStorage()` を呼んだ上で `router.replace(callbackUrl)`（オープンリダイレクト対策で既に `safeInternalPath` 済みの `callbackUrl` を利用）。ループ防止のため `/login` 側と同じく「accountType一致時のみreplaceし、不一致時はバナーに委ねる」条件を踏襲すること。

---

## 確認したが問題なし（新規差分のみ再検証）

- **通知（減額申請の作成→依頼者・決定→業者・取引キャンセル→相手方）**: `reductions.py` `create_reduction`/`decide_reduction`、`transactions.py` `cancel_transaction` とも `background.add_task` へ渡す引数はプリミティブ値のみ（ORMオブジェクトを渡していない）で `bids.py` の既存規約と一致。`notify_dispatch.py` の新設3関数（`dispatch_reduction_requested`/`dispatch_reduction_decided`/`dispatch_transaction_cancelled`）は全て `_best_effort` でラップ済み、LINE優先→メールフォールバック、`is_placeholder_email`/`None`ガードも一貫。二重送信・失敗握りつぶしなし。`line_notify.py`/`notify.py` の遷移先URL（`/cases/{id}`・`/operator/transactions/{id}`・`/chat/{id}`）は既存の `push_message_received` と同じパス規約で実在ルートに一致。
- **業者401/403共通処理**: `backend/app/api/deps.py` の `SUSPENDED_ACCOUNT_DETAIL` を `assert_user_not_suspended`/`assert_operator_not_suspended` で共用し、`auth.py` の `operator_login`/`user_login`/`line_exchange` 全経路が同一dict detailに統一されたことを確認。`web/src/lib/katadzuke-api.ts:610-637` の `throwHttpError` が401/403(account_suspended)双方でsignOut→役割別ログイン画面へ誘導し、`skipAuthRedirect` のオプトインは現状どこからも使われていない（grep確認: ヒット0件＝全API呼び出しが共通処理を通る）。`web/src/auth.ts` の `SESSION_MAX_AGE_SECONDS`（7日）が `backend/app/config.py` の `jwt_expire_minutes`（7日）と一致し、r3-verify ADD-3（30日vs7日のズレ）は解消済み。
- **入札409後の再取得**: `operator/cases/[id]/page.tsx:106-108`・`operator/page.tsx:398-400` とも `catch` 節で `KdzApiError.status===409` の場合のみ `reload()` を追加。エラー文言（`setError`/`showToast`）は先に確定させてから `reload()` する順序が守られており、r3-verify指摘（エラー文言が上書きされない配慮）どおり実装されている。`canBid` 判定（`caseData.status`・`my_bid`）は `reload()` の戻り値で正しく更新され、成約済み/取り下げ済みでフォームが消え、`my_bid` があれば入札済み表示に切り替わることをロジック上確認。
- **手数料β表記の整合**: `operator/chat/[id]/page.tsx`・`operator/page.tsx`・`operator/profile/page.tsx` に加え、`legal/page.tsx`・`terms/TermsTabs.tsx`・`faq/page.tsx`・`business/page.tsx`・トップ `page.tsx` の「8%」表記全箇所にβ無料注記が追加されており、r3-verify PARTIAL指摘（法定表示面`/legal`の取りこぼし）も是正済み。`operator/chat/[id]/page.tsx` の手数料欄は完了前後で表示元が切り替わらず一貫して「予定額（買取額の8%）」を表示するよう修正されている。

## 未解決・確認できなかった点

- `docs/business_plan_katazuke_20260831.md` の正式ローンチ時手数料率（15%）とアプリ内表記（8%）の不整合は文書間の話であり、`docs/TODO.md` 02節「決めてから着手」の範疇（r3-verifyが既に指摘済み）のため本台帳では再指摘しない。
- `web/src/app/operator/signup/page.tsx` の招待コード登録直後の `signIn` 成功パス（line 62-73）は今回のコミットで変更されておらず、`clearRedirectLoopStorage()` を呼ばない点は885f2ec以前からの挙動（回帰ではない）と判断し対象外とした。

---
判定サマリ: High 0 / Medium 1。r3の4件（H1/H2/M1/M2）とADD-1/2/3は全て正しく実装されていることを確認した上で、885f2ecが新規に持ち込んだ非対称実装（R4-M1）を1件検出した。
