# r8 High 是正の独立検証（自己申告の突合）

日付: 2026-09-05 / 対象: `r8-fix-backend3.md`・`r8-fix-frontend3.md` が主張する H-1〜H-4 是正
方針: 自己申告を根拠に採らず、正本（`C:\Users\ko13h\Claude\Projects\ソクウリ`）の実コードのみで判定した。
注: web は worktree（`.claude\worktrees\kdz-r8\web`）と正本で md5 が一致しないファイルが3件あるが、
判定対象の該当行は正本側にも同一行番号で存在することを確認済み（改行コード差と判断）。以下の file:line は全て正本。

## 総合判定

**合格（Critical 0 / High 0 / 新規回帰 0）**。H-1 のみ「一部」、H-2・H-3・H-4 は塞がった。
Medium 6 件は 1 件も着手されていない（自己申告どおりスコープ外）。

## 実行検証（実測）

| 項目 | コマンド | 結果 |
|---|---|---|
| pytest | `backend/.venv/Scripts/python.exe -m pytest -q` | **814 passed, 843 warnings in 185.60s / exit 0**（自己申告 814 と一致） |
| tsc / eslint / next build | 未実行（本ミッションは読み取り検証） | — |

## 項目別判定

### (1) H-1 退会×落札の競合 — **一部**

塞がった部分:
- 順序が「pending 入札の一括 rejected 化 → `flush()` → 進行中取引数の再判定 → 非0なら `rollback()`+409」に入れ替わっている: `backend/app/api/v1/endpoints/operator_profile.py:434-452`。
- 多層防御ガード: `backend/app/api/v1/endpoints/bids.py:278-283`（`target.operator.deleted_at is not None` → 409）。`is_suspended`(:271) / `vendor_status`(:266) と同じ post-lock 位置で、`lock_case_row`(:230) → `_get_case`（`populate_existing=True`, :54）の後にあるため最新状態を読む。
- `list_bids` の旗: `bids.py:72`（`out.operator_suspended = bool(...is_suspended) or bid.operator.deleted_at is not None`）。`_bid_out` の呼び出しは :100/:101/:104 の3経路のみで、いずれも `selectinload(Bid.operator)`(:39) 済み → N+1・遅延ロード例外なし。
- 回帰テスト: `backend/tests/test_r8_abnormal_guards.py:611`（select_bid が退会済み業者を 409）。

塞がっていない部分（判定「一部」の理由）:
- **退会側は Case 行ロックを一切取っていない**（`operator_profile.py:388-480` に `lock_case_row` の呼び出しは無い）。直列化はレビュー修正案(b)の後段「Case 行をまとめて掴む」ではなく、一括 UPDATE が生む **Bid 行ロックへの依存**で成立している。既存の pending 入札に対しては正しく機能する（select_bid の条件付き UPDATE `bids.py:291` は同一行を掴もうとしてブロックし、解放後は status が rejected のため rowcount 0 → 409 `bids.py:294-296`）。
- **残る窓**: 退会側の一括 UPDATE（:434-438）の後、commit（:467）の前に同一業者が **新規 pending 入札を INSERT** した場合、その行は退会側の行ロックの対象外である。この窓で走る `select_bid` は未コミットの `deleted_at` を読めない（READ COMMITTED）ため :278 のガードを素通りし、退会側の再判定（:441-449）は既に通過済みのため、**退会済み業者の進行中 Transaction が成立しうる**。窓は「一括 UPDATE〜commit」の数ミリ秒に限られ、かつ入札 INSERT の同時着弾を要するため実害確率は低いが、H-1 の再現条件そのものは論理上まだ閉じていない。

### (2) H-4 退会の再認証・レート制限 — **塞がった（ただし 429 はテスト未実証）**

- password 必須化: `backend/app/schemas_katadzuke.py:254-263`（`OperatorAccountDeleteRequest.password: str`）／ハンドラ `operator_profile.py:389`。
- 403: `operator_profile.py:374-377`（`_OPERATOR_DELETE_WRONG_PASSWORD` = 403）＋ :425-428。
- レート制限の実効化: `operator_profile.py:419-421`（`ctx = request.state.rate_limit` → `ctx.check_account(str(operator.id))`）・:427 `record_failure`・:429 `reset_account`。`rate_limit_deps.py:375-378` の `account_delete` は `ip_rule=None / count_all=False` なので、この3呼び出しが揃って初めてガードが効く条件を満たしている。`users.py:595-607` と同型。
- 回帰テスト: `test_r8_abnormal_guards.py:530`（誤パスワード 403・`deleted_at is None` を確認）・:498（409）・:559（匿名化・入札 rejected・旧トークン 401・/vendors 除外）。
- **未実証**: `backend/tests/` 全体で `account_delete` の文字列ヒットは 0 件、`test_rate_limit_api.py` にも当該 scope のケースが無い。**429 に到達することを実証したテストは存在しない**（コード上は成立する）。

