# user-journey.md High指摘 反証結果（2026-09-03）

対象: user-journey.md High 1〜7（依頼者導線）。判定 = CONFIRMED / PARTIAL / REFUTED。

---

## 1. /verify-email「自宅で即日現金」断定と/legalの矛盾
**判定: CONFIRMED**
- `web/src/app/verify-email/page.tsx:109`「気に入った業者を選べばOK。自宅で即日現金を受け取れます。」実在確認。
- `web/src/app/legal/page.tsx:133`「業者によって異なります（現金・振込など）。詳細は交渉時に業者へご確認ください。」実在確認。両者は直接矛盾。
- `page.tsx:6`「実際の確認処理はバックエンド未配線のため、本ページは『確認完了』表示のみを担う」実在確認。バックエンドに email verify エンドポイントは存在しない（`backend/app/api/v1/endpoints/auth.py`, `users.py` grep で verify系エンドポイント無し。`verified_at` は operator審査専用でユーザーのメール確認とは無関係=既知メモと一致）。
- 修正案は legal記載への整合と「確認完了」表示の見直しを提案しており、隣接ファイルへの副作用なし。安全。妥当。

## 2. /password-reset 完全未配線なのに成功断定
**判定: CONFIRMED**
- `page.tsx:90-105`（`onReset`）は `window.setTimeout` のみでAPI呼び出しなし。実在確認。
- `page.tsx:277-281`（STEP4）「パスワードを変更しました。」「新しいパスワードでログインできます。」断定文言・デモ表記なし、実在確認（該当行は270-286と近似・内容一致）。
- `page.tsx:3-5` の方針コメント「虚偽の成功断定は避け、デモ操作である旨を明示する」実在確認、STEP4で不履行。
- バックエンドにパスワードリセット関連エンドポイントは存在しない（grep `reset` は rate-limit系のみ）。ロックアウトリスクの主張は妥当。
- 修正案（本番非公開化 or デモ文言追加）は妥当、副作用なし。

## 3. /create/complete が孤立ページで受付番号・カウントダウン・LINEボタンが偽データ
**判定: CONFIRMED（ただし到達条件に1点補足）**
- `create/page.tsx:306` `router.push(\`/cases/${created.id}?created=1\`)` 実在確認。`/create/complete` への内部リンクはリポジトリ全体で0件（grep該当はCSS/コメントのみ）実在確認。
- `complete/page.tsx:39,45-46`（ランダムlotId）、`21-22,50-70`（localStorageカウントダウン）、`72-76,191-195`（LINE連携=デモトースト）すべて実在確認。
- 補足[実機検証]: `curl http://localhost:3103/create/complete` は307で `/login?callbackUrl=%2Fcreate%2Fcomplete` にリダイレクトされ、未ログインでは到達不可（authミドルウェアが効いている）。ただし**ログイン済みユーザーなら直打ちで到達可能**という指摘の核心は変わらないため判定はCONFIRMEDのまま維持し、影響範囲は「未ログイン第三者」ではなく「ログイン中の全ユーザー」に限定と補足する。
- 修正案（`/cases/[id]` 完了体験へ統合 or リダイレクタ化）は `/create/complete` 自体の改修であり `cases/[id]/page.tsx` `katadzuke-api.ts` の編集対象外制約に抵触しない。安全。

