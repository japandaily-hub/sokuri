# 依頼者導線 QA監査台帳（第3周・2026-09-04）

対象: 依頼者（一般ユーザー）ルートのみ。`.agent-state/audit/user-journey.md` `verify-user.md` `review-qa.md` で
CONFIRMED・修正済みの項目（/verify-email 断定表現、/password-reset 偽成功、/create/complete 孤立、
LINE/メール文言不統一、AppHeaderBell、/cases と /mypage の重複導線、/signup role未送信、
/create STEP1 disabled理由不可視 等）は再指摘しない。編集除外ファイル
（backend/app/config.py, main.py, core/alert_middleware.py, services/alerts.py, tests/test_alerts.py,
.github/workflows/uptime-alert.yml）は指摘対象にしていない。

---

## High

### H1. NextAuthセッション（30日）とbackend JWT（7日）の有効期限が非同期のため、期限切れ時に英語の生エラー文が露出し再ログイン導線もない
- ルート: `/create` `/schedule` `/review` `/chat/[id]` `/mypage` `/mypage/profile` `/mypage/identity` `/mypage/bank-account`（`/notifications` と `AppHeaderBell` のみ対応済み）
- 根拠:
  - `web/src/lib/katadzuke-api.ts:1415-1425`（`toDisplayMessage`）は `err.status >= 500` のときだけ汎用文言にフォールバックし、401/403/404/409/422/429 はバックエンドの `detail` 文字列をそのまま画面へ返す。
  - `backend/app/api/deps.py:22-24` の401時 `detail="Invalid credentials. Please log in again."`（英語・和訳なし）。
  - `web/src/auth.ts:149`（`session: { strategy: "jwt" }`）に `maxAge` 指定なし＝NextAuthのデフォルト30日セッションが有効なまま残る一方、`backend/app/config.py:59` `jwt_expire_minutes: int = 60 * 24 * 7`＝backend JWTは7日で失効。両者を同期させる仕組み（リフレッシュ・強制ログアウト）は無い。
  - `web/src/components/kdz/Ui.tsx:18-24`（`useToken`）はNextAuthセッションの有無だけを見て `token` を返すため、失効済みJWTでもリクエストは送信され続ける。
  - 401を個別ハンドリングしているのは `web/src/app/notifications/page.tsx:235` と `web/src/components/kdz/AppHeaderBell.tsx:96` のみ（`grep "status === 401" web/src` で確認）。`schedule/page.tsx:109,138,261`、`review/page.tsx:77,120`、`chat/[id]/page.tsx:149,172,233,259`、`mypage/page.tsx:175,180,185`、`mypage/profile/page.tsx:174,192,255,317,350`、`mypage/identity/page.tsx:120,245`、`mypage/bank-account/page.tsx:106,181,219`、`create/page.tsx:308` は全て `toDisplayMessage(e, "<日本語フォールバック>")` を無条件に呼ぶのみ。
- 事象: 週をまたいでログイン状態を維持したユーザー（入札検討〜日程調整〜評価まで数日〜数週間かかる本サービスの想定利用パターンで頻発しうる）が上記いずれかの画面を操作すると、401が発生した瞬間、他の日本語UIの中に "Invalid credentials. Please log in again." という英語の生テキストが表示される。再ログインへの導線（ボタン・リンク）も出ない。特に `/create` のSTEP4送信（`create/page.tsx:308`）でこれが起きると、写真アップロード完了後の最終送信で失敗し、H3（下記）と合わさって作業内容が丸ごと失われるリスクにつながる。
- 再現手順: [推測・時間経過依存] 発行から7日超経過したbackend JWTを保持したまま（NextAuthセッションは30日有効のため）任意の認証必須ページでAPIを呼ぶ操作（例: `/mypage/bank-account` を開く、`/schedule` で確定する）を行う。
- 修正案: `toDisplayMessage` または各画面のcatchで `err.status === 401` を共通ハンドリングし、「セッションの有効期限が切れました。再度ログインしてください」+ `/login?callbackUrl=...` への導線を出す共通コンポーネント/フックを作り、上記全ページで呼び出す。根本対応として `web/src/auth.ts` の `session.maxAge` をbackendの `jwt_expire_minutes` 以下に揃えるか、JWTリフレッシュを実装する。

