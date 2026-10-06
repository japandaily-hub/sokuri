# E2E（Playwright）実行手順

ローカルスタック（使い捨て SQLite + `next dev`）に対して、依頼者・業者・運営の主要導線を
自動で回すスモークテスト。**本番には決して向けないこと**（`E2E_BASE_URL` / `E2E_API_URL` の
既定値はどちらも localhost）。

## 前提（初回のみ）

```powershell
cd C:\Users\ko13h\Claude\Projects\ソクウリ\web
npm install
npx playwright install chromium
```

`web/.env.local` も必要（`.gitignore` 済みで新しい worktree には無い）。`web/.env.example` を
複製して `AUTH_SECRET` を任意の乱数文字列にし、`NEXT_PUBLIC_API_URL` は
`http://localhost:8000/api/v1` にする（worktree では本体の `web/.env.local` を複製してもよい。その場合も
`NEXT_PUBLIC_API_URL` と、あれば `API_URL` の行がローカルを向いていることを確かめる。`API_URL` は
サーバー側で `NEXT_PUBLIC_API_URL` より優先される）。Next は環境変数を「プロセスの環境変数（シェルで
設定した値（PowerShell の `$env:API_URL=…` 等）と、OS のユーザー・システム環境変数）→
`.env.development.local` → `.env.local` → `.env.development` → `.env`」の順に採るので、それらに
`API_URL` / `NEXT_PUBLIC_API_URL` が残っていないことも確かめる。
シード（`backend/seed_local_e2e.py`）と E2E は、リポジトリ直下の `test-room.jpg`（任意の室内写真）を読む。
`.gitignore` 済みで新しい worktree には無いので、各自で置く（コミットしない。実写なら EXIF の位置情報を除く）。
**接続先が未設定のまま `next dev` を起動しても本番 API へは落ちない**（未設定時に本番 API を使うのは
本番ビルドだけ）。ログインは画面上「サーバーに接続できませんでした」になり、`next dev` のターミナルに
`[backend-api-base] バックエンド API の接続先（API_URL / NEXT_PUBLIC_API_URL）が未設定です…` が出る。
`AUTH_SECRET` も無い場合は、それより手前で NextAuth が `MissingSecret` で止まる。

## 実行（3 コマンド）

ターミナルを 3 枚使う。1・2 は起動しっぱなしにする。

```powershell
# 1) バックエンド（http://127.0.0.1:8000・使い捨て SQLite backend/e2e_local.db）
cd C:\Users\ko13h\Claude\Projects\ソクウリ\backend; .venv\Scripts\python.exe run_local_e2e.py

# 2) フロント（http://localhost:3100。ALLOWED_ORIGINS の都合で 3000/3100/3101 のみ可）
cd C:\Users\ko13h\Claude\Projects\ソクウリ\web; npm run dev -- -p 3100

# 3) シード投入 → テスト実行
cd C:\Users\ko13h\Claude\Projects\ソクウリ\backend; .venv\Scripts\python.exe seed_local_e2e.py; cd ..\web; npm run e2e
```

`npm run e2e` は `playwright test`。個別実行は次の通り。

```powershell
npx playwright test e2e/04-schedule-reduction-complete.spec.ts   # ファイル指定
npx playwright test --project=mobile                             # 375px 幅だけ
npx playwright test --headed --project=desktop                   # 画面を見ながら
npx playwright show-trace test-results\<失敗したテスト>\trace.zip # 失敗時のトレース
```

環境変数で向き先を変えられる（既定は下記の値）。

| 変数 | 既定 | 意味 |
| --- | --- | --- |
| `E2E_BASE_URL` | `http://localhost:3100` | フロントの起点 |
| `E2E_API_URL` | `http://localhost:8000/api/v1` | バックエンド API の起点 |
| `E2E_ALLOW_REMOTE` | 未設定 | `1` のときだけ localhost / 127.0.0.1 / ::1 以外への実行を許す |