## 4. 通知チャネル（メール/LINE）のページ間矛盾
**判定: CONFIRMED**
- `cases/[id]/page.tsx:319`「業者から入札が届くとメールでお知らせします」、`:534`「まだ入札がありません。入札が届くとメールでお知らせします。」実在確認（編集対象外・指摘のみ）。
- `create/complete/page.tsx:125`「入札が届くとLINEに通知が届きます」実在確認（引用位置は125、137にも"LINEで通知"タグあり）。
- `chat/[id]/page.tsx:360`「新着メッセージはLINEにも通知されます」実在確認。
- `schedule/page.tsx:538`「LINEにも通知が届きます。」（510行にも同種記載）実在確認。
- `mypage/page.tsx:343`「入札・メッセージの通知はLINEで受け取れます」実在確認（見出しは340）。
- `backend/app/services/notify.py` 全文確認: 送信手段はBrevo経由メールのみ（`send_case_created`, `send_bid_received`, `send_bid_selected`, `send_schedule_confirmed` 等）。LINEへのプッシュ送信関数はbackend内に存在しない。
- `notifications/page.tsx:14-27` のコメントでLINE連携はパスワード確認モーダルを挟む明示的オプトインと確認。
- 結論: LINE未連携ユーザーへの「LINEに届く」という断定は事実と乖離。CONFIRMED。修正案（条件分岐文言）は妥当・副作用なし。

## 5. /create STEP1完了ボタンがtitle属性のみで無効理由を提示（スマホで無反応に見える）
**判定: CONFIRMED**
- `create/page.tsx:706` `disabled={!currentItem || currentItem.photos.length === 0 || !checkedHints.has(...)}` 実在確認（引用行701-710と一致）。
- `:707` `title={...}` のみで無効理由提示、実在確認。
- `:564`「商品の状態が正確に確認できる写真を撮影しました」チェックボックス実在確認。
- `title`属性はホバー前提でタップ操作では表示されないというのは一般的なモバイルUXの既知事実であり、`capture="environment"` 属性使用（スマホ撮影想定）と合わせて論理的に妥当。修正案（インラインヒント常時表示 or スクロール+ハイライト）は他ファイルに影響しない局所修正で安全。

## 6. /signup role="buyer" 選択が送信されず、STEP3で登録内容のように見える
**判定: CONFIRMED**
- `signup/page.tsx:28` `ROLE_LABEL` 実在確認。`:111-112` `signupUser({ email, password, name: name || undefined })` でrole/areaを送っていないこと実在確認。コメントで「area/roleは将来拡張用にUI収集のみ」明記。
- `:223-227` role="buyer" 選択UI、`:230-235` `/business` 案内バナー、実在確認。
- `:260` STEP3確認行「利用目的」表示、実在確認。role=buyerの場合に警告文が追加される分岐は無し（256-262に単純な確認行のみ）実在確認。
- バックエンド `katadzuke-api.ts:523-529 signupUser` の型定義は `email/password/name` のみ。`backend/app/api/v1/endpoints/auth.py:108-114` の `user_signup` もrole列を `email in admin_emails` のみで決定しており、フロントのrole選択を一切参照しない実装であることを実在確認。指摘は完全に裏取りできた。修正案（STEP3に太字注記追加 or buyer選択時に/businessへ誘導）は`signup/page.tsx`単独の変更で他ファイル波及なし、安全。

## 7. /cases と /mypage の重複導線・本流不明確
**判定: CONFIRMED**
- `AppHeader.tsx:34-39` グローバルナビが「マイページ」(`/mypage`) のみを露出し `/cases` への直接リンクなし、実在確認。
- `create/complete/page.tsx:171` `<Link href="/cases">入札状況を確認する</Link>`、`schedule/page.tsx:541` `<Link href="/cases">申し込み状況を確認する</Link>`、`review/page.tsx:359` `<Link href="/cases">` いずれも実在確認、`/cases`遷移で一致。
- `cases/page.tsx:47-111` はシンプルなカード一覧＋`AppHeader`のみ実在確認。`mypage/page.tsx:253-`はユーザーカード統計(281-300)＋サマリーカード(304-)を確認（253-402全域は範囲一致、統計+カード一覧という記述と整合）。さらに`mypage/page.tsx:305`のサマリーカード自体が`/cases`へリンクしており、マイページ内から再度`/cases`に飛ぶ二重構造も確認、指摘の趣旨をむしろ補強。
- 修正案（統合 or 遷移先統一）は両ファイルとも編集対象外指定なし（`cases/page.tsx`は対象外リストに含まれず、`cases/[id]/page.tsx`のみが対象外）。ただし`mypage/page.tsx`側の改修は今回のスコープ外の別作業者領域である可能性に留意。安全性は確保できるが、実施前に`/mypage`側の担当者と調整すべき旨を付記すべき。

