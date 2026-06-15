# PLAN — カタヅケ 業者獲得エンジン実装（量・スケール フェーズ）
## version: 1.0 / 2026-06-15 / 予算上限: ¥0 / CYCLE_LIMIT: 6

---

## 0. 前提コンテキスト（全エージェント必読）

### プロジェクト状態
- **本番稼働中**: sokuri.vercel.app（Vercel/Next.js 15）+ sokuri-backend.onrender.com（Render/FastAPI）
- **正典repo**: C:\sokuri（github.com/japandaily-hub/sokuri）
- **OneDriveパス**: C:\Users\ko13h\OneDrive\ドキュメント\Claude\Projects\ソクウリ
- **現フェーズ**: β本番デプロイ・E2E全合格済み → 業者獲得（量・スケール）フェーズ

### 技術スタック
```
Backend : Python FastAPI / PostgreSQL / Alembic / SQLAlchemy (async)
Frontend: Next.js 15 / TypeScript / Tailwind CSS / NextAuth v5 beta.29
Infra   : Render (backend) / Vercel (frontend) / render.yaml 自動デプロイ
```

### 重要ファイル
```
backend/
  app/
    api/v1/endpoints/admin.py       ← 管理エンドポイント（招待コード・業者承認）
    db/models/operator.py           ← Operatorモデル
    db/models/invite.py             ← Inviteモデル
    schemas_katadzuke.py            ← Pydanticスキーマ
    api/v1/router.py                ← ルーター登録
  alembic/versions/                 ← マイグレーション（0001〜0005）
  tests/test_katadzuke_api.py       ← pytest 56 passed
web/
  app/admin/page.tsx                ← 管理画面（招待コード・業者承認）
  lib/katadzuke-api.ts              ← フロントAPIクライアント
```

### 運用制約（絶対厳守）
- **DBはテーブル削除禁止。追加・カラム追加のみ**
- **マイグレーション番号は 0006 から始める**（0001〜0005 は既存）
- **認証トークンはJWT（HS256）、NextAuth v5 Credentials Provider**
- **OneDrive配下はbash Writeが截断する場合あり。bash heredoc方式か Read/Writeツールを使う**

### 現行Operatorモデルの重要フィールド
```python
verified_at: datetime | None   # 承認日時（Noneなら未承認）
is_suspended: bool             # 停止フラグ
invite_code: str               # 登録時の招待コード（unique）
password_hash: str | None      # bcrypt
```

### 現行admin.py の機能
- POST /admin/invites          → 1件ずつ招待コード発行（現状の律速点）
- GET  /admin/invites          → コード一覧
- GET  /admin/operators        → 業者一覧
- PATCH /admin/operators/{id}/verify → 承認/取消

---

## 1. ゴール（North Star）

**週次・新規"稼働"業者数（登録後14日以内に1回以上入札）を最大化する**

現状の単一最大ボトルネック＝「招待コード1個ずつ＋admin手動承認」が人間律速。
この2律速を解消し、月40社稼働レベルの受け入れ能力を実現する。

---

## 2. 実装タスク一覧（優先順）

### TASK-1: バルクコード一括発行（軽・即実装）
**目的**: admin画面から N 件の招待コードを一括生成し CSV でダウンロード

**Backend変更**:
1. `backend/app/schemas_katadzuke.py` に追加:
   ```python
   class InviteBulkCreateRequest(BaseModel):
       count: int = Field(ge=1, le=500, description="発行件数")
       lot_name: str | None = Field(default=None, max_length=128, description="ロット名（管理用）")
   
   class InviteBulkCreateResponse(BaseModel):
       codes: list[str]
       lot_name: str | None
       count: int
   ```

2. `backend/app/api/v1/endpoints/admin.py` に追加:
   ```python
   @router.post("/admin/invites/bulk", response_model=InviteBulkCreateResponse, status_code=201)
   async def create_invites_bulk(body: InviteBulkCreateRequest, admin=..., session=...):
       # N件のコードを一括生成してDBに保存
       # lot_nameはInviteモデルに追加が必要（TASK-1 migration）
   ```

3. **Migration 0006**: `invites` テーブルに `lot_name VARCHAR(128) NULL` カラム追加

