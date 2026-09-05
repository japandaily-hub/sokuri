# r10-user 独立検証（依頼者導線・立案者と無関係な再検証）2026-09-05

判定基準: CONFIRMED=事実かつ重大度妥当 / PARTIAL=事実に誤りか重大度過大 / REJECTED=事実誤認または TODO 03 重複。
検証方法: 台帳の全 file:line を実ファイルで照合。backend スキーマ・保護ルート定義まで遡って裏取り。

## 集計

| 判定 | 件数 |
|---|---|
| CONFIRMED | 10（H2・H3・M1〜M9 のうち9件） |
| PARTIAL | 3（H1・M3・M6） |
| REJECTED | 0 |
| 追加発見 | High 1・Medium 1 |

重大度の純増減: High 3 → High 3（H1 を Medium へ降格、ADD-H1 を High として追加）。Medium 9 → 11。

---

## High

### R10-H1 → **PARTIAL・重大度 High → Medium**

事実として正しい部分:
- `/signup` の `AREAS` は 8 択で大阪府・愛知県・福岡県・その他を含む（`web/src/app/signup/page.tsx:17-26`）。エリアは必須（検証 `:95-98`、UI `:204` 相当の `label>お住まいのエリア<span className="req">必須`）。
- `/create` の `PREFECTURES` は 4 都県のみ（`web/src/app/create/page.tsx:25`）、既定値は `PREFECTURES[0]`＝東京都（`web/src/app/create/page.tsx:112`。台帳の `:113` は 1 行ずれ）。
- 対応エリア 4 都県の記載は `web/src/app/business/page.tsx:79` に存在。

**誤りが 2 点ある。**

1. **「LP に対応エリアの記載が無い」は事実誤認。** `web/src/app/page.tsx:106` に `<b>東京・千葉・埼玉・神奈川</b>` ＋「順次エリア拡大中」が assure-item として明示されている。H1 の修正案「LP に対応エリアを 1 行表示する」は既に実装済みの要求。
2. **「出品 STEP3 で詰まる」は成立しない。** `/create` STEP3 の都道府県セレクトは 4 都県から必ず 1 つ選べ（既定 東京都）、`canNext()` は step===2 で `city` のみを要求する（`web/src/app/create/page.tsx:364-368`）。backend も `CaseCreateRequest.prefecture` に許容リストを持たず `Field(min_length=1, max_length=32)` のみ（`backend/app/schemas_katadzuke.py:584`）。つまり誰も出品段階でブロックされない。

さらに、**H1 が問題視した /signup のエリア値はそもそも送信されず破棄される（H3）** ため、「登録者のエリア」というデータは存在しない。H1 の実害は「対応外エリアの選択肢を必須項目として提示している」という期待値の誤生成のみに縮む。これは H3 と同一根で、H3 の修正案 (a)/(b) のどちらを採っても同時に解消する。

- 重大度修正: **High → Medium**（利用者は詰まらない。既定 東京都のまま気づかず誤エリアで出品しうる、という副次リスクは残るが「詰まる」ではない）。
- 修正案（最小構成）: `signup/page.tsx:17-26` の `AREAS` を対応 4 都県＋「その他（対応エリア外）」の 5 件に絞る。副作用なし（`AREA_LABEL` は同配列から導出、`area` は送信されないため backend 影響ゼロ）。LP への追記は不要。

### R10-H2 → **CONFIRMED・High 維持**

- `capture="environment"` は 2 箇所とも実在（まとめ撮影 `web/src/app/create/page.tsx:578`、商品ごと撮影 `:664`）。ラベルは両方とも「写真を撮影・選択」（`:574`、`:660`）。
- `/photo-guide` は「床・机に並べて全体写真を撮る」等、事前撮影を前提にした手順書（`web/src/app/photo-guide/page.tsx:30-31`）。台帳の記載どおり。
- 挙動根拠: HTML Media Capture 仕様上 `capture` は「UA は指定のキャプチャデバイスを使うべき」の指示であり、iOS Safari は `capture` 付きでカメラアプリへ直行しフォトライブラリの選択肢を出さない。Android Chrome も同様にカメラを直接起動する（`capture` を外すとファイルピッカーとカメラの両方が出る、というのが Android 側の一般的な回避策として知られている）。
- **台帳が触れていない、コードだけで確定できる補強事実**: `capture` と `multiple` は併存できない。カメラ直起動時は 1 回 1 枚しか返らないため、`multiple`（`:579`、`:665`）と `ITEM_PHOTO_LIMIT = 12`（`:32`）を前提にした「全方位＋アップを数枚」の撮影 UX が、ギャラリー選択可否の議論とは独立に成立しない。この 1 点だけで High は維持される。
- 修正案の妥当性: **`capture` 属性を 2 箇所から削除するのが最小構成で正しい**。`accept="image/jpeg,image/png,image/webp"` は残るため、iOS/Android とも「カメラで撮影／ライブラリから選択」の標準ダイアログに戻り、`multiple` も機能する。台帳の第 2 案（2 ボタン併置）は `capture` 付き input を追加する分だけ state と ref が増えるので、まず削除だけで足りる。副作用: なし（`handleItemFileChange` / `handleLooseFileChange` は入力経路に依存しない）。

