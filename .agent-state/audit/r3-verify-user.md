# r3-user.md 独立検証（敵対的レビュー・2026-09-04）

検証者: 立案者と無関係の独立QA。全項目を実コードで再読し、判定した。
`backend/app/config.py` `backend/app/main.py` 等の編集除外ファイルへの修正提案は却下対象として扱う。

集計: **CONFIRMED 3 / PARTIAL 2 / REJECTED 0**（High 3件のうち1件を Medium へ降格、M1 を Low へ降格）

---

## H1. NextAuthセッション(30日)とbackend JWT(7日)の非同期 → 英語の生エラー露出・再ログイン導線なし

**判定: CONFIRMED（重大度 High 維持）**

根拠（全て実在確認）:
- `web/src/lib/katadzuke-api.ts:1414-1425` `toDisplayMessage`。`err.status >= 500` のみ fallback、
  それ未満は `err.message`（backend detail）をそのまま返す。台帳の記載どおり。
- `backend/app/api/deps.py:21-25` `_CRED_EXC` の `detail="Invalid credentials. Please log in again."`（英語）。
  この例外は `_decode`（`deps.py:29-42`）経由で**全認証必須エンドポイント**に効く。
- `web/src/auth.ts:148-149` `session: { strategy: "jwt" }`、`maxAge` 指定なし。
- `backend/app/config.py:59` `jwt_expire_minutes: int = 60 * 24 * 7`。
- `web/src/components/kdz/Ui.tsx:17-23` `useToken` は `data?.accessToken` を素通しし、失効判定を持たない。
- 401個別ハンドリングは `web/src/app/notifications/page.tsx:235` と
  `web/src/components/kdz/AppHeaderBell.tsx:96` の2箇所のみ（+ `web/src/lib/line-link.ts:162` の
  LINE連携専用パス。台帳は未言及だがこれは reauth_required へ正しく分岐しており問題なし）。
  `grep -rn "status === 401" web/src` で再現。

**台帳への重要な補正（2点）**

1. **再現性は「推測・時間経過依存」ではなく決定的。**
   `backend/app/api/deps.py:44-60` `assert_user_not_revoked` は
   「`deleted_at` 設定済み」「JWTの `iat` < `password_changed_at`」でも同じ `_CRED_EXC` を投げる。
   → 別端末でパスワード再設定した直後、旧タブは**7日待たずに即座に**英語文言に落ちる。
   台帳の「[推測・時間経過依存]」の但し書きは外してよい。重大度 High は据え置きで妥当。

2. **修正案の後半（`session.maxAge` を揃える）は効かない。**
   NextAuth の JWT セッションはアクセスのたびに `updateAge`（既定24h）でスライド更新されるため、
   `maxAge` を7日に縮めても**継続利用中のユーザーのセッションは失効しない**一方、
   `auth.ts` の `jwt` コールバックに accessToken の再発行経路が無いため backend JWT は発行時刻のまま固定。
   結果、台帳が想定する「両者の同期」は maxAge 調整では達成できない。
   さらに `jwt_expire_minutes` 側の変更は `config.py`（編集除外）に触れるため**却下**。
   → 実際に採るべきは修正案前半のみ: `err.status === 401` を共通ハンドリングし
   「セッションの有効期限が切れました」+ `signOut()` → `/login?callbackUrl=...` を出す共通フック。
   これなら web 側だけで閉じ、編集除外にも抵触しない。

**修正案への注意**: 401をグローバルに signOut へ流すと、`line-link.ts:162` の
reauth_required（401を正常系として扱う）が誤って強制ログアウトされる。共通化はフック側で
opt-out できる形にすること。

---

## H2. 日程確定完了画面が依頼者自身への通知を約束するが backend は業者にしか通知しない

**判定: CONFIRMED（事実）／ 重大度は High → **Medium** へ修正（PARTIAL）**

事実面は全て一致:
- `web/src/app/schedule/page.tsx:507`（確定ボタン直上）と `:535`（完了モーダル内）に
  「メールでお知らせします。LINE連携済みの場合はLINEにも届きます。」
- `backend/app/api/v1/endpoints/transactions.py:451-455` で `party != "user"` を403 →
  操作者は常に依頼者本人。
- 同 `:484-495`：`operator_email` / `operator_line_user_id` のみを
  `notify_dispatch.dispatch_schedule_confirmed` に渡す。依頼者宛の通知呼び出しは
  当該エンドポイント内に存在しない（`background.add_task` はこの1件のみ）。
- `backend/app/services/notify_dispatch.py:112-124` docstring「訪問日程確定通知（業者宛）」。

**重大度を下げる根拠（台帳が触れていない緩和材料）**:
- `transactions.py:474-482` で `kind="schedule_confirmed"` の system Message を取引に追加しており、
  依頼者はチャット（`/chat/[id]`）と `/mypage` で確定内容を再確認できる。
  「確定できたか分からない」状態そのものは発生しない。
- 実害はデータ喪失・誤送信ではなく「届かない通知を約束したコピー」＝信頼と問い合わせコスト。
  同種の指摘（`/verify-email` の断定表現）が Medium 相当で処理されてきた経緯とも整合する。