### H2. 日程確定の完了画面が「メール/LINEでお知らせします」と依頼者自身への通知を約束するが、backendは業者にしか通知しない
- ルート: `/schedule`
- 根拠:
  - `web/src/app/schedule/page.tsx:507`「日程確定後はメールでお知らせします。LINE連携済みの場合はLINEにも届きます。」（確定ボタン直上の案内）、`:535`（完了モーダル内でも同文）。文面はこの画面を操作している依頼者自身に対する一人称的な案内。
  - `backend/app/api/v1/endpoints/transactions.py:443-456`（`confirm_schedule`）は `party != "user"` を403で弾く＝この操作を行うのは常に依頼者本人。
  - 同 `:484-495` で通知に使うのは `operator_email` / `operator_line_user_id`（業者の連絡先）のみ。`notify_dispatch.dispatch_schedule_confirmed`（`backend/app/services/notify_dispatch.py:112-123`）のdocstringも「訪問日程確定通知（**業者宛**）」と明記。依頼者宛のメール/LINE送信呼び出しは同エンドポイント内に存在しない（`grep dispatch_schedule_confirmed backend/app/api/v1/endpoints/*.py` の一致は`transactions.py:490`の1箇所のみ）。
- 事象: 依頼者が日程を確定すると画面上は「メール/LINEでお知らせします」と表示されるが、実際にメール/LINEが届くのは業者側だけで、確定操作をした依頼者自身には何も届かない。タブを閉じた後に「確認のメールが来ない」と不安になり問い合わせが発生する、または実際に確定できているか信用できず再度サイトへ戻って重複確認する導線ロスが起きる。
- 再現手順: 依頼者としてログイン → 成約済み取引で `/schedule` を開き日程を確定する → 完了モーダルの文言（`メールでお知らせします`）を確認 → 依頼者本人のメール/LINEには日程確定メールが届かないことをbackendコード上で確認済み（実メール受信の実機確認はスコープ外）。
- 修正案: 文言を「業者へ日程確定の通知が送られます」等、実際の宛先に合わせて修正する。あわせて依頼者自身にも確定内容のメール/LINE通知を送りたいのであれば、`confirm_schedule` 内で依頼者（`txn.case.user`）宛の `dispatch_schedule_confirmed` 相当の呼び出しを追加する（`send_schedule_confirmed`/`push_schedule_confirmed` は現状「業者宛」固定文言のため、依頼者向けの別文言関数が必要）。

### H3. `/create` の撮影・入力内容が全てReactのメモリ内stateのみで保持され、リロード・バックグラウンド化・誤操作で無警告に全消失する
- ルート: `/create`
- 根拠:
  - `web/src/app/create/page.tsx:102`（`const [items, setItems] = useState<DraftItem[]>([]);`）が唯一のデータ保持箇所。`grep -n "localStorage\|sessionStorage\|beforeunload"` は本ファイルで0件（実在確認）。
  - 商品上限 `ITEM_LIMIT = 30`（`:31`）・商品あたり写真上限 `ITEM_PHOTO_LIMIT = 12`（`:30`）・案件合計 `CASE_PHOTO_LIMIT = 150`（`:28`）と、複数商品・多数写真を前提にした長時間作業を想定した設計であるにもかかわらず、離脱防止（`beforeunload`）や下書きの永続化が一切ない。
  - スマホのカメラ撮影（`capture="environment"` 前提のUI、`HINT_ITEMS`のコメント参照）を主動線としており、電話着信・他アプリ切替・OSによるバックグラウンドタブのメモリ回収（Android Chromeで一般的）が起きやすい利用シーンだが、復帰時の状態復元手段がない。
- 事象: 依頼者が10点・数十枚の写真を撮り終えた直後にブラウザが誤って更新される／タブが非アクティブ化されOSに回収される／端末を横向きにした拍子に誤タップでリロードされる、などが起きると、確認や警告なしに商品データ・撮影済み写真が全て消え、STEP1からの完全なやり直しになる。H1（401でSTEP4送信が失敗）と組み合わさると被害はさらに拡大する。
- 再現手順: `/create` でSTEP1にて複数商品を撮影 → ブラウザの更新ボタンを押す、またはタブを閉じて開き直す → 撮影内容が跡形もなく消えることを確認（コード上、復元経路が存在しないため実機検証なしで再現性は確定的）。
- 修正案: 最低限 `beforeunload` イベントで「入力中の内容が失われます」の標準確認ダイアログを出す。可能であれば `items`/`loosePhotos` のメタデータ（File自体は保存できないため撮影枚数・商品名など）を `sessionStorage` に定期保存し、復帰時に「前回の続きから再開しますか」を出す。

---

## Medium

### M1. `/cases` が現行デザインシステム（人の森整合テーマ）未適用のまま残存し、同じ依頼者導線内で見た目が一段階古い
- ルート: `/cases`
- 根拠:
  - `web/src/app/cases/page.tsx` は専用CSS importが無く（`grep "\.css" web/src/app/cases/page.tsx` 0件）、`web/src/components/kdz/Ui.tsx` の汎用Tailwindコンポーネント（`Card`/`PageShell`/`StatusBadge`/`btnPrimary`）のみで構成。同コンポーネントの実装（`Ui.tsx:62,83,114,124,126,128,130`）は `rounded-none border border-slate-200 bg-white` `text-slate-900` `bg-brand-600` 等、汎用Tailwindのグレースケール/角丸ゼロ止まりで、書体（明朝）や額装フレーム等のブランド固有トークンが乗らない。
  - 対照的に `mypage/page.tsx:18` は `import "./mypage.css"`、`schedule/page.tsx` も専用 `schedule.css`（`--radius` 等のCSSカスタムプロパティを使用、`schedule.css:104,114,152,263,286`）を持つ。他の依頼者ルート（identity・bank-account・review等）も同様に専用CSSを持つ。
  - `.agent-state/PROJECT_STATE.md:13`「人の森整合テーマ…は全41ルートへ適用済み・push 済み・本番反映済み」との記載と、`/cases` の実装が食い違う。
