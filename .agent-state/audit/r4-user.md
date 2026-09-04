# 依頼者導線 回帰監査台帳（第4周・2026-09-04）

対象: 依頼者（一般ユーザー）ルートのみ。コミット `885f2ec`（r3 実装、91ファイル・7,478行追加）に
対する独立の回帰監査。前提として `r3-user.md` / `r3-verify-user.md` / `r3-review-qa2.md` /
`docs/TODO.md` を読了済み。これらで CONFIRMED・修正済み・意図的未対応と記録された項目
（H1/H2/H3/A1/R-M1/R-M2/R-M3/M1 dead code 等）は、現在のコードで実際に修正が反映されている
ことをコード上で再確認したうえで、再指摘していない。編集除外ファイル（backend/app/config.py,
main.py, core/alert_middleware.py, services/alerts.py, tests/test_alerts.py,
.github/workflows/uptime-alert.yml）は指摘対象にしていない。

**重要な前提訂正**: `r3-review-qa2.md` が新規回帰として記録した R-M1（停止アカウントのログイン誤表示）・
R-M2（/contact と案件作成のレート制限バケット共有）・R-M3（プロセス内キャップの実送信通数基準）は、
現在の `web/src/auth.ts`・`web/src/app/login/page.tsx`・`backend/app/api/v1/endpoints/contact.py` を
直接読んだ結果、**いずれも既に修正済み**であることを確認した（コメントに「r3再レビューR-M1是正」
「N-2対応」「N-4対応」等の記載があり、895f2ec の内部反復（r3-fix-frontend2/3, r3-fix-backend2/3）で
qa2 執筆後に対応されたとみられる）。r3-review-qa2.md をそのまま信用せず必ずコードで現況確認すること。

---

## High

（該当なし）

## Medium

（該当なし）

---

## 確認したが問題なし

- **401/403共通処理の網羅性**: `web/src/lib/katadzuke-api.ts` の `throwHttpError`/`handleSessionExpired` は
  `request()` を通る全呼び出しに一律適用され、401は日本語文言+signOut後に役割別ログイン画面へ、
  停止403（`detail.code==="account_suspended"`）は `?reason=suspended` 付きで遷移する。ループ検知
  （`isRedirectLooping`）・signOut失敗時のフォールバック文言も実装済み。H1（r3時点でHigh）は解消済み。
- **LINE連携reauth（401）の誤発火なし**: `web/src/lib/line-link.ts:linkLineToCurrentUser` は素の `fetch`
  を使い `request()`/`throwHttpError` を経由しないため、`reauth_required`（401）が誤ってグローバル
  セッション失効処理に巻き込まれることはない（`res.status === 401` を専用に判定して分岐、実在確認）。
- **/verify-email・/password-reset の誤発火リスクなし**: 両ページとも `katadzuke-api.ts`・`fetch` の
  呼び出しが一切なく（grep 0件）、静的案内のみで API 401 を受け取る経路自体が存在しない。
- **/login の停止アカウント表示（旧 R-M1）**: `web/src/auth.ts` に `AccountSuspendedError`
  （`CredentialsSignin` 継承・`code="account_suspended"`）が実装され、`login/page.tsx` の
  `onSubmit` が `res?.code === "account_suspended"` を専用ハンドリングして「利用停止中」バナー
  ＋ `/contact` 導線を表示する。「メールアドレスまたはパスワードが正しくありません」への誤表示は
  発生しない（r3-review-qa2 記載の R-M1 は解消済み）。
- **/login の accountType 判定・callbackUrl**: `login/page.tsx` は `session?.accountType !== "user"`
  の場合は自動 replace せず、業者セッションでの迷い込みには「サインアウトして依頼者ログインへ」
  バナーを出す（無限リダイレクトループを起こさない設計）。`middleware.ts` も accountType 不一致を
  `/forbidden?reason=account_type` へ送り、`/forbidden` 側は `session.accountType` を見て
  「業者アカウントでログイン中です」等の具体的な案内文を出し分ける。実装・文言とも整合。
- **/create の離脱ガード（旧 H3）**: `beforeunload`（写真0枚なら発火しない）と `popstate` 二重ガード、
  `confirmLeave()` が `allowLeaveRef` を先に立ててから `router.push("/mypage")` する設計を確認。
  正常送信時も `allowLeaveRef.current = true` を送信成功後に立てており、誤って離脱モーダルが
  二重発火することはない。
- **/create のAI解析タイムアウト（旧 A1, High）**: `createTimeoutSignal(180_000)` を `createCase` に
  渡し、`AbortSignal.timeout` 非対応環境（Safari 15以前等）へのフォールバックも実装。タイムアウト時は
  専用文言＋`/mypage`誘導に分岐し、通常のネットワークエラーと区別している。
- **/contact の 422/429/503 分岐**: `KdzApiError.status` で 422（入力確認）・429（送信集中）を専用文言に
  分岐し、それ以外（503含む）は `toDisplayMessage` の汎用フォールバックへ。二重送信防止（`sending`
  フラグ）も確認。バックエンド側のレート制限バケットは `case_create` と scope名で分離済み
  （`contact.py` コメント「N-2対応」）、プロセス内キャップも「実送信通数」ではなく「リクエスト数」基準
  に既に修正されている（r3-review-qa2 記載の R-M2/R-M3 は解消済み）。
