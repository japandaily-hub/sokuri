# r5 修正の独立検証（2026-09-04）

対象: `git diff`（未コミット、13ファイル / +598 -142）。自己申告 `r5-fix-backend.md`・`r5-fix-frontend.md` は額面で受けず実測した。

## 総合判定

**条件付き不合格（High 1）。** backend 側 5 項目はすべて実装・テストまで到達しているが、
`GET /admin/operators` の応答契約が backend（`counts`）と web（`pending_count`）で不一致であり、
**H-1 の中核成果物である「審査待ち件数バッジ」が本番で一切表示されない**。tsc は `request<T>()` が
無検証キャストのため、この不一致を検出できない（型が通るのに実行時 undefined）。

## 実測結果（すべて本検証で実行）

| コマンド | 結果 |
| --- | --- |
| `backend> .venv\Scripts\python.exe -m pytest -q` | **753 passed, 0 failed**, 731 warnings, 221.99s（自己申告 753 と一致） |
| `web> npx tsc --noEmit` | **エラー 0** |
| `web> npx eslint src` | **エラー 0 / warning 3**（`notifications/page.tsx:195`・`operator/transactions/[id]/page.tsx:92`・`signup/page.tsx:59`、いずれも本差分の対象外・未変更） |

自己申告の pytest 件数・tsc/eslint 結果は事実。前方参照バグ（`_ADMIN_CASE_TXN_DEFAULT_LIMIT`）の
是正も事実で、`backend/app/api/v1/endpoints/admin.py:76-81` にファイル冒頭定義があり、
旧定義位置 `:450` はコメントに置換済み。collection 全滅は再現しない（753 件が収集・成功）。

---

## 項目別判定

### (1) `GET /admin/operators` の契約一致 — **一部**

**backend 側は完全に契約どおり。**
- `status` Literal: `admin.py:225-230`（`all|pending|limited|active|rejected|suspended`、`alias="status"`）
- `q`（会社名/メール/許可番号・ilike エスケープ付き）: `admin.py:257-266`、`_escape_ilike_value` は `admin.py:88`
- `limit`（既定 50 / 上限 200）・`offset`: `admin.py:232-233`
- `{items,total,counts}`: `admin.py:302-306`、スキーマ `backend/app/schemas_katadzuke.py:107-131`
- pending 優先ソート: `admin.py:292-299`（`case((vendor_status=="pending",0),else_=1)` → `created_at desc` → `id desc`）
- テスト: `backend/tests/test_admin_operator_controls.py:292-372`（counts 辞書の全キー・絞込非依存・422・limit 上限）

**web 側が 1 文字一致していない。**
- `web/src/lib/katadzuke-api.ts:1624-1627` が `pending_count: number` を宣言。backend は
  `counts: OperatorListCounts` を返し、`response_model` が余剰キーを落とすため `pending_count` は**存在しない**。
- `web/src/app/admin/page.tsx:351` が `count: operatorsData?.pending_count` を渡す → 常に `undefined`。
- `web/src/app/admin/_components/StatusFilterBar.tsx:30` が `opt.count !== undefined` で描画を分岐するため、
  pending ボタンは **数字が一切付かない**（「0」ですらなく無表示）。
- 結果として、H-1 が是正しようとした「2ページ目以降の pending を見落とす」問題は、
  「件数が全く見えない」形で**残存**する。絞込・検索・ページング自体はサーバ委譲されており正しい。

**サーバ委譲・ページング・再取得は塞がった。**
- クライアント絞込の全撤去を diff で確認（削除済み: `matchesOperatorSearch` / `searchedOperators` /
  `operatorStatusCounts` / `suspendedCount` / `filteredOperators`、および
  「件数・検索は表示中のページ（50件）のみが対象です」注記）。
- ページングは `total` ベース: `web/src/app/admin/page.tsx:634`（`total={operatorsData?.total ?? null}`）。
- 承認・停止・承認取消の後の再取得は健在: `admin/page.tsx:292`（`closeSuspendModal(); await reload();`）、
  `:311`（verify 側）。`reload` の deps に `statusFilter`・`operatorSearchQuery`・`operatorOffset` が
  入っており（`:191`）、絞込変更時の再取得も成立。

### (2) approve の重複 409・招待コード未発行 — **塞がった**

`admin.py:1037-1047`。重複検査は `_issue_unique_invite_code(session)`（`:1049`）**より前**に置かれており、
409 時にコードは発行されない。detail は「このメールアドレスの業者アカウントは既に存在します。招待コードは発行していません。」。
テスト: `backend/tests/test_katadzuke_api.py` の `test_admin_approve_operator_application_existing_operator_409`
（409 と detail 文言をアサート）。

### (3) 事前申込の `q` に許可番号・`status` Literal→422 — **塞がった**