- 事象: `create/complete` や `schedule` `review` 等の完了直後CTA（既知の重複導線問題、user-journey.md #7参照）が依然として `/cases` へ遷移する箇所が残っている場合、依頼者は明朝体・額装フレーム調に統一された他画面から、書体もカードの見た目も異なる汎用Tailwind画面へ突然切り替わり、同一サービス内という一貫性が損なわれる。
- 修正案: `/cases` を廃止し `/mypage` へ統合する（user-journey.md #7の修正案と同じ方向）のであれば本件は自然に解消する。存続させる場合は他ルートと同じ専用CSS・デザイントークンを適用する。
- [推測] 実際の見た目の崩れ具合はブラウザでの目視確認をしていないため未検証。専用CSS不在という構造的事実のみコードで確認済み。

---

## 確認したが問題なし（観点別）

- **二重送信ガード**: `/schedule` の日程確定ボタン（`schedule/page.tsx:240,243-244,499`）・`/review` の評価送信（`review/page.tsx:100-101`）・`/mypage/bank-account` の口座保存/削除（`bank-account/page.tsx:135,153,200-201`、ボタンの`disabled={saving|deleting}`も確認）・`/create` のSTEP送信（`create/page.tsx:772`, `disabled={submitting}`）は全て `submitting`/`busy`/`saving` フラグと関数冒頭の早期returnで二重送信を防いでいる。
- **写真アップロードの再送重複防止**: `/create` の `submit()`（`create/page.tsx:293-330`）は `photo.uploadedKey` を保持し、再試行時に既アップロード済み写真を再送しない設計を確認。
- **「上位3社から選ぶ」表現と実装の食い違い**: `web/src/app`配下を "上位3社" 等のキーワードでgrepしたが該当箇所は0件（現行コピーには当該表現が存在しない。過去のTODO記載は既に是正済みと判断）。
- **業者宛LINE/メール通知のリンク先**: `backend/app/services/notify.py` `line_notify.py` の `push_bid_selected` `send_bid_selected` `push_schedule_confirmed` はいずれも `/operator/transactions/{id}` を指しており業者向けとして正しい（H2は依頼者側の文言表示の問題であり、この2関数自体の宛先設計は妥当）。
- **依頼者宛の入札受領通知**: `dispatch_bid_received`（`notify_dispatch.py:126-141`）は依頼者の `line_user_id`/`email` を受け取り `/cases/{case_id}` へのリンクで正しく通知する設計を確認。
- **モバイル375px幅のグリッド崩れ**: `schedule.css` の2カラムレイアウト（`grid-template-columns: 1fr 300px`, line 95）は `@media (max-width: 720px)`（line 436）で単カラムに切り替わることを確認。`create.css` の `purpose-grid`/`field-row` も同様に720px未満？相当のブレークポイントで単カラム化（`create.css:175-176`）。コード上は375px幅を十分にカバーしている。
- **/cases の空状態案内**: `cases/page.tsx:60-66` は「まだ案件がありません。」+「最初の依頼をつくる」CTAを明示しており、初回ユーザー向け案内は存在する（デザイン不一致はM1として別途指摘）。

---

## 未解決・確認できなかった点

- H1・H2ともに、実際のメール/LINE受信結果や本番でのJWT失効挙動はブラウザ実機・受信箱での確認をしておらず、コード上の裏付けのみ（禁止事項によりファイル編集・実際のログイン操作は範囲外）。
- H3の「タブのバックグラウンド回収でReact stateが消えるか」はAndroid Chromeの一般的挙動からの推論であり、対象端末での実機再現はしていない。
- アクセシビリティ（aria/label/フォーカス）を `/login` `/signup` `/mypage/profile` 等で確認したが、`Field`/`PasswordField` 等の共通コンポーネントが `htmlFor`/`id` を正しく紐付けており、コードレベルでの明確な違反は発見できなかった（フォーカスリング等の視覚的検証は未実施）。
- M1で指摘した `/cases` の見た目の実害度は、ブラウザでの目視確認をしていないため未検証（構造的事実のみ確認）。
- 通知文面と画面文言の突き合わせは `/schedule` `/chat` `/mypage` 系のみ実施。`/mypage/withdraw`（退会）に伴う通知文面の突き合わせは未実施。