---

## 判定集計
CONFIRMED: 7 / 7　PARTIAL: 0　REFUTED: 0

### 棄却・PARTIALのIDと理由
なし（該当ID無し）。ただしID3は「未ログインでは/loginへ307リダイレクトされ直打ち到達できない」という実機検証結果（curl）を補足事項として付記した（判定はCONFIRMEDのまま）。

---

## 見落とされたHigh相当の欠陥（追加発見）

### A. 通知ベルの未読バッジがほぼ全ページで実状と無関係にハードコード表示
- 根拠: `components/kdz/AppHeader.tsx:10`のデフォルトは`unread=false`だが、`web/src/app/review/page.tsx:137,148,181,390`、`web/src/app/schedule/page.tsx:71,274,283,293`、`web/src/app/mypage/profile/page.tsx:259,272,293`、`web/src/app/vendors/[id]/page.tsx:51,62,83`は`<AppHeader unread />`とJSXブール省略記法で**常にtrue固定**。一方`web/src/app/cases/page.tsx:39,49`と`web/src/app/cases/[id]/page.tsx:288,299,315`はpropを渡さず常にfalse固定。実際に未読を計算しているのは`mypage/page.tsx:255`(`negotiatingCount > 0`)と`notifications/page.tsx:303`(`rows.length > 0`)のみ。
- 問題: ユーザーが`/schedule`や`/review`や取引詳細(`/mypage/profile`)を開くたびに、既読・未読を問わず常に赤丸バッジが点灯する。逆に`/cases`系では新着があっても点灯しない。依頼者は「新着通知がある」という誤情報を継続的に見せられ続け、通知ベルへの信頼性が失われる（狼少年効果）。景表法とは別軸だが機能的な虚偽表示であり、依頼者導線全体に及ぶためHigh相当。
- 修正案: `AppHeader`呼び出し元全てで実未読件数（`listMyCases`のbid_count合計や`listTransactions`の未処理件数）から算出した値を渡すよう統一する。もしくは`AppHeader`自体をclient componentにしSWR等で共通フェッチし、呼び出し側でのハードコード指定を廃止する。

### B. /create/complete のカウントダウンがcase単位でなくグローバルlocalStorageキーのため2回目以降の出品で誤表示
- 根拠: `web/src/app/create/complete/page.tsx:21` `const COUNTDOWN_KEY = "katazuke_done_start";`（case_idを含まない固定文字列）、`:51-54`で`window.localStorage.getItem(COUNTDOWN_KEY)`の値が既にあればそれを起点に残り時間を計算し続ける実装を確認。
- 問題: 依頼者が1回目の出品から3日以上経過後に2回目の出品を行うと、新しい案件のはずなのに`formatRemaining`が0以下を返し「終了」と表示される（`:29` `if (remainingMs <= 0) return "終了";`）。逆に短時間で連続出品した場合は1回目の残り時間がそのまま2回目にも表示され、実際の入札受付開始時刻と無関係な数値が出る。リピーター（片付け業者選定を複数回利用するユーザー）ほど発生しやすく、"即時終了"と誤認して業者への案内・入札を待たず離脱するリスクがある。
- 修正案: キーを`katazuke_done_start_${created.id}`のようにcase_id別に分離するか、そもそもURLクエリで受け取ったcase作成時刻（サーバー側`created_at`）を起点に計算する。localStorageの新旧キー混在を避けるため、旧固定キーの値は無視して起点を上書きするマイグレーション処理も併せて入れる。

（3件目は根拠の確度が十分でないため計上しない）

---

保存パス: C:/Users/ko13h/Claude/Projects/ソクウリ/.agent-state/audit/verify-user.md