`admin.py:937`（`OperatorApplication.license_number.ilike(...)` を `or_` に追加）、
`admin.py:911-913`（`Literal["received","approved","rejected"] | None`）。
テスト: `test_admin_list_operator_applications_invalid_status_422`・
`test_admin_list_operator_applications_q_matches_license_number`。
placeholder も `web/src/app/admin/operator-applications/page.tsx:255` で
「会社名／メール／許可番号（部分一致）」に統一済み。

### (4) `OperatorApplication.operator_id` の書き込み経路 — **塞がった（実在する）**

経路は 4 点そろっている。
1. 承認時にコードを控える: `admin.py:1056-1058`（`application.invite_code = code`）
2. 列の追加: `backend/app/db/models/operator_application.py:62-66`（`String(64)`, index）
3. マイグレーション: `backend/alembic/versions/0026_operator_app_invite.py`（revision id 25 文字、
   `down_revision="0025_user_suspend"` で head 直列・分岐なしを確認）
4. 消込時の書き戻し: `backend/app/api/v1/endpoints/auth.py:366-375`
   （`select(OperatorApplication).where(OperatorApplication.invite_code == invite.code)` → `application.operator_id = operator.id`、`commit` 前）

テスト `test_operator_application_operator_id_tracked_after_signup` が「承認直後は null →
招待コードで本登録 → 一覧・詳細の `operator_id` が新 Operator.id と一致」まで通している。

### (5) ConfirmModal の `error` 一本化・二重表示なし — **塞がった（4画面すべて）**

`web/src/app/admin/_components/ConfirmModal.tsx:36,63-67` が `error?: string | null` を受け、
モーダル内の `Notice tone="error"` に描画する。4 画面すべてで「失敗時に閉じない」に統一され、
同時に `setError`（ページ上部 Notice）を呼ぶ経路は無く、二重表示は発生しない。

| 画面 | 失敗時の表示先 | 根拠 |
| --- | --- | --- |
| `admin/page.tsx` | `suspendModalError` / `verifyModalError` | `:297`, `:316`, prop 配線 `:769`, `:790` |
| `admin/users/page.tsx` | `suspendModalError` / `roleModalError` | `:96`, `:119`, prop 配線 `:301`, `:325` |
| `admin/operator-applications/page.tsx` | `approveModalError` / `rejectModalError` | `:168`, `:193`, prop 配線 `:495`, `:514` |
| `admin/identity-documents/page.tsx` | `approveModalError` / `rejectFormError` | `:160`, `:182`, prop 配線 `:420`、却下はフォーム直下 `:366-368` |

identity-documents の却下だけ ConfirmModal ではなくフォーム直下表示だが、却下 UI 自体が
詳細モーダル内のインラインフォームであり、モーダル背後に隠れないため設計として妥当。
モーダルを開く各ボタンで対応する error state を `null` にリセットしており、
前回のエラーが次回開いたときに残る事故も無い（例 `admin/page.tsx:263-280`）。

### (6) privacy のお問い合わせ行に種別 — **塞がった**

`web/src/app/privacy/page.tsx:22` が「お名前、メールアドレス、お問い合わせ種別、お問い合わせ内容」。
`backend/app/schemas_katadzuke.py:1202-1205`（`name` / `email` / `category` / `message`）と 1:1 で一致。

### (7) 前方参照バグ（collection 全滅） — **塞がった**

`admin.py:76-81` に冒頭定義、`admin.py:450` は「ファイル冒頭で定義」のコメントに置換。
本検証の pytest 753 passed が実証（NameError による import 失敗は再現しない）。

---

## 新規の回帰

### High-1 `GET /admin/operators` の応答契約が backend と web で不一致（pending バッジが無表示）

- 根拠: `backend/app/schemas_katadzuke.py:128-131`（`counts: OperatorListCounts`） vs
  `web/src/lib/katadzuke-api.ts:1627`（`pending_count: number`）、消費側 `web/src/app/admin/page.tsx:351`、
  描画側 `web/src/app/admin/_components/StatusFilterBar.tsx:30`
- 事象: `operatorsData.pending_count` は常に `undefined`。`count !== undefined` で分岐するため
  pending ボタンには数字が付かない。運営は「審査待ちが何件あるか」を /admin から知る手段を失う。
- 影響: H-1（承認漏れ＝売上機会損失）の是正が完了していない。誤った 0 表示ではなく無表示になった分だけ
  マシだが、当初の是正目的は達成されていない。
- 修正案: `AdminOperatorListResponse` を `counts: { all; pending; limited; active; rejected; suspended }` に
  変更し、`admin/page.tsx:345-353` の各 option の `count` を `operatorsData?.counts.<status>` へ差し替える
  （backend は絞込非依存の全件内訳を返すため、全ボタンに常時正しい件数を出せる）。