`E2E_BASE_URL` / `E2E_API_URL` / `playwright.config.ts` の `baseURL` のホストがローカル以外だと、
4段の検査で実行前に失敗する: ①`playwright.config.ts` の読み込み時（主防御。ワーカーを1つも
起動しない） ②`helpers/test.ts` の worker fixture（`localTargetGuard`） ③ブラウザのコンテキストを
作るときの実効 `baseURL`（`context` fixture・`newE2EContext`） ④`Api.create()`（API クライアントを
作るたび）。③は page / context を使うテストでしか走らないため、spec では baseURL を書くこと
（`test.use` / `test.extend` / `newE2EContext` の options など、オブジェクトの `baseURL` キー全般）と
`@playwright/test` からの `request`・default の import を `web/eslint.config.mjs` で禁止している
（baseURL は `playwright.config.ts` だけで決める）。検査の本体は
`helpers/local-target.ts`。`E2E_ALLOW_REMOTE=1` を付けると検査を外すが、外した接続先（origin）を
警告として表示する。ただし `next dev` 自身が使う接続先（サーバー側の NextAuth の `authorize()` 等と、
画面が使う `NEXT_PUBLIC_API_URL` の両方）は4段では検査しないため、`web/.env.local` の接続先そのものを
ローカルにしておくこと。

## クリーンな状態から流す

テストは成約・取引を消費する（完了確定・運営の強制終了）。同じ DB に対して何度も流すと
使える取引が尽きて案件を新規作成しに行き、案件作成のレート上限（既定 10 件/時・IP 軸と
アカウント軸の両方）に当たる。**2 回目以降は DB を作り直すのが確実。**

```powershell
# バックエンドを止めてから
Remove-Item C:\Users\ko13h\Claude\Projects\ソクウリ\backend\e2e_local.db
# 起動し直して seed_local_e2e.py を再実行
```

繰り返し流したい場合は、バックエンド起動時に案件作成の上限だけ緩める（ログイン側の
上限は 429 のテストで使うので触らないこと）。

```powershell
$env:RL_CASE_CREATE_IP_MAX="200"; $env:RL_CASE_CREATE_ACCOUNT_MAX="200"
.venv\Scripts\python.exe run_local_e2e.py
```

## テスト構成

| ファイル | 内容 |
| --- | --- |
| `e2e/01-public-pages.spec.ts` | 公開ページ 8 本が 200・横スクロールなし・console error なし |
| `e2e/02-seller-select-bid.spec.ts` | 依頼者ログイン → マイページ → 案件詳細で入札を選定（ConfirmModal）→ 成約表示（チャットは画面内に開いた状態で出る） |
| `e2e/03-chat-unread.spec.ts` | 依頼者チャット送信 → 業者（別 context）で未読 → 返信 → 候補日提案（日付＋時刻の構造化入力。業者側・依頼者側とも件数 +1 で確認）→ 依頼者が候補ごとのボタン＋確認モーダルで確定（accept API） |
| `e2e/04-schedule-reduction-complete.spec.ts` | 日程確定（当月の今日・運営を名乗る「業者へのひとこと」付き）→ 依頼者・業者の両チャットで、「訪問日程が確定しました」の帯（サーバーが作った日付・時間帯だけ）とひとこと（帯の外の本人の吹き出し）が分かれていることを確認。当日の終わった枠は選べないため、時間指定なしを選ぶ → 減額申請（業者 API）→ 依頼者が承認 → 業者が完了確定を依頼（依頼後はボタンが無効＋注記）→ 完了確定 → 評価投稿 |
| `e2e/05-admin-operations.spec.ts` | 運営: /admin のバッジ → 事前申込を承認して招待コード表示 → お問い合わせを対応済み |
| `e2e/06-abnormal-cases.spec.ts` | 運営の強制終了でチャットが閉じる（UI 文言 + API 409）／誤パスワード 6 回で 429 文言 |
| `e2e/07-session-crossover.spec.ts` | 業者セッションで `/login` を開くとサインアウト導線が出る（ループ再発防止） |

`e2e/helpers/` は共通部品。