### R10-H3 → **CONFIRMED・High 維持**

- backend `UserSignupRequest` は `email` / `password` / `name` の 3 フィールドのみ。`area` も `role` も無い（`backend/app/schemas_katadzuke.py:29-32`）。エンドポイントも body からその 2 値を読む箇所が無い（`backend/app/api/v1/endpoints/auth.py:167-176`）。
- web 側も `signupUser({ email, password, name })` のみ（`web/src/app/signup/page.tsx:112`）。コード先頭のファイル docstring（`:4-5`）と `:111` のインラインコメントが「UI 収集のみ」と自認している。
- 確認画面には「エリア」「利用目的」が登録内容として並ぶ（`web/src/app/signup/page.tsx:264-265`）。STEP2 の説明文「適切な業者をマッチングするために使用します。」（`:195`）は、実装上どこにも使われない値についての記述であり、**データ利用目的の不実表示**にあたる。High 妥当。
- 修正案: 台帳の (b)（必須解除＋文言削除）が最小構成。(a)（backend へ渡す）は `UserSignupRequest` にフィールド追加＋`User` への保存＋`prefecture_to_residence_area` との整合が必要で、`/mypage/profile` の住所由来 `residence_area` 自動決定（`backend/app/api/v1/endpoints/users.py:107-120`）と二重情報源になる副作用がある。**(b) を推奨**。

---

## Medium

| # | 判定 | 検証結果 |
|---|---|---|
| M1 | **CONFIRMED** | `web/src/app/cases/[id]/page.tsx:423` が `flex items-start justify-between gap-3`、案内ブロックは第3子で `mt-3 w-full`（`:437-444`）。flex 子の `w-full` は他 2 子と幅を奪い合うため縮む。行番号も完全一致。修正案（flex 行の外へ移動）は妥当・副作用なし。 |
| M2 | **CONFIRMED** | 落札額 `cases/[id]:787`／成約額 `chat/[id]:364`／成約買取額 `schedule:343`／買取額 `schedule:482`／総買取額 `mypage:328`。同カード内の見出しが「成約:」（`cases/[id]:783-784`）である点も一致。5 表記は多い。 |
| M3 | **CONFIRMED（cite 1 件誤り）** | `mypage:155`「出品をはじめる」、`cases/page.tsx:52`「マイ案件」・`:56`「新しく依頼する」・`:65`「最初の依頼をつくる」、`create:890`「この内容で依頼する」いずれも一致。**ただし「この内容で出品します」の step-desc は `:802` であり、台帳の「`:790` 付近」は誤り**（`:790` はエレベーターのチェックボックス）。substance は成立。 |
| M4 | **CONFIRMED** | `mypage:335,343,351` の 3 カードすべて `href="/cases"`。`cases/page.tsx` にタブ・フィルタ・クエリ受けは無く単一 grid（`:69`）。 |
| M5 | **CONFIRMED** | `isBiddingCase` は `(open\|bidding) && bid_count > 0`（`mypage:56-57`）、チップは `status==="open"` を無条件に「入札受付中」（`mypage:63`）。サマリー補助文「入札が届いています」（`mypage:341`）。入札 0 件で語が矛盾するのは事実。 |
| M6 | **CONFIRMED（cite 1 件誤り）** | `canNext()` の step===2 分岐（`create:364-368`）と `disabled={!canNext()}`（`create:882`）は一致。**STEP1 のインライン理由表示は `create:865-870`（`role="status"` の `p.field-error`「写真を1枚以上追加してください」）であり、台帳の `:906-913` は離脱確認モーダルの本文で誤り**。扱いの不揃いという指摘自体は成立。 |
| M7 | **CONFIRMED** | 投稿後は `Notice tone="success"` のみ（`cases/[id]:992-995`）、直後の導線は「← マイ案件一覧へ」（`:1048-1050`）。`/review` 側には `/create` への「次のアクション」あり（`review:338`）。 |
| M8 | **CONFIRMED・TODO 03 重複ではない** | `window.confirm` は当該ファイルに 0 件（`ConfirmModal` は `:14` import・`:1054` 使用）。TODO 03 の「ユーザー側 `/cases/[id]` が window.confirm のまま」は **r8 で解消済みの陳腐化エントリ**。残存しているのは `window.prompt` 2 箇所で、`:753-754` は `if (reason === null) return;` で中止、`:966` は `?? null` でそのまま `setConfirmState` へ進む。非対称は事実。修正案（`:966` を `:754` に揃える）は 1 行で副作用なし。 |
| M9 | **CONFIRMED** | 401／403 `account_suspended` は `signOut` 後に `window.location.href` で遷移（`web/src/lib/katadzuke-api.ts:687-707`）。遷移条件 `isProtectedRoutePath(pathname)` に `/create` は含まれる（`web/src/lib/protected-routes.ts:22-32` の `USER_PROTECTED_PATHS`）ため、抜けは実在。`/create` の未ログインガードは `router.replace`（`create:93-95`）で `beforeunload` を通らない。`skipAuthRedirect` オプションは既に実装済み（`katadzuke-api.ts:716,736,764`）なので修正案は既存 API の利用のみ・副作用小。 |