- 備考: 両担当の自己申告が互いに矛盾している。backend は「`pending_count`→`counts` に変更」と明記し、
  frontend は「`operatorsData.total`/`pending_count` 使用」と明記している。突き合わせが行われていない。

### Low-1 `/admin` 業者検索の placeholder が許可番号検索を告知していない

- 根拠: `web/src/app/admin/page.tsx:549`（`placeholder="会社名・メールで検索"`）vs
  `backend/app/api/v1/endpoints/admin.py:259-265`（`license_number.ilike` を含む 3 列検索）
- 事象: R5-M1 と同じ「placeholder と backend の検索列の不一致」が、今度は**逆方向**（実装の方が広い）で
  業者一覧に残っている。事前申込側は「会社名／メール／許可番号（部分一致）」に統一されたのに不揃い。
- 修正案: `admin/page.tsx:549` を `"会社名／メール／許可番号（部分一致）"` に揃える（1行）。

### Low-2 UI から `rejected` 業者に到達できない

- 根拠: `web/src/app/admin/page.tsx:345-353`（options は all/active/limited/pending/suspended の 5 個）vs
  `backend/app/api/v1/endpoints/admin.py:225-227`（Literal は `rejected` を受理）
- 事象: 却下済み業者を絞り込むボタンが無く、`counts.rejected` を返す backend 実装が死んでいる。
  「すべて」で総当たりするしかない。
- 修正案: options に `{ value: "rejected", label: "rejected", count: ... }` を追加。

### Low-3 `counts` を配線しても他ボタンの件数は「選択時のみ」表示に留まる

- 根拠: `web/src/app/admin/page.tsx:346-352`（`statusFilter === "all" ? operatorsData?.total : undefined` 等）
- 事象: backend は絞込非依存の全件内訳を毎回返しているのに、web は「選択中のボタンだけ total を出す」
  設計のままで、内訳を活かしていない。High-1 を直す際に同時に解消すべき。

---

## 未解決リスク

1. **migration 0026 が本番未適用**（未コミット・未 push）。`application.invite_code = code` と
   `select(...).where(OperatorApplication.invite_code == ...)` は列の存在を前提とするため、
   コード先行・マイグレーション後行のデプロイ順になると承認と業者本登録が
   `UndefinedColumn` で 500 になる。デプロイ後は `/readyz` で 0026 到達を実測すること
   （既知の alembic_version 全断障害と同じクラスの事故）。
2. **既存の承認済み申込は遡及紐付け不能**。`invite_code` は本修正以降の承認にしか書かれないため、
   既に承認済み・招待コード発行済みの申込は永久に `operator_id = null` のまま残り、
   「承認したが本登録していない業者」を運営が判別できない状態が部分的に続く。
   データ移行（`invites.email` と `operator_applications.contact_email` の突合）は未実施。
3. **`counts` が `q` を無視する仕様が UI 上どこにも説明されていない**。検索中でもバッジは全件内訳を
   出す設計（`admin.py:268-291` のコメントに記載）だが、High-1 を直して数字が出るようになると
   「検索結果 3 件なのに pending 12」という表示になり、運営が数字を誤読しうる。ラベル注記が要る。
4. **メール重複検査が大文字小文字を区別する**。`admin.py:1041`（`Operator.contact_email == application.contact_email`）は
   完全一致。`Foo@example.com` と `foo@example.com` は別物として通過し、M-3 の「使用不能な招待コード」が
   このケースでは再現する。既存の signup 側 409 検査（`auth.py`）も同じ比較なので新規欠陥ではないが、
   M-3 の是正は完全ではない。
5. **実ブラウザでの動作確認と `next build`（本番ビルド）が未実施**（frontend 自己申告どおり）。
   High-1 は tsc をすり抜けた実行時不整合であり、まさに実機確認でしか捕まらない種類の欠陥だった。

---

## 末尾サマリ

- ✅ backend 5 項目（counts 契約・409 重複・許可番号検索・Literal 422・operator_id 紐付け）は
  すべて実装＋テスト済み。pytest 753 passed / tsc 0 / eslint 0 error を本検証で再現。
  ConfirmModal の error 一本化（4画面）・privacy の種別追加・docstring 是正・前方参照バグ修正も事実。
- ⚠️ 承認済みの設計判断として counts は絞込非依存。既存承認済み申込の遡及紐付けは行われていない。
  migration 0026 の適用順・メール大小文字・実機未検証が残リスク。
- ❌ **High-1: `counts` vs `pending_count` の契約不一致で pending バッジが無表示**。
  H-1 の中核目的（審査待ち件数を常に正しく見せる）は未達。コミット前に web 側の型と参照の修正が必須。
