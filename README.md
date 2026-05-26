# AssetWise

全カテゴリ横断リユース・アグリゲーター。スマートフォンで写真を撮るだけで品目を AI 判定し、最適な売却・買取チャネルへ送客する 2 層構成の SaaS プロダクト。

---

## アーキテクチャ概要

```
┌─────────────────────────────┐
│  web (Next.js 15 / App Router)  │  ← ブラウザ（PC / モバイル Web）
└───────────────┬─────────────┘
                │ REST / JSON
┌───────────────▼─────────────┐
│  backend (FastAPI + PostgreSQL) │  ← 査定・ルーティング・アフィリエイト
└─────────────────────────────┘
```

| レイヤー | 役割 |
|---|---|
| フロントエンド | 写真アップロード → 状態選択 → 査定結果・送客チャネル表示 |
| バックエンド | Gemini Vision による品目解析・価格帯推定、ルールベース＋LLM ハイブリッドルーティング、アフィリエイトリンク生成 |

---

## 技術スタック

| 領域 | 採用技術 |
|---|---|
| API サーバー | Python 3.11+ + FastAPI 0.115 + uvicorn |
| ORM / マイグレーション | SQLAlchemy 2.0 (AsyncSession) + Alembic |
| DB ドライバ | asyncpg |
| データベース | PostgreSQL 16 |
| AI | Google Gemini（`google-genai` SDK）Vision + Structured Outputs |
| フロントエンド | Next.js 15 (App Router) + React 19 + TypeScript + Tailwind CSS |
| コンテナ | Docker Compose |
| CI | GitHub Actions |

> **フロント構成（2026-05-26 確定）**: プロダクトは `web/`（Next.js）の Web アプリ単一に一本化。当初の Expo / React Native モバイルアプリ案は凍結し、旧 `frontend/` ディレクトリは廃止した。モバイルネイティブ対応は将来フェーズで再評価する。

---

## クイックスタート（Docker Compose）

### 前提

- Docker Desktop が起動していること
- `GOOGLE_API_KEY` が手元にあること（https://aistudio.google.com/app/apikey から取得）

### 手順

```bash
# 1. リポジトリ取得
git clone <repo-url>
cd assetwise

# 2. 環境変数ファイルを用意
cp backend/.env.example backend/.env
# backend/.env を開き、GOOGLE_API_KEY=AIza... を実際のキーに書き換える

# 3. 起動（初回はイメージビルドあり）
docker compose up --build

# 4. 動作確認
# → http://localhost:8000/docs  （Swagger UI）
# → http://localhost:8000/health（ヘルスチェック）
```

> **Note:** `GOOGLE_API_KEY` が空のままでも起動はする（`docker-compose.yml` が `${GOOGLE_API_KEY:-}` でフォールバック済み）。ただし `/api/v1/analyze` エンドポイントは Gemini Vision API を呼ぶため、キーが必要。

### 停止・クリーンアップ

```bash
# コンテナ停止
docker compose down

# DB ボリュームごと削除（データ全消去）
docker compose down -v
```

---

## フロントエンド起動（Next.js / `web/`）

```bash
cd web
npm install                       # 初回のみ
cp .env.local.example .env.local  # バックエンド URL を設定
npm run dev                       # → http://localhost:3000
```

バックエンド向け URL は `web/.env.local` の `NEXT_PUBLIC_API_URL` で設定。
ローカルでは `http://localhost:8000/api/v1` のまま動作する。

---

## テスト実行

### バックエンド（pytest）

```bash
cd backend

# 仮想環境セットアップ（初回のみ）
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]" aiosqlite httpx

# テスト実行
pytest -v

# Lint
ruff check .
```

> テストはインメモリ SQLite を使用するため、PostgreSQL の起動は不要。

### フロントエンド（型チェック / Lint）

```bash
cd web
npx tsc --noEmit     # 型チェック
npm run lint         # ESLint (next lint)
```

---

## ディレクトリ構造