---

## 追加発見（台帳が同観点で見落としたもの）

### ADD-H1（**High**）. 住所プロフィールは 47 都道府県を必須登録でき、出品は 4 都県のみ — 本命の入口/出口不一致は `/signup` ではなく `/mypage/profile`

- H1 は「値が破棄される `/signup`」を見て、**実際に永続化される住所フォームを見落としている**。
- `/mypage/profile` の都道府県セレクトは backend の `PREFECTURES` をそのまま列挙する 47 件（`web/src/app/mypage/profile/page.tsx:32,623`）、必須（`:612`、検証 `:214`）。backend も 47 件の `_PREFECTURE_SET` で検証して受理する（`backend/app/schemas_katadzuke.py:268-278,327-332`）。
- 保存すると `residence_area` が自動導出され、大阪・愛知・福岡は専用キーを持つ（`backend/app/schemas_katadzuke.py:280-288`、`backend/app/api/v1/endpoints/users.py:119-120,163-167`）。つまり **backend は対応外エリアの依頼者を正規のデータとして受け入れる設計になっている**のに、出品 UI は 4 都県しか出さない（`web/src/app/create/page.tsx:25`）。
- 実害: 大阪府在住として住所を登録し終えた利用者が `/create` STEP3 で自分の県を選べず、既定の東京都のまま出品するか離脱する。H1 が主張した「詰まる」は `/signup` では起きないが、**ここでは実際に起きる**。
- 修正案（最小）: `/create` STEP3 の都道府県セレクトの直上に「現在の対応エリアは東京・千葉・埼玉・神奈川です」を 1 行出し、プロフィール住所の都道府県が 4 都県外なら `role="status"` で警告する。既定値を `PREFECTURES[0]` 固定から「プロフィール住所が 4 都県内ならそれ、外なら未選択」に変える案は `canNext()` に都道府県必須を足す必要があり影響が広がる。副作用: 表示追加のみなら無し。

### ADD-M10（Medium）. `POST /cases` の `prefecture` だけ許容リスト検証が無い（住所 API とは非対称）

- `CaseCreateRequest.prefecture` は `Field(min_length=1, max_length=32)` のみで値域チェックが無い（`backend/app/schemas_katadzuke.py:584`）。同じファイルの `UserAddressUpdateRequest.prefecture` は `_PREFECTURE_SET` で弾く（`:327-332`）。`purpose` は `CasePurpose` で Literal 化済み（`:583`、TODO 03 の r7 項目は解消済み）なので、**未検証で残っているのは prefecture だけ**。
- 実害: API 直叩きや将来の UI 変更で対応外エリア・任意文字列の案件が `open` として業者一覧に載る。業者には「エリア外への訪問買取は受け付けていません」と案内しているため（`web/src/app/business/page.tsx:79`）、その案件は入札ゼロで放置される。
- 修正案: 対応 4 都県の `Literal` か、`_PREFECTURE_SET` と同形の frozenset 検証を追加。既存データが 4 都県のみなら `Literal` 化が最も安全。副作用: `/create` の選択肢と必ず同期させること（片方だけ広げると 422 になる）。

---

## 台帳の cite 精度

誤り 3 件（`page.tsx` の LP エリア記載＝事実誤認、`create:790`→`:802`、`create:906-913`→`:865-870`）。1 行ずれ 1 件（`create:113`→`:112`）。それ以外の約 40 箇所の file:line はすべて実ファイルと一致した。

## 末尾サマリ

- ❌ High 3件（**H2 ギャラリー選択不可**・**H3 必須入力の破棄**・**ADD-H1 住所47県 vs 出品4都県**）— H1 は Medium へ降格
- ⚠️ Medium 11件（M1〜M9 は全件成立、H1 降格分と ADD-M10 を追加）
- ✅ REJECTED 0件。M8 は TODO 03 重複ではなく、TODO 側「window.confirm のまま」が陳腐化エントリ