- **通知チャネル文言の横断整合**: `cases/[id]/page.tsx`（入札通知）・`mypage/page.tsx`（入札/チャット）・
  `chat/[id]/page.tsx`（チャット新着）・`notifications/page.tsx`（連携済み案内）・`faq/page.tsx` の
  5箇所が「入札はLINE連携済みはLINE・未連携はメール」「チャット新着はLINE連携済みのみ（メール無し）」
  で完全に一致。バックエンド `notify_dispatch.py` の `dispatch_bid_received`（email フォールバック
  あり）と `dispatch_message_received`（`line_user_id` 必須・emailフォールバック無し）の実装とも
  文言が正確に対応している。
- **クーリング・オフ/古物営業法の非断定表現の横断整合**: `schedule/page.tsx`・`legal/page.tsx`・
  `faq/page.tsx`・`page.tsx`（トップ）・`terms/TermsTabs.tsx`・`business/page.tsx` の6箇所すべてで
  「品目・経緯によって異なる／業者から交付される書面を確認」という同一の非断定文言に統一。
  古物営業法の本人確認義務も `faq/page.tsx`・`privacy/page.tsx`・`terms/TermsTabs.tsx`・
  `mypage/identity/page.tsx` の4箇所で「1万円以上の買取など法令で定める場合」という同一の条件付き
  表現に統一済み（r3-review-qa2 が指摘した粒度不一致は解消されている）。
- **死んだ古文言コンポーネントの完全削除**: `web/src/components/landing/Faq.tsx`
  （「当面無料」「8日間の無条件クーリングオフ」を含む未importの死にコード、105行）はファイル自体が
  存在せず（r3-review-qa2 記載の QA-M1 は完全解消）。
- **事業者所在地・連絡先メールの横断整合**: `legal/page.tsx`・`company/page.tsx`・`privacy/page.tsx`
  フッターがすべて「神奈川県横浜市」で一致。連絡先メールも `legal/page.tsx`・`company/page.tsx`・
  `unsubscribe/page.tsx`・`contact.py`・`notify.py` まで `katazuke.info@gmail.com` で統一され、
  旧アドレス（katazuke-support@gmail.com）の残存は0件（grep確認）。
- **/mypage/bank-account・/mypage/profile の支払経路表現**: 「カタヅケは送金を行わない（当事者間精算）」
  「振込希望時に業者へ伝える口座」という新方針に一致した文言に統一されている。
- **入札期間上限なしの表現統一**: `faq/page.tsx`・`legal/page.tsx`・`terms/TermsTabs.tsx` で
  「上限を設けていない・業者選択時点で終了」に統一。旧「3日間」の残存なし（grep 0件、`/cases`・
  `/create`・`photo-guide` を含む）。
- **写真上限の表示値**: `photo-guide/page.tsx`（150枚/12枚)・`create/page.tsx`
  （`CASE_PHOTO_LIMIT=150`, `ITEM_PHOTO_LIMIT=12`, `ITEM_LIMIT=30`）が一致。旧上限（20枚/8枚/10点）の
  残存は無い。

## 未解決

- **R-L1相当の残存（Low・再指摘は主節に含めず参考記載）**: `create/page.tsx` は `guardArmedRef` で
  写真1枚目のタイミングに履歴へ番兵エントリ（`pushState({kdzCreateGuard:true})`）を積むが、
  正常送信成功時（`:432`）・離脱モーダル「ページを離れる」時（`:217-219`）ともに
  `router.push(...)` するだけで番兵を `replaceState` 等で消費しない。結果、送信成功後に
  `/cases/[id]` へ遷移した直後にブラウザバックすると、番兵の残った空の `/create` フォームへ着地する
  （送信成功直後の混乱要因になりうるが、案件自体は正常に作成済みでデータ損失はない）。
  r3-review-qa2 が Low として記録済みで `docs/TODO.md` の「03 開発の積み残し」には個別記載が無い。
  重大度は Low のためリリース阻害の主節（High/Medium）には計上しないが、本番前に軽微修正
  （遷移前に `history.replaceState` で番兵を消す）を推奨する。
- **実ブラウザでの確認は本監査でも未実施**: 停止アカウントでの実ログイン試行、送信成功後の
  ブラウザバック挙動（上記）、LINE内蔵ブラウザでの `/create` タイムアウト表示は、いずれもコード
  読解のみで判定しており、実機・実ブラウザでの再現確認はしていない（禁止事項によりファイル編集・
  実操作は範囲外）。
- **`/mypage/withdraw`（退会）の通知文面突き合わせ**: `r3-user.md` の未解決事項として既に記録されて
  おり、本第4周でも実施していない（885f2ec の diff に含まれないファイルのため回帰の可能性は低いが、
  未検証のまま）。
- **本番 ADMIN_EMAILS 実測・`/contact` 実受信確認**: `docs/TODO.md` 01章に記載のユーザー側タスクで
  Claude側では実行不能（本番メール受信箱の確認が必要）。依頼者が `/contact` で問い合わせても運営に
  届かない不可視の全損経路が理論上残っている。

---

## 末尾サマリ

✅ コミット 885f2ec 時点で r3-user.md の High 3件（H1/H2/H3）・r3-review-qa2.md の新規回帰
（R-M1/R-M2/R-M3/M1死にコード等）はすべてコード上で修正を確認した。本第4周で依頼者導線に
新規の High/Medium 回帰は検出しなかった。
⚠️ Low 相当の未修正が1件残存（送信成功直後のブラウザバックで空の /create フォームに着地）。
リリースを阻害しないが本番前の軽微修正を推奨する。
❌ 実機・実ブラウザでの動作確認、本番 /contact 実受信確認、/mypage/withdraw の通知文面突き合わせは
本監査のスコープ外・未実施のまま残っている。
