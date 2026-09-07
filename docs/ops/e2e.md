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
| `e2e/02-seller-select-bid.spec.ts` | 依頼者ログイン → マイページ → 案件詳細で入札を選定（ConfirmModal）→ 成約表示 |
| `e2e/03-chat-unread.spec.ts` | 依頼者チャット送信 → 業者（別 context）で未読 → 返信 → 候補日提案 |
| `e2e/04-schedule-reduction-complete.spec.ts` | 日程確定 → 減額申請（業者 API）→ 依頼者が承認 → 完了確定 → 評価投稿 |
| `e2e/05-admin-operations.spec.ts` | 運営: /admin のバッジ → 事前申込を承認して招待コード表示 → お問い合わせを対応済み |
| `e2e/06-abnormal-cases.spec.ts` | 運営の強制終了でチャットが閉じる（UI 文言 + API 409）／誤パスワード 6 回で 429 文言 |
| `e2e/07-session-crossover.spec.ts` | 業者セッションで `/login` を開くとサインアウト導線が出る（ループ再発防止） |

`e2e/helpers/` は共通部品。

- `env.ts` … 接続先とテスト口座。**`backend/seed_local_e2e.py` の `ACCOUNTS` と 1:1 で同期させること。**
- `api.ts` … 前提データ作成・ID 引き当て用の API クライアント（`web/src/lib/katadzuke-api.ts` は
  `"use client"` 依存を持つため import せず、必要な型だけ再定義している）。
- `ui.ts` … ログインフォーム操作、共通 ConfirmModal の確定、横スクロール判定、console error 収集。
- `fixtures.ts` … シード済み DB から「入札待ちの案件」「進行中の取引」を引き当てる。
  **既存を再利用できる場合は必ず再利用し、案件の新規作成は最後の手段**（上記レート上限のため）。

## 設計方針（変更するときの約束）

- **`data-testid` を足さない。** セレクタは `getByRole` と表示文言で書く。文言変更で壊れやすい
  ところは正規表現で緩める。UI 側にテスト専用属性を増やさないための制約。
- **直列実行（`workers: 1` / `fullyParallel: false`）。** シナリオが同じ DB の取引を消費するため、
  並列化すると別テストが掴んだ取引を横取りする。
- **`retries: 0`。** 落ちたら実挙動の問題として扱う。リトライで隠さない。
- **前提は API・確認は UI。** シードの ID は決め打ちせず、ログイン後に API から引く。
- 2 プロジェクト（`desktop` 1280px / `mobile` 375px）で同じシナリオを流す。chromium のみ。

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

**このチェックで落ちたら実バグとして扱う**（実際 r12 で `create_case` の 500 を検出した。
`.agent-state/audit/r12-pg-concurrency.md` 参照）。反復回数は `KDZ_ROUNDS`、接続先は
`KDZ_API_BASE` / `KDZ_PG_DSN` で変えられる。アカウントは実行ごとに新規作成するため再実行可能。

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