**Frontend変更** (`web/app/admin/page.tsx`):
- 「バルク発行」ボタン追加 → モーダルで件数・ロット名入力 → 発行 → CSVダウンロード
- CSVフォーマット: `code,lot_name,created_at`

**完成条件**:
- [ ] POST /admin/invites/bulk で100件一括発行できる（pytestで検証）
- [ ] 管理画面から500件まで一括発行できる
- [ ] 生成コードがCSVダウンロードできる
- [ ] 既存の /admin/invites（1件）エンドポイントが壊れていない

---

### TASK-2: オープン業者登録 + 事後審査（limited/active制）
**目的**: 招待コードなしで業者登録可能にし、登録直後は `limited`（入札OK・住所開示NG）、審査通過で `active`（フル機能）

**Backend変更**:
1. **Migration 0007**: `operators` テーブルに `vendor_status VARCHAR(20) NOT NULL DEFAULT 'limited'` 追加
   - 既存 `verified_at` を活用: `vendor_status='active'` ⟺ `verified_at IS NOT NULL`
   - 値: `pending` / `limited` / `active` / `suspended`（suspendedはis_suspendedと共存）

2. `operator.py` モデルに `vendor_status` 追加:
   ```python
   vendor_status: Mapped[str] = mapped_column(String(20), nullable=False, default="limited", index=True)
   ```

3. `backend/app/api/v1/endpoints/auth.py` の業者登録エンドポイントを変更:
   - 招待コードを **任意（optional）** にする
   - 招待コードなしで登録 → `vendor_status='limited'`
   - 招待コードあり → 従来通り（使用済みマーク）、`vendor_status='limited'`（adminが後で`active`へ）
   - `OperatorSignupRequest.invite_code` を `Optional[str]` に

4. 住所開示ロジック（`transactions.py`）:
   - 落札業者への住所開示条件に `operator.vendor_status == 'active'` を追加
   - `limited` 業者が落札した場合、審査通過まで住所は開示しない（メッセージで案内）

5. `admin.py` 更新:
   - PATCH /admin/operators/{id}/verify で `vendor_status` も同時更新（approve → `active`, revoke → `limited`）
   - `OperatorOut` スキーマに `vendor_status` フィールド追加

**Frontend変更**:
- `web/app/operator/signup/page.tsx`: 招待コードフィールドを任意表示に
- `web/app/admin/page.tsx`: 業者一覧に `vendor_status` 表示 + ステータス変更UI
- `web/lib/katadzuke-api.ts`: `vendor_status` 対応

**完成条件**:
- [ ] 招待コードなしで業者登録できる（pytest）
- [ ] 登録直後は vendor_status='limited' で入札はできるが住所は非開示
- [ ] admin が approve → vendor_status='active' → 住所開示可能（pytest）
- [ ] 既存の招待コードあり登録フローが壊れていない（pytest）
- [ ] pytest 全テスト通過（新テスト追加含む）
- [ ] npm run build 成功

---

### TASK-3: 受給バランスゲート（セル密度監視）
**目的**: 「業者数/案件数 < 1:1.5」のセル（エリア×カテゴリ）のみ新規受入。量投入時の業者離脱を防ぐ

**設計**:
- セル = `prefecture` × `purpose`（cases.purposeフィールド流用）
- 初期: 全セルオープン（閾値チェックはread-only監視から始める）
- Phase1: `GET /admin/cell-density` → セル別（登録業者数/月間案件数）を返すだけ
- Phase2（将来）: 閾値超えでウェイトリスト化（今回は実装しない）

**Backend変更**:
1. `admin.py` に追加:
   ```python
   @router.get("/admin/cell-density")
   async def get_cell_density(admin=..., session=...):
       # prefecture × purpose ごとに
       # - operator_count: vendor_status IN ('limited','active') の業者数[推測: 全業者でよい]
       # - case_count_30d: 直近30日の案件数
       # - density_ratio: case_count_30d / operator_count (0除算保護)
       # - status: "ok" | "dense" (ratio < 1/1.5 = 0.67 なら dense)
   ```

2. **管理画面にセル密度テーブル表示**（読み取り専用・ヒートマップ風）