契約の非対称（新規に持ち込まれたもの）:
- 誤パスワードが業者退会は **403**（`operator_profile.py:375`）、依頼者退会は **400**（`users.py:492-494`）、業者の再認証／LINE 解除も **400**（`operator_profile.py:333`・:359）。同一意味に3系統の status が混在する。web は 403 で分岐済み（`web/src/app/operator/profile/page.tsx:175`）のため実害は無いが、API 契約としては不整合。
- LINE 専用業者: 依頼者側 `AccountDeleteRequest` は `password` 任意＋`confirm` 必須（`users.py:599-607`）だが、業者側は `password: str` 必須・`confirm` 無し（`schemas_katadzuke.py:263`）。`password_hash is None` の分岐（`operator_profile.py:425`）に入ると照合も `reset_account` もスキップされる。`operator_signup` が必ず password_hash を設定するため現状到達不能で、実害は無い。

### (3) admin の退会業者の扱い — **塞がった**

- 一覧・counts の除外: `backend/app/api/v1/endpoints/admin.py:280`（`deleted_condition`）→ `:281 conditions` と counts 集計の両方に適用。`include_deleted` クエリは `:261-263`。
- verify 409: `admin.py:364-367`。suspend/停止解除 409: `admin.py:419-423`。
- promote は業者向けエンドポイントが存在せず（`promote_user_to_admin` は User 対象）、`admin.py:1028` で `User.deleted_at` を既にチェック済み。
- 残件: **運営 web UI に退会バッジ・`include_deleted` トグルが無い**（`web/src/app/admin/` に `include_deleted`／業者退会の文言のヒット 0）。運営は「一覧から消えた業者」の理由を画面上で判別できない。

### (4) /vendors・口コミ集計の退会除外 — **塞がった**

- 一覧: `operator_profile.py:252-254`（`Operator.deleted_at.is_(None)`）。公開プロフィール: `:177`（404）。
- 口コミ集計 `services/review_stats.py:23-59` は operator 単位の書き戻しで、公開読み出し経路（上記2つ）が退会業者を弾くため露出しない。ただしレビュー行と `operators.rating` は退会後も残る（下記リスク参照）。

### (5) web の告知・退会モーダル・理由表示 — **塞がった**

- H-2 開示告知: `web/src/app/operator/transactions/[id]/page.tsx:437`（「入力した理由はそのまま依頼者に表示されます。」）。
- H-3 双方開示告知: `web/src/app/admin/transactions/page.tsx:253`（message）・`:257`（`reasonLabel="終了理由（必須・当事者双方に表示されます）"`）。
- 退会モーダルのパスワード入力: `web/src/components/kdz/ConfirmModal.tsx:28,47-48,53,138-155,163-164`（`withPassword` / `passwordMissing` で確定ボタンを無効化 / `autoComplete="current-password"`）→ 配線 `operator/profile/page.tsx:786-795`。送信 `web/src/lib/katadzuke-api.ts:428-434`。
- 403/409/429 の区別表示: `operator/profile/page.tsx:175-181`。
- 理由の空値: `cases/[id]/page.tsx:821-825`（`理由の記載なし`）・`operator/transactions/[id]/page.tsx:203`。長文折り返し: `cases/[id]/page.tsx:822`（`break-words`）。
- **未実施（レビュー H-2 修正案の後半）**: キャンセル理由 textarea（`operator/transactions/[id]/page.tsx:438-445`）に `maxLength` が無い。backend は `TransactionCancelRequest.reason max_length=2000`（`schemas_katadzuke.py:771`）で、超過は 422 になるまで気づけない。「個人情報は書かないでください」の注記も未追加。強制終了側も admin 上限 500（`schemas_katadzuke.py:958`）が UI に出ていない。Low 相当。
- **L-1 未修正・かつ悪化**: `ConfirmModal.tsx:77-78`（Esc）・`:105`（背景 onClick）が `busy` を見ない。退会モーダルは**入力済みパスワードごと**閉じられ、in-flight の結果表示が行き場を失う。

### (6) Medium 6 件の状況 — **全件未対応**