```
assetwise/
├── .github/
│   └── workflows/
│       └── ci.yml              # GitHub Actions CI（backend: ruff + pytest / web: tsc）
├── backend/
│   ├── alembic/                # DB マイグレーション
│   │   └── versions/           # 0001_initial_schema / 0002_add_defect_evidence
│   ├── app/
│   │   ├── api/v1/
│   │   │   ├── router.py       # v1 ルーター集約
│   │   │   └── endpoints/
│   │   │       ├── analyze.py  # POST /v1/analyze（Vision + ルーティング）
│   │   │       └── estimate.py # POST /v1/estimate（価格帯推定）
│   │   ├── db/
│   │   │   ├── models/         # SQLAlchemy ORM モデル（item / assessment / channel / routing / defect）
│   │   │   └── session.py      # AsyncSession ファクトリ
│   │   ├── services/
│   │   │   ├── vision.py       # Gemini Vision 呼び出し（google-genai）
│   │   │   ├── routing.py      # ルールベース + LLM ハイブリッドルーティング
│   │   │   ├── affiliate.py    # アフィリエイトリンク生成
│   │   │   └── seed.py         # ルーティングルール初期データ
│   │   ├── config.py           # pydantic-settings（環境変数）
│   │   ├── main.py             # FastAPI アプリ + ライフサイクル
│   │   └── schemas.py          # Pydantic リクエスト/レスポンス型
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_api.py
│   │   ├── test_routing.py
│   │   └── test_affiliate.py
│   ├── .env.example            # 環境変数テンプレート ← ここをコピーして .env を作る
│   ├── Dockerfile
│   ├── alembic.ini
│   ├── er_diagram.mmd          # Mermaid ER 図
│   └── pyproject.toml
├── web/
│   ├── src/
│   │   ├── app/                # Next.js App Router
│   │   │   ├── page.tsx        # トップ（撮影入口）
│   │   │   ├── analyzing/      # 解析中画面
│   │   │   ├── condition/      # 状態選択画面
│   │   │   ├── result/         # 査定結果・送客チャネル
│   │   │   └── globals.css
│   │   ├── components/         # ChannelCard / ConditionCard / DefectUploader
│   │   └── lib/                # api.ts（API クライアント）/ format.ts
│   ├── package.json
│   ├── next.config.ts
│   ├── tailwind.config.ts
│   ├── vercel.json             # Vercel デプロイ設定
│   └── .env.local.example
├── docker-compose.yml
├── AssetWise_Cowork_Handoff.md # 設計意図・未解決事項の詳細（唯一の前提仕様）
└── README.md                   # このファイル
```

---

## カテゴリ体系（`CategoryTier`）

| Tier | 対象品目 | 主な送客先 |
|---|---|---|
| `high_value_standard` | ガジェット・ブランド品・貴金属 | 買取業者 ASP（800〜6,600 円/件） |
| `low_value_daily` | 生活雑貨・家電・家具 | フリマ送客 + まとめ買取 |
| `vehicle` | 車 | MOTA / カーセンサー等の一括査定 |
| `real_estate` | 不動産 | 不動産一括査定（※要法務確認） |

---

## 未確定事項・TODO

| 優先度 | 内容 | 担当 |
|---|---|---|
| 🔴 HIGH | ASP 提携申し込み（買取業者 ASP の実 URL・手数料率取得） | ビジネス |
| 🔴 HIGH | 不動産カテゴリの法務確認（宅建業法・景品表示法） | 法務 |
| 🟡 MEDIUM | ステマ規制 PR 表記 UI の実装（`is_sponsored` フラグ対応） | フロントエンド (web) |
| 🟡 MEDIUM | `RoutingRule` 管理 API（Admin CRUD）の要否判断 | PM |
| 🟡 MEDIUM | 車カテゴリの JSONB 属性定義（年式・走行距離・排気量） | バックエンド |
| 🟢 LOW | 本番環境構成（backend: Railway、web: Vercel の構成確定） | インフラ |
| 🟢 LOW | レートリミット・キャッシュ設計（Gemini API コスト最適化） | バックエンド |

詳細は `AssetWise_Cowork_Handoff.md` を参照。

---

## ライセンス

Private — 無断転用禁止