- `test.ts` … 全 spec が使う `test` / `expect`（`@playwright/test` の拡張）。next dev の開発用オーバーレイ
  （`<nextjs-portal>`）を全ページで非表示にする。**spec は `@playwright/test` ではなくここから import し、
  別コンテキストは `browser.newContext()` ではなく `newE2EContext(browser)` で作ること**（`web/eslint.config.mjs`
  で強制。`browser.newContext` / `browser.newPage` の直接呼び出しは helpers も含めて禁止。違反すると
  `npm run lint` と CI の lint（`npx eslint src e2e`）が落ちる）。接続先の検査のうち worker fixture
  （`localTargetGuard`）と、コンテキスト作成時の実効 `baseURL` を見る `context` fixture / `newE2EContext`
  の2段を持つ。
- `local-target.ts` … 接続先がローカルスタックかどうかを検査する純関数（検査の本体）。上記4段の
  検査はすべてここから import する。
- `local-target.test.mts` … 上記の回帰テスト（`node --test`。`playwright.config.ts` の
  `testMatch` を `**/*.spec.ts` に絞っているため Playwright の収集対象にもならない）。
- `env.ts` … 接続先とテスト口座。**`backend/seed_local_e2e.py` の `ACCOUNTS` と 1:1 で同期させること。**
- `api.ts` … 前提データ作成・ID 引き当て用の API クライアント（`web/src/lib/katadzuke-api.ts` は
  `"use client"` 依存を持つため import せず、必要な型だけ再定義している）。
- `ui.ts` … ログインフォーム操作、共通 ConfirmModal の確定、横スクロール判定、console error 収集。
  `loginAsUser` は callbackUrl なしで `/login` を開き、**ログイン直後の着地先（運営は `/admin`・それ以外は
  `/cases`）を必須で確かめてから**目的のパスへ移る（`/login` を抜けたことだけを見ていた頃は、運営が
  `/cases` に着地する不具合を見逃していた。2026-09-26）。
- `fixtures.ts` … シード済み DB から「入札待ちの案件」「進行中の取引」を引き当てる。
  **既存を再利用できる場合は必ず再利用し、案件の新規作成は最後の手段**（上記レート上限のため）。

## 設計方針（変更するときの約束）

- **ローカル以外には向けない。** 接続先は許可リスト（localhost / 127.0.0.1 / ::1）で検査し、
  本番のホスト名はテストコードに書かない。検査は4段（`playwright.config.ts` の読み込み時が
  主防御 → `helpers/test.ts` の worker fixture → コンテキスト作成時の `baseURL` → `Api.create()`）で
  重ねている（検査の本体は `helpers/local-target.ts`）。spec では baseURL を書かず、`@playwright/test` の
  `request`・default を import しない（eslint で禁止）。
- **`data-testid` を足さない。** セレクタは `getByRole` と表示文言で書く。文言変更で壊れやすい
  ところは正規表現で緩める。UI 側にテスト専用属性を増やさないための制約。
- **直列実行（`workers: 1` / `fullyParallel: false`）。** シナリオが同じ DB の取引を消費するため、
  並列化すると別テストが掴んだ取引を横取りする。
- **`retries: 0`。** 落ちたら実挙動の問題として扱う。リトライで隠さない。
- **前提は API・確認は UI。** シードの ID は決め打ちせず、ログイン後に API から引く。
- 2 プロジェクト（`desktop` 1280px / `mobile` 375px）で同じシナリオを流す。chromium のみ。
- **next dev の開発用オーバーレイはテストのブラウザ内だけで消す。** 左下の「N」インジケーターは本番に
  存在せず、375px 幅では画面下端に固定された入力欄左端のボタン（業者チャットの「日程を提案」）に重なって
  クリックを横取りする（チャット画面は 100vh 固定なのでスクロールでは避けられない）。next.config の
  `devIndicators` は next dev の起動設定で E2E だけに限定できず、DevTools の「Hide Dev Tools」は
  dev サーバー側に保存されて開発者のブラウザにも効くため、どちらも使わない（`helpers/test.ts`）。
- **CI は E2E を実行しないが、型と lint は守る。** web ジョブで `npx tsc -p e2e/tsconfig.json`（ルートの
  tsconfig は `e2e` を除外しているため別に回す）と `npx eslint src e2e` を通す。spec や helpers を変えたら
  push 前にローカルでも同じ2つを流す。

## PG 同時実行チェックの手順