| # | 状況 | 根拠 |
|---|---|---|
| M-1 監査主体（admin_id）未記録 | 未対応 | `cancelled_by_admin_id` は `backend/app` / `backend/alembic` に 0 件 |
| M-2 レガシー purpose が「その他」化 | 未対応 | `web/src/lib/case-labels.ts` に `LEGACY_CASE_PURPOSES` なし |
| M-3 空 MIME を 422 にする回帰 | 未対応 | `web/src/lib/katadzuke-api.ts:1447-1449`（`file.type === ""` のフォールバック無し） |
| M-4 `CASE_PURPOSE_VALUES` 二重定義 | 未対応 | `backend/app/schemas_katadzuke.py:569` に定義のみ残存 |
| M-5 `operator_deleted` の表現 | **一部** | 入札一覧は `bids.py:72` で `operator_suspended` に流用。`TransactionDetailOut` には未追加（`operator_deleted` の grep ヒットは `bids.py:71` のコメントのみ） |
| M-6 減額上限の行ロック | 未対応 | `backend/app/api/v1/endpoints/reductions.py` に `lock_transaction_rows` の呼び出し 0 件 |

**対応不要と判断できるもの: 無い。** M-3 は実ユーザーが写真を出せなくなる回帰、M-2 は既存データの表示崩れ、M-6 は 3 件目の減額申請が通る不整合で、いずれも「不要」ではなく「未着手」。M-4 のみドリフト予防の内部整理で、リリース阻害要因ではない。

## 新規回帰（High 以上）

**0 件**。pytest 814 全緑（既存 811 + 新規3）。読み取り検証の範囲では以下も問題なし:
- `operator_profile.py:23`（`update`）・`:34`（`BID_STATUS_PENDING/REJECTED, Bid`）・`:37`（`Transaction`）の import は揃っており、退会経路の NameError は無い。
- `session.rollback()`(:451) 後に 409 を送出する経路で、入札の rejected 化も併せて巻き戻る（意図どおり）。
- `_bid_out` の `bid.operator` 参照はすべて eager load 済み経路（:39）からの呼び出しのみ。

## 未解決リスク

1. **H-1 の残窓（上記(1)）**: 一括 UPDATE〜commit の間に INSERT された新規入札は行ロックに掴まれず、`select_bid` は未コミットの `deleted_at` を読めない。完全に閉じるにはレビュー修正案(b)後段（対象業者の pending 入札が付く Case 行を `lock_case_row` でまとめて取得）か、退会側での `deleted_at` 先行 UPDATE→flush→入札 reject→再判定への再々順序化が必要。
2. **競合系が 1 件もテストで実証されていない**: `backend/tests/conftest.py` の SQLite in-memory では `SELECT ... FOR UPDATE` が no-op。H-1 の直列化・`lock_case_row`・部分ユニーク索引はすべて未実証のまま「814 passed」に含まれている。緑は根拠にならない。
3. **`account_delete` の 429 が未実証**: 実装は正しいが、`ctx.check_account` の呼び忘れ再発（まさに H-4 の原因）を捕まえるテストが無い。誤パスワードを上限回連打して 429 を確認する 1 ケースを追加すべき。
4. **0030 が本番未適用**: `deps.py` と `auth.py` が `operators.deleted_at` を無条件参照するため、migrate→deploy の順を誤ると業者側の全リクエストが 500。今回の変更でこの参照経路（`bids.py:72`・`:278`、`admin.py:280`・:364・:419、`operator_profile.py:177`・:253）がさらに増え、失敗時の爆風半径が拡大した。
5. **誤パスワード時の status が 400/403 で混在**（`operator_profile.py:375` vs `users.py:493` vs `operator_profile.py:333`）。将来 web 側を共通化する際に取りこぼしを生む。
6. **退会業者のレビュー行・`operators.rating` が残置**（`review_stats.py` は再計算されない）。現状の公開経路は除外済みだが、「地域平均」等の集計を足した時点で混入する。
7. **運営 UI から業者の退会が見えない**（`web/src/app/admin/` に `include_deleted` の配線なし）。API は 409 で守られたが、運営は原因を画面で判別できずサポート問い合わせに答えられない。
8. **web のビルド系（tsc / eslint / next build）は本検証では未実行**。フロント差分の型・ビルド健全性は自己申告のみが根拠。

## 結論

- High 4 のうち H-2・H-3・H-4 は実コードで塞がったことを確認。H-1 は主要な再現経路（既存 pending 入札）を塞いだが、新規入札が絡む残窓が論理上残るため「一部」。
- 新規 High 回帰は無し。ただし競合系・429 はテストで実証されておらず、緑は根拠にならない。
- Medium 6 件は未着手。M-3（写真アップロードの回帰）・M-6（減額 3 件目）は実利用に触れるため、次周で優先すべき。

サマリ: ⚠️ H-2/H-3/H-4 塞がった・H-1 は一部（残窓あり）／Critical 0・High 0・新規回帰 0／pytest 814 passed／Medium 6 件未着手・429 未実証
