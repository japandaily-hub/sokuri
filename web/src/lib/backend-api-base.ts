/**
 * バックエンド API の接続先解決（auth.ts / lib/line-link.ts / lib/api.ts が共有する単一の正本）。
 *
 * 以前はこの3ファイルがそれぞれ「未設定なら本番 API にフォールバックする」処理を重複して持っていた。
 * そのため `web/.env.local` の無い worktree で next dev と E2E を回すと、NextAuth の authorize()
 * （サーバー側）がテスト口座のログインや誤パスワードの連続投入を本番 API へ送り、本番のログイン
 * 試行の回数制限に開発者の IP が数えられるおそれがあった（2026-09-25 のセキュリティレビューで判明）。
 *
 * 未設定時の扱いは「本番ビルドかどうか」で分ける:
 * - 本番ビルド（`NODE_ENV === "production"`。Vercel の Production・Preview・`next start` が該当）:
 *   従来どおり {@link PRODUCTION_FALLBACK_API_BASE} にフォールバックする（本番の挙動は変えない）。
 * - それ以外（`next dev`・`node --test` 等）: 本番へは接続せず、
 *   {@link BackendApiBaseNotConfiguredError} を投げる。
 *
 * katadzuke-api.ts の `apiBase()` は対象外（未設定なら本番ビルドでも例外にする別方針のため）。
 *
 * `process.env.API_URL` / `process.env.NEXT_PUBLIC_API_URL` / `process.env.NODE_ENV` は必ずこの
 * リテラルの形で参照すること。Next はこの形の参照だけをビルド時に値へ置き換えるため、分割代入
 * （`const { NODE_ENV } = process.env`）や動的キー（`process.env[key]`）にすると、ブラウザ側に
 * バンドルされたコードでは常に未設定になる。
 *
 * このモジュールは Node の型除去（type stripping）で `backend-api-base.test.mts` から
 * 直接 import されるため、enum・namespace・コンストラクタ引数プロパティ（型除去の対象外の
 * 構文）は使わず、import も持たない（依存ゼロ）。
 */

/**
 * 本番ビルドで接続先の環境変数が読めなかったときだけ使う本番 API（開発時はここへ落とさない）。
 *
 * Vercel の Environment Variables を Sensitive 扱いにすると `NEXT_PUBLIC_*` が
 * クライアントバンドルに inline されない既知制約があり、env var だけに頼ると
 * 本番でフロントが backend に到達できなくなる。確実性のため本番 Render URL を
 * フォールバックとして埋め込む。
 *
 * Railway → Render 移行履歴:
 *   旧: https://backend-production-e4f0d.up.railway.app/api/v1 (deploy 不安定で廃止)
 *   現: https://sokuri-backend.onrender.com/api/v1
 *
 * 2026-09-25 時点の Vercel は NEXT_PUBLIC_API_URL を Production・Preview に設定済みで、
 * このフォールバックは実際には使われていない（未設定になった場合の保険としてのみ残す）。
 */
export const PRODUCTION_FALLBACK_API_BASE = "https://sokuri-backend.onrender.com/api/v1";

/** {@link resolveBackendApiBase} に渡す候補 1 件（環境変数名と値の組）。 */
export interface BackendApiBaseCandidate {
  readonly envVarName: string;
  readonly value: string | undefined;
}

/** 本番ビルド以外で、バックエンド API の接続先が未設定のまま解決しようとしたときに投げる。 */
export class BackendApiBaseNotConfiguredError extends Error {
  constructor(envVarNames: readonly string[]) {
    super(
      `バックエンド API の接続先（${envVarNames.join(" / ")}）が未設定です。開発時は本番 API へ接続しません。` +
        "web/.env.local に NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1 を設定してください" +
        "（web/.env.example・docs/ops/e2e.md）。",
    );
    this.name = "BackendApiBaseNotConfiguredError";
  }
}

/**
 * バックエンド API の接続先を解決する純関数（環境変数を直接読まない。テストから呼びやすくするため）。
 *
 * @param candidates 優先順位順の候補列（先頭が最優先）
 * @param nodeEnv 呼び出し側から渡す `process.env.NODE_ENV` の値
 * @returns 解決できた接続先（末尾スラッシュなし）
 * @throws {BackendApiBaseNotConfiguredError} 候補が全て未設定で、かつ本番ビルドでもない場合
 */
export function resolveBackendApiBase(
  candidates: readonly BackendApiBaseCandidate[],
  nodeEnv: string | undefined,
): string {
  for (const candidate of candidates) {
    const trimmed = candidate.value?.trim();
    if (trimmed) {
      // 末尾スラッシュ（1個・複数どちらも）を正規化する。動いている設定の結果は変わらず、
      // 壊れた設定（末尾スラッシュ付きの入力等）だけが直る。
      return trimmed.replace(/\/+$/, "");
    }
  }
  // 完全一致（Next は next build・next start で常に小文字の "production" を設定する。
  // 表記ゆれを本番扱いにすると開発時に本番へ落ちうるので緩めない）。
  if (nodeEnv === "production") {
    return PRODUCTION_FALLBACK_API_BASE;
  }
  const error = new BackendApiBaseNotConfiguredError(candidates.map((c) => c.envVarName));
  // 呼び出し側はこの例外を握りつぶす（auth.ts の backendLogin は ServerUnavailableError に、
  // LINE 交換は { ok: false } に置き換える）ため、ここで残さないと開発者が原因に気付けない。
  console.error(`[backend-api-base] ${error.message}`);
  throw error;
}

/**
 * バックエンド API の接続先（サーバー専用: NextAuth の authorize() や Route Handler から使う）。
 * API_URL を NEXT_PUBLIC_API_URL より優先する。
 */
export function serverBackendApiBase(): string {
  return resolveBackendApiBase(
    [
      { envVarName: "API_URL", value: process.env.API_URL },
      { envVarName: "NEXT_PUBLIC_API_URL", value: process.env.NEXT_PUBLIC_API_URL },
    ],
    process.env.NODE_ENV,
  );
}

/**
 * バックエンド API の接続先（ブラウザでも動くモジュール向け）。
 * ブラウザに届くのはビルド時に埋め込まれる `NEXT_PUBLIC_*` だけなので、サーバー専用の `API_URL` は見ない。
 */
export function publicBackendApiBase(): string {
  return resolveBackendApiBase(
    [{ envVarName: "NEXT_PUBLIC_API_URL", value: process.env.NEXT_PUBLIC_API_URL }],
    process.env.NODE_ENV,
  );
}