Playwright の E2E（SQLite）とは別枠の検証。（E2E は 2026-09-07 時点で 36 本: 08 に「他社入札額の匿名開示」「入札額の引き上げ」を追加。`E2E_SCREENSHOT_DIR` を指定すると引き上げ後の業者画面を保存する。）**SQLite では `SELECT ... FOR UPDATE` が no-op**
のため、行ロック（`app/services/case_lock.py`）・部分一意索引（0028）・冪等の複合一意（0029）は
pytest では実証できない。実 PostgreSQL を立てて同時リクエストで確かめる。

```bash
# 1) PG を起動（使い捨て。ホスト 55432）
docker run -d --name kdz-pg -e POSTGRES_PASSWORD=kdz -e POSTGRES_DB=kdz -p 55432:5432 postgres:16

# 2) 実マイグレーションを当てる（backend/ を cwd にすること）
cd backend
DATABASE_URL=postgresql+asyncpg://postgres:kdz@127.0.0.1:55432/kdz \
  .venv/Scripts/python.exe scripts/pg_alembic_upgrade.py
#    ↑ 初回は 0008 で必ず失敗する（alembic_version が VARCHAR(32) で作られるため）。
#      alembic/env.py が次回起動時に VARCHAR(255) へ拡幅するので、もう一度同じコマンドを流す。
#    ↑ 素の `alembic -c alembic.ini` は日本語コメントで cp932 エラーになる。alembic は ini を
#      encoding="locale" で読むため PYTHONUTF8=1 では回避できない（PEP 686）。上のラッパを使う。

# 3) API を PG 接続で :8001 に起動（RATE_LIMIT_ENABLED=false・ADMIN_EMAILS 設定込み）
.venv/Scripts/python.exe scripts/run_pg_e2e.py

# 4) 別シェルで同時実行チェック（各シナリオ 3 ラウンド）
.venv/Scripts/python.exe scripts/pg_concurrency_check.py

# 5) 後片付け
docker rm -f kdz-pg
```

検証シナリオと不変条件（`scripts/pg_concurrency_check.py`）:

| # | 同時に撃つもの | 期待する応答 | DB 側の不変条件 |
| --- | --- | --- | --- |
| S1 | 同一案件への `select_bid` × 2 業者 | `[201, 409]` | `transactions=1` / `selected` 入札=1 |
| S2 | `DELETE /operator/me` と `select_bid` | 片方のみ成功 | 退会済み業者に進行中成約が 0 |
| S3 | 同一取引への減額申請 × 3 | `[201, 409, 409]` | `pending` 減額=1（部分一意索引） |
| S4 | 取引キャンセル × 2 | `[200, 409]` | `cancellations`=1 行 |
| S5 | 同一 `idempotency_key` の `POST /cases` × 2 | `[200, 201]` | 案件=1 件 |
| S6 | 運営の強制終了と依頼者の `complete` | 片方のみ成功 | status と `cancellations` が矛盾しない |
| S7 | 有効な管理者が2人だけのときの①同時自己退会 ②相互降格 ③退会と降格の同時実行 | 成功はちょうど1件（他は 401 / 403 / 409） | 残る管理者はちょうど1人（0 人にならない） |
| S8 | 運営の口コミ削除（`PATCH /admin/reviews/{id}/hide`）の①同時削除 ②同時に元に戻す ③削除と元に戻すの同時実行 ④同じ業者への口コミ投稿と削除の同時実行 | ①②③ `[200, 200]`・④ `[201, 200]` | 削除の記録（日時・理由・実施者）は片方の組で揃うか全て空で、業者の件数（よかった／伸びしろ／合計）が公開中の口コミの数え直しと一致 |
| S9 | NUL・制御文字・孤立サロゲートを含む入力（チャット本文・signup の name・招待コード付き業者登録の company_name・事前申込の message・案件の address_detail・入札 message・業者プロフィール intro_message・運営の成約強制終了 reason・運営の業者検索 q 等） | すべて 422（`disallowed_character`。RLO/タブ/CR は個別バリデータの `value_error` になる欄もある）。500 にならない | 何も保存されない（メッセージ件数・users・operators・operator_applications・冪等キーの cases・案件の bids・cancellations がいずれも増えない。招待コードの `used_at` は NULL のまま・業者プロフィールは基準値のまま・成約は `pending` のまま） |

