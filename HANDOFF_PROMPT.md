# 🤖 新 PC の Cowork に貼り付ける引き継ぎプロンプト

このファイルの **以下の区切り線で囲まれた部分すべて** を選択してコピー → 新 PC で
Claude desktop を起動 → Cowork mode を ON → 作業フォルダに `C:\sokuri` を選択 →
最初のメッセージとして貼り付けてください。

---ここから貼り付け開始---

こんにちは。私は kohei、`ko.13.hei@gmail.com` です。
旧 PC から新 PC に環境移行したので、ソクウリ／AssetWise プロジェクトの作業を続きから引き継いでください。

## プロジェクト概要

「ソクウリ／まとめてソクウリ」(sokuri / matome-sokuri) は、写真 1 枚から AI が中古品を鑑定して最適な買取チャネルを提案する Web サービスです。MOTA 型の一括査定マッチングを軸に、車・不動産・ブランド品など全カテゴリを横断します。

## 本番デプロイ状態（2026-06-01 時点で稼働中）

- **フロント**: `https://sokuri.vercel.app/` (Vercel Hobby、Next.js 15.5.18 App Router)
- **バックエンド**: `https://sokuri-backend.onrender.com/` (Render Free、FastAPI + asyncpg + PostgreSQL)
- **API base**: `https://sokuri-backend.onrender.com/api/v1`
- **DB**: Render Managed Postgres (sokuri-db、Oregon リージョン)
- **GitHub**: `https://github.com/japandaily-hub/sokuri` (main ブランチが本番、autoDeploy)
- **AI**: Google Gemini 2.5 Flash (Vision + Structured Outputs)
- **作業フォルダ**: `C:\sokuri`

## 直前のセッションで完了した主要作業

1. **Railway → Render へバックエンド移行**（Railway の healthcheck 失敗が原因不明だったため案 B 採択）。`render.yaml` Blueprint で sokuri-db + sokuri-backend を一発プロビジョニング
2. 移行時に踏んで潰したバグ 4 件:
   - `render.yaml` の `dockerCommand: sh -c "..."` で argv 解釈崩壊 (`exit 127`) → `backend/start.sh` に切り出し、Dockerfile CMD で呼ぶ構成に変更
   - `app/api/v1/endpoints/analyze.py` の leftover `from openai import OpenAIError` で `ModuleNotFoundError` → `google.genai.errors.APIError` に置換
   - `app/api/v1/endpoints/estimate.py` line 290 に paste corruption（orphan fragment + 重複 `upload_defect` ルート）で `SyntaxError: unmatched ')'` → 67 行 truncate
   - `app/services/seed.py` の重複関数定義 + orphan `_ROUTING_RULE_SEEDS` 末尾 → 予防的に 110 行 truncate
3. **paste corruption 再発防止 CI** を `.github/workflows/ci.yml` の `syntax-guard` job に追加（ruff/pytest 失敗時でも先に止める）
4. **frontend の `FALLBACK_PROD_API_URL`** を `web/src/lib/api.ts` で Render URL にハードコード（Vercel env var Sensitive 制約回避）
5. **新 PC 移行用ツール群**を `.tools/` に整備:
   - `restore-env.ps1` — OneDrive 同期された `.env` を配置
   - `restore-appdata-claude.ps1` — Claude desktop の memory / plugins / settings を UWP container に復元
   - `syntax-guard.ps1` — push 前のローカル構文 sanity
   - `push-render.ps1`, `backup-env.ps1`, `backup-appdata-claude.ps1`, `cleanup-appdata-backup.ps1`
6. 詳細手順書: `C:\sokuri\NEW_PC_MIGRATION.md`

## 既知の落とし穴（私と関わる時に気を付けて欲しいこと）

- **`C:\sokuri` の `.bat` は Windows Defender に隔離される**。ヘルパーは必ず `.ps1` で書く（`.tools/` 配下はすべて .ps1）
- **OneDrive 配下で bash サンドボックスを動かすと挙動不安定**。`C:\sokuri` 直下を維持し、bash のテスト出力を健全性の証拠にしない（Read/Write/Edit を優先）
- **Vercel の env var を Sensitive 化すると `NEXT_PUBLIC_*` がクライアントバンドルに inline されない**。`FALLBACK_PROD_API_URL` ハードコードで回避済
- **Render Free tier は inactivity で spin down**、初回リクエストに最大 50 秒の遅延
- **estimate.py / seed.py を編集する時は orphan fragment と重複関数定義の有無を先に確認**（過去の paste corruption の残骸が再発する可能性）
- **git push は `C:\sokuri\.tools\push-render.ps1` 経由で実行**（bash サンドボックスからは GitHub credential が無いため）

## あなた（新 Claude）に期待する初動

1. `C:\Users\<ユーザー名>\AppData\Local\Packages\Claude_*\LocalCache\Roaming\Claude\local-agent-mode-sessions\*/spaces/*/memory/MEMORY.md` を読んで過去の memory を取り込む（restore-appdata-claude.ps1 で復元されていれば自動で context に入るはず）
2. `git log --oneline -10` で最新コミット履歴を確認
3. 本番疎通確認: `https://sokuri-backend.onrender.com/health` が 200 を返すかブラウザで確認
4. 直近の私のリクエスト（このプロンプトの後に続く依頼）に取り掛かる

## 開発者プロファイル

- ロール: シニアソフトウェアエンジニア兼システムアーキテクト
- スタック: TypeScript / Python、Next.js (App Router) + Tailwind、FastAPI、PostgreSQL (Prisma ORM)、Jest / Pytest、Node.js v20+、Docker
- 設計方針: SOLID + DRY、計算量と堅牢性を可読性より優先、SQLi/XSS/CSRF 対策をデフォルトで含める
- コミュニケーション: 簡潔・客観的・断定的。冗長な挨拶不要。コードは即利用可能な形式で
- 変更時は「影響範囲」と「変更の論理的根拠」を 1 行で先に述べる
- 推測実装には `[推測]` を明記する

引き継ぎ完了の合図として「ソクウリのコンテキストを取り込みました」と一言返してください。その後に続けて私が次のタスクを依頼します。

---ここまで貼り付け終了---

## 補足: このファイルを新 PC で開く 2 つの方法

1. **git clone 後にメモ帳で開く**: `notepad C:\sokuri\HANDOFF_PROMPT.md`
2. **OneDrive 経由**: 新 PC で OneDrive sync 後に `C:\sokuri\HANDOFF_PROMPT.md`（こちらも git 経由で同期されます）

このプロンプトを貼った後の新 Claude は、以後のセッションでこのチャットの直接的な続きとして振る舞えます。
