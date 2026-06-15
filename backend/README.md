# カタヅケ Backend — Phase 1: ドメイン/データモデル設計

## 概要

ハンドオフ文書 §7 Phase 1 の成果物。ルーティングテーブルを中心とした全エンティティのスキーマ定義、ER 図、ORM 選定根拠を記載する。

---

## ER 図

`er_diagram.mmd`（Mermaid）を参照。

主要なリレーション:

- `items` → `assessments`（1:N）: 1 品目に対し複数回の査定を許容（相場変動追跡・再査定）
- `assessments` → `recommendations`（1:N）: 1 査定が複数チャネルを推奨（§1-1 低単価生活品の例）
- `channels` → `affiliate_meta`（1:0..1）: 収益化不可チャネル（フリマ等）は `affiliate_meta` を持たない
- `routing_rules` → `recommendations`（0..1:N）: LLM フォールバック由来の推奨は `source_routing_rule_id = NULL`

---

## ORM 選定根拠: SQLAlchemy 2.0 + asyncpg

ハンドオフ §4 に「FastAPI なら SQLAlchemy or Prisma Client Python が候補」と記載されている。以下の根拠で SQLAlchemy 2.0 を採用する。

### 採用理由

| 観点 | SQLAlchemy 2.0 | Prisma Client Python |
| :-- | :-- | :-- |
| 成熟度 | 20 年超の実績・PostgreSQL 全機能対応 | Python クライアントは beta 扱い（2025 時点） |
| async 対応 | `AsyncSession` + `asyncpg` が production grade | ジェネレータ式・実装品質に不確実性あり |
| Alembic 統合 | 公式ツール。autogenerate・命名規約で差分管理が安定 | Prisma Migrate（別系統。FastAPI との二重管理になる） |
| 型安全性 | `Mapped[T]` + `mapped_column` で完全な静的型付け | Prisma スキーマからの型生成（Python 側は partial） |
| JSONB / 配列型 | `postgresql.JSONB` など方言型をネイティブサポート | 方言固有型のサポートが限定的 |

### 採用しなかった理由: Prisma Client Python

- Python クライアントは 2025 年時点で GA 未到達。本番投入のリスクが高い。
- Prisma スキーマと SQLAlchemy モデルの二重管理は DRY 原則違反。
- FastAPI + asyncpg のエコシステムに対して SQLAlchemy の方が知見・事例が豊富。

### asyncpg を選んだ理由

`psycopg2` の非同期版（`psycopg[async]`）と比較して、asyncpg は PostgreSQL バイナリプロトコルを直接実装しており、高スループット時のレイテンシが低い。FastAPI の async エンドポイントとの親和性が高い。

---

## ルーティング判定方式の選定（§6-2）

ハンドオフで「ルールベース / LLM 判定 / ハイブリッド」の 3 案比較が求められていた。

| 方式 | 長所 | 短所 |
| :-- | :-- | :-- |
| ルールベースのみ | 監査可能・コスト 0・決定論的 | 網羅的なルール整備が必要。未知カテゴリに弱い |
| LLM のみ | 網羅性が高い・未知カテゴリに対応 | コスト・レイテンシ・非決定論的（監査困難） |
| **ハイブリッド（採用）** | ルールで決定論的に解決、未マッチのみ LLM にフォールバック | 複雑度が上がるが、`routing_method` で出自を監査可能 |

**採用: ハイブリッド方式**。`routing_rules` テーブルで権威的判定を行い、マッチしない場合のみ LLM を使用。`Assessment.routing_method`（RULE / LLM / HYBRID）で出自を記録し、ステマ規制対応（§3）の監査可能性を担保する。

---

## カテゴリ分類体系（`CategoryTier`）

§1-1 のカテゴリ表から以下 4 Tier を定義。ルーティング判定の主キーとなる。

| Tier 値 | 意味 | 主な送客先 |
| :-- | :-- | :-- |
| `high_value_standard` | 高単価標準品（ガジェット/ブランド/貴金属） | 買取業者 ASP（800〜6,600 円/件規模） |
| `low_value_daily` | 低単価生活品（生活雑貨/家電/家具） | フリマ送客 + まとめ買取送客 |
| `vehicle` | 車 | MOTA / カーセンサー等の一括査定 |
| `real_estate` | 不動産 | 不動産一括査定（要法務確認） |

細分類（品目名）は `Item.detected_category_label` の文字列で保持し、スキーマを肥大させない。Tier 固有の属性（年式・走行距離・面積など）は `Item.attributes`（JSONB）に格納。

---

## ステマ規制対応設計（§3）

査定の中立性と送客の広告性をデータ構造で分離:

- `Assessment`: 相場情報のみ（広告要素なし）
- `AssessmentRecommendation.is_sponsored`: 有料送客枠フラグ。`True` の場合、UI で PR 表記を要する
- `AffiliateMeta.requires_pr_label` / `pr_label_text`: チャネル単位の PR 表記設定

---

## マイグレーション実行

```bash
# Docker で PostgreSQL を起動
docker run -d --name assetwise-db \
  -e POSTGRES_USER=assetwise \
  -e POSTGRES_PASSWORD=assetwise \
  -e POSTGRES_DB=assetwise \
  -p 5432:5432 postgres:16

# 依存インストール
cd backend
pip install -e ".[dev]"

# マイグレーション適用
alembic upgrade head

# SQL 確認（DB 不要）
alembic upgrade head --sql
```

---

## Phase 2 への接続点

Phase 1 完了後、Phase 2（API 契約設計）で以下を確定する:

- `/analyze` の責務再定義（ハンドオフ §5 未解決の不整合）: 「査定一括」か「/analyze + /estimate 分割」か
- `Item` / `Assessment` / `AssessmentRecommendation` の Pydantic スキーマ（レスポンス型）
- `RoutingRule` の管理 API（Admin 向け CRUD）の有無