**完成条件**:
- [ ] GET /admin/cell-density が動作する（pytest）
- [ ] 管理画面でセル密度が確認できる
- [ ] 既存テスト全通過

---

### TASK-4: コンプライアンス整備（特定電子メール法・特商法）
**目的**: コールドメール送信のブロッカー解消

**実装内容**:
1. **配信停止ページ** `web/app/unsubscribe/page.tsx`:
   - URLパラメータ `?email=xxx` を受け取りGoogleフォーム（外部）にリダイレクト、または
   - シンプルな「配信停止を承りました。ご連絡ありがとうございます。」静的ページ
   - 配信停止URL形式: `https://sokuri.vercel.app/unsubscribe?email={encoded_email}`

2. **特商法・運営者情報ページ** `web/app/legal/page.tsx`:
   - 運営者名（プレースホルダ `[運営者名]`）
   - 住所（プレースホルダ）
   - 連絡先メールアドレス
   - サービス内容・料金（β期間中無料・将来手数料の記載）
   - 免責事項

3. **フッターに `/legal` リンク追加** (`web/app/layout.tsx` のフッター部分)

**完成条件**:
- [ ] /unsubscribe ページが存在し200を返す（npm build）
- [ ] /legal ページが存在し特商法必須項目を含む（npm build）
- [ ] フッターに /legal リンクがある
- [ ] npm run build 成功

---

## 3. 完成定義チェックリスト（全TASK）

### バックエンド
- [ ] TASK-1: POST /admin/invites/bulk で count=100 が動作 → pytest PASS
- [ ] TASK-2: 招待コードなし業者登録 → vendor_status=limited → pytest PASS  
- [ ] TASK-2: admin approve → vendor_status=active → 住所開示 → pytest PASS
- [ ] TASK-3: GET /admin/cell-density が動作 → pytest PASS
- [ ] 全テスト通過: `pytest backend/tests/ -v` → 0 failed（新テスト追加後）

### フロントエンド
- [ ] TASK-1: admin画面でバルク発行→CSVダウンロードできる
- [ ] TASK-2: 業者登録で招待コード任意
- [ ] TASK-4: /unsubscribe, /legal ページが存在
- [ ] `cd web && npm run build` → 0 errors

### デプロイ準備
- [ ] alembic revision ファイルが 0006, 0007 で存在する（自動適用はRender再起動時）
- [ ] render.yaml に新マイグレーションを妨げる変更がない（既存のまま）
- [ ] commit & push 可能な状態（git status clean）

---

## 4. エージェント推奨構成

- **①ITコンサルタント**: 設計レビュー・DB変更の後方互換性確認・セル密度設計
- **④プログラマー**: TASK-1〜4 の全実装（主力）
- **⑤リーガル**: TASK-4 特商法・特定電子メール法の文言確認
- **⑦データアナリスト**: セル密度ロジック・受給比率計算の検証
- **Wave構成**: Wave1=(①設計+⑤法務 並列) → Wave2=(④実装 TASK-1→2→3→4 順次) → Wave3=(⑦検証)

---

## 5. 禁止事項・リスク管理

- 既存テーブルのカラム削除・テーブル削除 → **禁止**
- マイグレーション番号 0001〜0005 の変更 → **禁止**
- invite_code フィールドの Operator モデルからの削除 → **禁止**（後方互換性）
- `verified_at` フィールドの意味変更 → **禁止**（vendor_status と二重管理で共存）
- 本番DBへの直接接続 → **不要**（Render自動マイグレーション）

---

## 6. 実行メモ（環境）

- sandbox bash: `/sessions/pensive-friendly-mayer/mnt/ソクウリ/` = `C:\Users\ko13h\OneDrive\ドキュメント\Claude\Projects\ソクウリ`
- pytest実行: `cd /tmp && cp -r /sessions/pensive-friendly-mayer/mnt/ソクウリ/backend . && cd backend && pip install -e ".[dev]" --break-system-packages -q && pytest tests/ -v`
- npm build: `cd /sessions/pensive-friendly-mayer/mnt/ソクウリ/web && npm run build`
- OneDriveファイルは Write/Edit ツールで直接編集を優先（bash截断問題を回避）

---

CYCLE_LIMIT: 6
予算: ¥0（課金操作で停止・HALT.flag）
