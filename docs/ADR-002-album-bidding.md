# ADR-002: 「まとめてソクウリ」アルバム + 業者一括入札の段階導入

- ステータス: Accepted (Phase 1 実装済、Phase 2+ 設計フェーズ)
- 日付: 2026-05-26
- 関係者: kohei（オーナー）, Claude（CTO 代行）

## コンテキスト

既存「ソクウリ」(単品アフィリエイト型) を「まとめてソクウリ」(MOTA 型一括査定マッチング)
へ転換する。React Native への切替案を退け、現行 Next.js + FastAPI + PostgreSQL を主軸として
段階導入する。

## 決定

### Phase 1（実装済 ✅）
- フロントエンドのみ追加: `/album`, `/album/submitted`
- 既存 `/api/v1/analyze` と `/api/v1/estimate` を N 回呼ぶ薄実装
- アルバム永続化は **sessionStorage のみ**、DB 改修ゼロ
- 「業者匿名・営業電話ゼロ」を全面差別化軸
- 業者連携は Wizard of Oz（管理者が手動メール転送）

### Phase 2（次フェーズ、Wizard of Oz 自動化前段）
バックエンド側にアルバム永続化 + 業者ロール導入:

```sql
-- albums: ユーザーが束ねた不用品セット
CREATE TABLE albums (
  id          UUID PRIMARY KEY,
  user_email  TEXT,                -- Phase 2 は anon、Phase 3 でユーザー化
  status      TEXT NOT NULL,        -- draft | bidding | closed | matched | cancelled
  total_estimated_jpy INTEGER,
  expires_at  TIMESTAMPTZ,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- album_items: アルバム内の個別商品（assessment と 1:1）
CREATE TABLE album_items (
  id              UUID PRIMARY KEY,
  album_id        UUID NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
  assessment_id   UUID NOT NULL REFERENCES assessments(id),
  position        INTEGER NOT NULL,
  UNIQUE (album_id, assessment_id)
);

-- businesses: 提携業者
CREATE TABLE businesses (
  id              UUID PRIMARY KEY,
  name            TEXT NOT NULL,
  email           TEXT NOT NULL UNIQUE,
  license_no      TEXT,                 -- 古物商許可番号
  kyc_status      TEXT NOT NULL,        -- pending | verified | rejected
  service_area    JSONB,                -- {prefectures: [...]}
  rating          NUMERIC(3,2),         -- 0.00 - 5.00
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- bid_invitations: 業者への入札依頼（送信ログ）
CREATE TABLE bid_invitations (
  id            UUID PRIMARY KEY,
  album_id      UUID NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
  business_id   UUID NOT NULL REFERENCES businesses(id),
  invited_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  viewed_at     TIMESTAMPTZ,
  UNIQUE (album_id, business_id)
);

-- bids: 業者入札
CREATE TABLE bids (
  id            UUID PRIMARY KEY,
  album_id      UUID NOT NULL REFERENCES albums(id) ON DELETE CASCADE,
  business_id   UUID NOT NULL REFERENCES businesses(id),
  amount_jpy    INTEGER NOT NULL,
  pickup_fee_jpy INTEGER NOT NULL DEFAULT 0,
  valid_until   TIMESTAMPTZ NOT NULL,
  notes         TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (album_id, business_id)         -- 1 業者 1 入札
);

-- deals: 成約（ユーザーが業者を選択した時点）
CREATE TABLE deals (
  id              UUID PRIMARY KEY,
  album_id        UUID NOT NULL UNIQUE REFERENCES albums(id),
  winning_bid_id  UUID NOT NULL REFERENCES bids(id),
  status          TEXT NOT NULL,        -- agreed | picked_up | paid | cancelled
  commission_jpy  INTEGER,              -- 当社取り分（成功報酬）
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### Phase 3（自動入札 + 通知）
- LINE Messaging API or Email (SendGrid) で業者通知
- ユーザー側はポーリング（30 秒間隔）または SSE で入札状況更新
- 入札期間 24-48h、自動締切ジョブは Railway Cron

### Phase 4（精算）
- Stripe Connect で業者からの手数料引き落とし
- 成約後のレビュー収集（business.rating 更新）

## 影響範囲

| 範囲 | Phase 1 | Phase 2 |
|------|---------|---------|
| フロント | `/album`, `/album/submitted` 新規 ✅ | 業者ダッシュボード `/biz/*` |
| バックエンド | 変更なし ✅ | router/albums, schemas, alembic 5 リビジョン |
| DB | 変更なし ✅ | 6 テーブル追加 |
| 認可 | 不要 ✅ | user / business / admin の三層 |
| 通知 | localStorage のみ ✅ | SendGrid + LINE |

## やらないこと（Phase 2 までは禁則）

- **WebSocket** によるリアルタイム入札（過剰、ポーリングで十分）
- **PostgreSQL RLS**（運用コスト > ROI、アプリ層認可で十分）
- **産業廃棄物の取り扱い**（特定産業廃棄物処理業の許認可が別途必要、利用規約で明示除外）
- **Stripe Connect**（成約 100 件超えるまで手動精算）

## 検証 KPI（Phase 1 → Phase 2 移行判断）

- アルバム作成完了率: 30% 以上
- 平均アルバム内アイテム数: 3 点以上
- メール通知登録率: 50% 以上
- 1 週間で 50 アルバム以上

上記未達なら Phase 2 着手前に Phase 1 を磨く（フリクション分析 → UI 改修）。

## 営業電話ゼロを保証する技術設計

1. ユーザー個人情報は `albums.user_email` のみ取得、業者には絶対渡さない
2. 業者通知メールには **アルバム ID と要約のみ**（住所/連絡先非含む）
3. 業者ダッシュボードでは **匿名アルバム ID** で全データ表示
4. 成約画面で初めて `deals` 経由でユーザー連絡先を業者へ開示
5. 開示後も電話番号より住所/メール優先（電話オプトインを別途設定）