S10（`s10_signup_duplicate_email_race`）: 同じメールアドレスでの `POST /auth/signup` × 2・`POST /auth/operator/signup` × 2 → それぞれ `[201, 409]`（409 の文言は事前確認と同じ）・依頼者と業者とも 1 件。事前確認（SELECT）をすり抜けた後発が一意制約（`uq_users_email`・`uq_operators_contact_email`）に当たっても 500 にならないこと（2026-09-27 までは 500 で、例外の DETAIL のメールアドレスがログ・アラートへ残った）。

**このチェックで落ちたら実バグとして扱う**（実際 r12 で `create_case` の 500 を検出した。
`.agent-state/audit/r12-pg-concurrency.md` 参照）。反復回数は `KDZ_ROUNDS`、接続先は
`KDZ_API_BASE` / `KDZ_PG_DSN` で変えられる。アカウントは実行ごとに新規作成するため再実行可能。
S8 はシナリオ中だけ2人目の運営を昇格させ、終了時に一般ユーザーへ戻す。①の「後から来た側が上書きしていない」の
判定は削除日時のマイクロ秒の差に頼るため、時計の分解能が粗い環境（Windows は約 1ms）では見逃しうる（CI の Linux が正）。
S7 はラウンド中だけ接続先 DB の他の admin を一般ユーザーへ外す（終了時に戻す）ため、接続先が
ローカル（127.0.0.1 / localhost / ::1）でなければ実行を拒否する。前回の実行が途中で止まって
運営アカウントが admin から外れたまま残っていても、起動時に自動で戻す。
S9 は同時実行ではなく実 PG でしか起きない入力由来の 500 の回帰（NUL は asyncpg の
`CharacterNotInRepertoireError`、孤立サロゲートは `DataError: surrogates not allowed`）で
あり、`KDZ_ROUNDS` に関係なく1周だけ流す（volley は使わない）。PC1 で `SELECT $1::text` に
NUL・孤立サロゲートを渡し、PG 自体がどちらも例外にすることを陽性対照として先に確認する
（成り立たなければ S9 の前提そのものが崩れているとして扱う）。PC2〜PC4 で ZWJ 絵文字・国旗・
タグ旗・改行等の許可文字・正しいサロゲートペア・通常のクエリが素通りすることも確認する。
S9 の実行順は S8 の後・S7 の前（S7 は運営の admin 権限を一時的に外すため必ず最後）。

> Docker Desktop が `initializing Inference manager` / `Secrets Engine` のソケットエラーで
> 起動しない場合は、`%LOCALAPPDATA%\Docker\run` と `%LOCALAPPDATA%\docker-secrets-engine` を
> リネームで退避してから起動し直す（孤児 unix ソケットが残ると毎回クラッシュする）。
> 復旧後にプロセスを force kill するとまた孤児が残るので注意。

## モバイル表示の視覚監査（スクリーンショット収集）

`web/e2e/99-mobile-audit.spec.ts` は通常の `npm run e2e` では自動スキップされる。`E2E_AUDIT_DIR` を指定して
実行すると、公開ページ・依頼者・業者・運営の主要画面を 375px 幅で撮影し（長いページは 1,400px ごとに分割）、
改行・折返し・余白のバランス確認に使える。スクロール連動の表示（`.rv`）と遅延読込画像は強制表示にして撮る。

```bash
cd web
E2E_AUDIT_DIR=C:/tmp/shots E2E_BASE_URL=http://localhost:3100 npx playwright test e2e/99-mobile-audit.spec.ts --project=mobile
```

2026-09-07 の監査で直した型: ステータスチップの縦折れ（`StatusBadge` を nowrap に）、運営の表が 375px に
押し込まれて 1 文字ずつ折れる（`min-w-[…]`＋横スクロール）、見出しが語の途中で折れる（`sp-br` を定義し、
スマホ幅だけ改行）、業者ダッシュボードのタブが横スクロールで欠ける（折り返しに変更）、トップページの
安心ポイント 2 列→1 列、プライバシーポリシーの表を横スクロールに。