→ リリース前に直すべきだが、High（導線が破綻する）ではなく Medium（文言不正確）が妥当。

**修正案への注意**: 台帳の代替案「依頼者にも送る」を採る場合、
`backend/app/services/notify.py` / `line_notify.py` の `send_schedule_confirmed` /
`push_schedule_confirmed` は**リンク先が `/operator/transactions/{id}`（業者画面）に固定**されている
（台帳の「問題なし」節の記述と一致）。依頼者宛に流用すると業者専用URLへ誘導する新規バグになる。
依頼者向け関数の新規追加が必須。**最小・安全な是正は `schedule/page.tsx:507,535` の文言修正のみ。**

---

## H3. `/create` の入力が React state のみで、リロード等で無警告に全消失

**判定: CONFIRMED（重大度 High 維持）**

- `web/src/app/create/page.tsx:102` `const [items, setItems] = useState<DraftItem[]>([]);`、
  `:103` `loosePhotos` も同様。
- `grep -n "localStorage\|sessionStorage\|beforeunload" web/src/app/create/page.tsx` → **0件**（再現確認）。
- 上限値 `CASE_PHOTO_LIMIT = 150`（`:28`）/ `ITEM_PHOTO_LIMIT = 12`（`:29`）/ `ITEM_LIMIT = 30`（`:31`）。
- **台帳より強い根拠を追加**: 写真のアップロードは撮影時ではなく `submit()` 内で初めて行われる
  （`create/page.tsx:300-330`：`if (!key) { const presign = await uploadCasePhoto(...) }`）。
  つまり STEP4 送信前は**全 File オブジェクトがブラウザメモリ上にしか存在しない**。
  台帳の「復元経路が存在しない」は構造的に確定。
- 失敗時の復旧は担保されている（`:350-353` の catch で `setSubmitting(false)`、
  `uploadedKey` 保持により再送時の重複アップロードなし）。消失リスクは「送信前」に限定される。

**修正案への注意（台帳の案は半分しか成立しない）**:
`sessionStorage` に保存できるのは商品名・枚数などのメタデータのみで、`File` は直列化できない。
メタデータだけ復元すると「商品は戻ったのに写真だけ空」という状態になり、
ユーザーは復元できたと誤認して不完全な案件を送信しうる（現状より悪化しうる）。
→ 安全な最小対応は `beforeunload` の確認ダイアログのみ。
本質的な復元を望むなら「撮影時に presign アップロードして `storage_key` を保持する」設計変更
（既に `uploadCasePhoto` は単体で呼べる）以外に成立する手はない。

---

## M1. `/cases` がデザインシステム未適用

**判定: PARTIAL（中核主張は誤り）／ 重大度 Medium → **Low** へ修正**

**REJECT する部分（台帳の根拠が実コードと食い違う）**:
- 「書体（明朝）が乗らない」は**誤り**。テーマは per-page CSS ではなく
  `web/src/app/globals.css:18` の `@import "./katazuke.css" layer(components)` で**全ページに適用**される。
  `web/src/app/katazuke.css:53-57` で `--serif`（Noto Serif JP 系）を定義し `--head:var(--serif)`
  `--sans:var(--serif)`、`:70` `body{font-family:var(--sans);…}`、`:75` `h1,h2,h3,h4,h5{font-family:var(--head);…}`。
  → `/cases` も明朝で描画される。
- 「角丸ゼロ止まり」も逆。`web/tailwind.config.ts:14` で `borderRadius` を全段 `0px`、
  `:15` で `boxShadow` を全段 `none` に固定済み。`Ui.tsx` の `rounded-none` は角丸0テーマそのもの。
- 「ブランド固有トークンが乗らない」も部分的に誤り。`tailwind.config.ts:26` の `brand-600: "#1447e0"` は
  `katazuke.css:11` の `--primary:#1447e0` と**完全一致**（`btnPrimary` の `bg-brand-600` は正典色）。
  ※ 台帳の「苔色」表現は現行 katazuke.css（ブルー #1447e0）と不一致。古い記録の引きずり。

**維持できる部分（実在する差分）**:
- `Ui.tsx:62`（`border-slate-200`）、`:114-131`（`bg-sky-100` `bg-amber-100` `bg-emerald-100` 等）、
  `:126`（`text-slate-500`）は Tailwind 既定パレットで、正典トークン
  `--line:#dce3ea` / `--body-soft:#63707b` / `--green:#15803d`（`katazuke.css:26,21,37`）と別値。
  → 実際の差分は「罫線・補助文字・バッジの色味が微妙に違う」レベル。書体・形状・主色は一致。
- **台帳が見落としている拡張**: `/cases/[id]`（案件詳細）も専用CSSを持たない
  （`web/src/app/cases/[id]/page.tsx:9-25` に `.css` import なし）。`/create` 完了後の着地先は
  `create/page.tsx:349` `router.push(\`/cases/${created.id}?created=1\`)` であり、
  こちらの方が通過率が高い。M1 を残すなら対象は `/cases` 単体ではなく `/cases` 系2画面。

