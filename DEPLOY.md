# デプロイ手順 — ソクウリ

実 URL で公開するための手順。フロントエンドは Vercel、バックエンドは Railway に配置する。

## 構成

| 対象 | ディレクトリ | ホスティング |
| :-- | :-- | :-- |
| フロントエンド（Next.js 15） | `web/` | Vercel |
| バックエンド（FastAPI） | `backend/` | Railway |

フロントは環境変数 `NEXT_PUBLIC_API_URL` 経由でバックエンドの API を呼び出す。

---

## 0. 事前確認（ローカル）

Vercel のデプロイは `next build` を実行する。型エラー・ESLint エラーがあるとビルドが失敗するため、先にローカルで通ることを確認する。

```
cd web
npm install
npm run build
```

エラーが出た場合は修正してから次へ進む。

> 補足: 旧 `frontend/` ディレクトリ（React Native の名残）は 2026-05-26 に削除済み。プロダクトは `web/` 単一。

---

## 1. GitHub リポジトリの作成と push

1. GitHub で新規リポジトリを作成（例: `sokuri`。Private で可）。
2. プロジェクトルート（`web/` と `backend/` を含む階層）で以下を実行:

```
cd <プロジェクトルート>
git init
git add .
git commit -m "initial commit"
git branch -M main
git remote add origin https://github.com/<ユーザー名>/sokuri.git
git push -u origin main
```

`.gitignore` は設定済みで、`node_modules` / `.env.local` / `.next` などは自動的に除外される。

---

## 2. Vercel へデプロイ（フロントエンド）

1. https://vercel.com に GitHub アカウントでログイン。
2. 「Add New… → Project」から上記リポジトリを Import。
3. **重要 — Root Directory に `web` を指定する。** プロジェクトが `web/` サブディレクトリにあるため、これを忘れるとビルドに失敗する。
4. Framework Preset は `Next.js` が自動検出される。Build / Output 設定は既定のままでよい。
5. Environment Variables に次を追加:

   | Name | Value |
   | :-- | :-- |
   | `NEXT_PUBLIC_API_URL` | バックエンドの API URL（例: `https://<railwayサブドメイン>.up.railway.app/api/v1`） |

   バックエンド URL が未確定なら暫定値で可。トップページは表示できる（査定フローはバックエンド稼働後に有効になる）。
6. 「Deploy」を実行。数分で `https://<プロジェクト名>.vercel.app` が発行される。

---

## 3. バックエンド（Railway）側の対応

1. `backend/` を Railway にデプロイ（`backend/railway.json` 同梱済み）。
2. Railway で PostgreSQL を追加し、環境変数 `DATABASE_URL` と `GOOGLE_API_KEY` を設定する。
3. **CORS 設定（必須）**: FastAPI 側で Vercel のドメイン（`https://<プロジェクト名>.vercel.app`）を許可オリジンに追加する（`backend/app/main.py` の CORS ミドルウェア設定）。未設定だと、ブラウザからの査定 API 呼び出しが CORS でブロックされる。
4. バックエンド URL が確定したら、Vercel の `NEXT_PUBLIC_API_URL` を実値に更新し、再デプロイする。

---

## 4. 以降の更新

`main` ブランチへ push するたびに、Vercel が自動でビルド・再デプロイする。Railway も同様に自動デプロイに設定できる。

---

## 補足

- トップページ（ランディング）はバックエンドなしで表示・レビュー可能。
- 写真アップロード → 査定 → 結果の一連のフローは、バックエンド（Railway）と Gemini API キーが揃って初めて動作する。
- アカウント作成（GitHub / Vercel / Railway）と各サービスの連携操作はアカウント所有者本人が行う必要がある。
