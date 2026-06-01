# 新 PC 移行手順 — ソクウリ／AssetWise

最終更新: 2026-06-01。所要時間目安: **30〜60 分**（ソフト DL 含む）。

---

## 0. 移行の全体像

ソクウリは主要資産がほぼ全てクラウド側にあるため、新 PC では「ソフトを入れる → サインインする → リポジトリを clone する → ローカル秘密だけ手動コピー」で完全復元できます。

| 資産 | 保管場所 | 新 PC での復元方法 |
|------|--------|------------------|
| ソースコード | GitHub (`japandaily-hub/sokuri`) | `git clone` |
| 本番フロント | Vercel | サインインのみ。再デプロイ不要 |
| 本番バックエンド | Render | サインインのみ。再デプロイ不要 |
| 本番 DB | Render Managed Postgres | 触らない（データ保全） |
| Gemini API キー | Render dashboard + 旧 PC の `backend/.env` | dashboard で確認 or 旧 PC からコピー |
| Claude メモリ | 旧 PC `%APPDATA%\Claude\...\memory` | 手動コピー（任意） |
| Helper スクリプト | git 管理下 (`.tools/`) | clone で自動復元 |

---

## 1. 旧 PC で「持ち出すもの」をまとめる

USB メモリ or クラウドストレージ（OneDrive/Dropbox）にコピーしてください。

### 1-A. 必須: ローカル秘密ファイル

これは **絶対に git に入っていない**ため、手動で移動する必要があります。

| ソースパス（旧 PC） | 内容 |
|---|---|
| `C:\sokuri\backend\.env` | `GOOGLE_API_KEY`, ローカル `DATABASE_URL`, `SQL_ECHO` |
| `C:\sokuri\web\.env.local` | ローカル `NEXT_PUBLIC_API_URL` |

> **コピーが面倒なら省略可。** `GOOGLE_API_KEY` は Render dashboard にも入っているので、本番運用だけなら新 PC ローカルにこの 2 ファイルが無くても支障ありません（ローカル `npm run dev` で開発したい時だけ必要）。

### 1-B. 任意: Claude メモリ（プロジェクト文脈）

旧 PC で Claude が覚えていた「ソクウリ運用知識」を保持したい場合のみ。

```text
コピー元: C:\Users\ko13h\AppData\Roaming\Claude\local-agent-mode-sessions\
コピー先: 同じパス（新 PC のユーザー名に置換）
```

フォルダ階層が深いですが、丸ごとコピーすれば次回 Cowork セッションで前の memory が読み込まれます。

### 1-C. 任意: 旧 PC のリポジトリディレクトリ

`C:\sokuri\` 全体をコピーする必要は **ありません**。GitHub に commit `be6e018` まで全部上がっているので、新 PC で `git clone` する方が確実かつ高速です（`node_modules` を持ち出すと数百 MB の無駄）。

---

## 2. 新 PC でのセットアップ

### 2-1. 必須ソフトをインストール

| ソフト | 入手元 | 用途 |
|---|---|---|
| Git for Windows | <https://git-scm.com/download/win> | clone, push（PowerShell 用 credential helper 同梱） |
| Node.js v20 LTS | <https://nodejs.org/> | frontend `npm install && npm run dev` |
| Python 3.12 | <https://www.python.org/downloads/> | backend ローカル実行 |
| GitHub CLI (推奨) | <https://cli.github.com/> | `gh auth login` で 1 コマンド認証 |
| Claude desktop | <https://claude.com/download> | Cowork mode 継続利用 |

> 旧 PC で使っていた **Docker Desktop は不要**（バックエンドは Render が Docker ビルドする）。

### 2-2. リポジトリを clone

PowerShell を開いて:

```powershell
# C:\sokuri に clone（旧 PC と同じパスにすると memory 内のパス参照が壊れない）
git clone https://github.com/japandaily-hub/sokuri.git C:\sokuri
cd C:\sokuri
```

GitHub 認証はブラウザで自動的に走ります。`gh auth login` を済ませてあれば即座に通ります。

### 2-3. ローカル秘密ファイルを配置（1-A で持ち出した場合）

```text
C:\sokuri\backend\.env       ← USB から
C:\sokuri\web\.env.local     ← USB から
```

### 2-4. クラウドサービスへサインイン

すべてブラウザでログインするだけ。**新規アカウント作成は不要**。

| サービス | URL | 同じアカウントでログイン |
|---|---|---|
| GitHub | <https://github.com/login> | (japandaily-hub 所属) |
| Vercel | <https://vercel.com/login> | GitHub 連携で入れる |
| Render | <https://dashboard.render.com> | GitHub 連携で入れる |
| Google AI Studio | <https://aistudio.google.com> | Google アカウント（`ko.13.hei@gmail.com`） |

すべてサインインすれば、旧 PC と完全に同じ管理画面が見えます。

### 2-5. （任意）ローカル開発の動作確認

新 PC でローカル `npm run dev` を試したい場合のみ:

```powershell
cd C:\sokuri\web
npm install
npm run dev   # http://localhost:3000
```

```powershell
cd C:\sokuri\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
uvicorn app.main:app --reload --port 8000
```

> ローカル開発をしない場合（本番だけ触る）、この手順はスキップ可。

---

## 3. 本番デプロイの動作確認（5 分）

新 PC で初めて `git push` する時に Render が再ビルドを始めないか心配な方へ:

- **新 PC でただ clone しただけでは何も起きません**。`git push` するまで Render は再ビルドしません。
- 念のため、新 PC でブラウザから本番 URL を 1 回開いてください:
  - <https://sokuri.vercel.app/> → トップ表示
  - <https://sokuri-backend.onrender.com/health> → `{"status":"ok"}` 表示

両方表示できれば移行完了です。

---

## 4. 既知の注意点（旧 PC からの引き継ぎ事項）

過去のセッションで踏んだ落とし穴。新 PC でも同じ罠が再発する可能性あり:

1. **`C:\sokuri` の `.bat` は Windows Defender に隔離されやすい** → ヘルパーは `.ps1` で書く（`.tools/` 配下が既に全部 .ps1）
2. **OneDrive 配下で WSL/bash を動かすと挙動が不安定** → C ドライブ直下 `C:\sokuri` を維持
3. **Vercel の env var を Sensitive にすると `NEXT_PUBLIC_*` がクライアントに inline されない** → `web/src/lib/api.ts` の `FALLBACK_PROD_API_URL` でハードコード回避済（現在 `https://sokuri-backend.onrender.com/api/v1`）
4. **Render Free tier は inactivity で spin down、初回リクエストに 50 秒** → ユーザー体感が悪ければ Upgrade

---

## 5. 1 行サマリー

「**Git とブラウザにサインインすれば本番は何もせず動き続ける。ローカル `.env` 2 ファイルだけ手動コピー、それ以外は全部 clone で復元**」

---

## 付録: バックエンド／フロントの最終 commit

| 項目 | commit | 内容 |
|---|---|---|
| 直近 push | `be6e018` | helper スクリプト追加 |
| Render Live | `61da936` | estimate.py / seed.py 整理 → backend 稼働 |
| Vercel | `201ff7b` | API URL を Render に切替 |

移行後、`git log --oneline -5` で同じ並びが見えれば OK です。