**修正案への注意**: 台帳の「`/cases` を廃止して `/mypage` へ統合」は影響が大きい。
`/cases` への参照は `mypage/page.tsx:315,323,331`、`chat/[id]/page.tsx:273`、
`notifications/page.tsx:280`、`applications/page.tsx:20`、`result/page.tsx:19`、
`cases/[id]/page.tsx:818` に分散し、さらに**依頼者宛の入札受領通知のリンク先が `/cases/{case_id}`**
（`notify_dispatch.py:126-141`）＝**既に送信済みの通知メール/LINEのリンクが死ぬ**。
廃止するならリダイレクト維持が必須。Low 判定である以上、リリース前対応は不要と考える。

---

## 「確認したが問題なし」節の抜き取り検証（3項目）

| 項目 | 判定 |
|---|---|
| `/review` の二重送信ガード | **妥当**。`review/page.tsx:100-101` `if (busy \|\| !token \|\| !txn \|\| star === 0) return;` → `setBusy(true)`、`:121` finally で解除。断定は正しい。 |
| モバイル375px | **結論は妥当だが引用が不正確**。`create.css:174` のブレークポイントは `@media (max-width: 480px)` であり台帳の「720px未満相当」は誤り。ただし 375px < 480px なので `purpose-grid`/`field-row` は単カラム化する（`create.css:175-176`）。結論に影響なし。 |
| 「上位3社」表現 | **妥当**。`grep -rn "上位3社\|上位３社\|3社" web/src` → 0件を再現。 |

---

## 追加発見（台帳に無い High、最大3件）

### A1[High]. 案件作成APIが Gemini 画像解析をリクエスト同期で実行し、フロントに一切のタイムアウト/中断手段が無い

- `backend/app/api/v1/endpoints/cases.py:205` `case.ai_summary, item_results = await generate_case_ai(...)`
  ＝ POST `/cases` のレスポンスが**最大30商品×12枚の画像解析の完了までブロックされる**
  （BackgroundTasks へ逃がしていない。同ファイル `:258` の `notify.send_case_created` は
  `background.add_task` に載っているので、意図的な使い分けではなく同期実行が既定）。
- `grep -n "AbortSignal\|timeout\|signal:" web/src/lib/katadzuke-api.ts` → **0件**。
  fetch にタイムアウトも中断も無く、`create/page.tsx:337` の
  `setProgress("AIが案件を要約しています…")` のまま無限に待つ。キャンセルUIも無い。
- H3 と直列に効く: 写真アップロードは完了しているが `items`/`loosePhotos` はメモリのみ。
  ユーザーがしびれを切らしてリロードすれば H3 の全消失に直行する。
- [未検証] 実際に Render/Vercel のプロキシ側タイムアウトに到達するかは実測していない。
  `cases.py:234` に `ai_summary` のフォールバック（`f"利用目的: {case.purpose}。写真 {n} 枚。"`）があるため
  例外時はデグレード成功する可能性がある。**確定しているのは「同期実行」と「クライアント側タイムアウト皆無」の2点**。
- 最小対応: クライアント側に `AbortSignal.timeout()` と再試行導線を入れる（`uploadedKey` 保持済みなので再送は安価）。

### A2[High→H1へ統合]. パスワード変更・退会後の旧セッションが同じ英語文言で固まる
H1 の補正1に記載（`deps.py:44-60`）。独立項目ではなく H1 の再現性を確定させる根拠として扱うべき。

### A3. 該当なし（3件目に相当する新規 High は発見できなかった）
`/cases/[id]` の不可逆操作は `window.confirm` で保護済みを確認:
`cases/[id]/page.tsx:269-270` の `act(fn, confirmMsg)` と `:598-601`（業者決定時に
「決定後、業者へ住所詳細が開示されます。」を明示）。ここに指摘は立たない。

---

## (b) 全項目を修正しても依頼者導線がリリース可能にならないケース

**ある。** `.agent-state/PROJECT_STATE.md:22` の記載どおり、別セッションが
「業者の入札取り下げ」を廃止し「依頼者の出品取り下げ（`cancel_case`）」へ置換する作業を
**同じ作業ツリー上で未コミットのまま進行中**で、対象に
`web/src/app/cases/[id]/page.tsx` と `web/src/lib/katadzuke-api.ts`、
backend 側 `cases.py`（`:324` `出品を取り下げる（依頼者本人のみ・open/bidding のみ）`）が含まれる。
本台帳の H1〜M1 は全てこの2ファイル群の**外側**の問題であり、全部直しても
依頼者導線の中核画面（案件詳細＝入札比較・成約・取り下げ）は
半分移行した未マージ状態のままリリース判定に入れない。
台帳の項目消化とは独立に、この移行の完了・整合テスト（取り下げ後の入札状態・
業者側表示・通知文言）が完了することがリリースの必要条件になる。

---

## 検証の限界

- ブラウザ実機での表示確認は行っていない（M1 の色味差分の体感度、A1 の実タイムアウト到達は未実測）。
- メール/LINE の実受信は未確認。H2 は backend コードの呼び出し有無のみで判定した。
- `backend/app/config.py` `main.py` は編集除外のため読み取り検証のみ実施し、修正提案には含めていない。
