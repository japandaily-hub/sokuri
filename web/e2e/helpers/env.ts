/**
 * E2E 共通の定数。
 *
 * テスト口座は backend/seed_local_e2e.py の ACCOUNTS と 1:1 で対応させること
 * （片方だけ変えるとシード済み DB に対して全テストが落ちる）。
 */

/**
 * フロントの起点。playwright.config.ts の baseURL はこの値を使う。
 * ローカル（localhost / 127.0.0.1 / ::1）以外は、playwright.config.ts の読み込み時をはじめとする
 * 4段の検査（helpers/local-target.ts）で実行前に失敗する（E2E_ALLOW_REMOTE=1 で解除）。
 */
export const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3100";

/**
 * バックエンド API の起点（末尾スラッシュなし）。
 * ローカル以外は BASE_URL と同じく4段の検査（helpers/local-target.ts）で実行前に失敗する。
 */
export const API_URL = (process.env.E2E_API_URL ?? "http://localhost:8000/api/v1").replace(/\/+$/, "");

/**
 * バックエンドのオリジン（presign が返す相対 upload_url の解決に使う）。
 * import の時点では解釈に失敗しても投げない。Node の Invalid URL は入力値をそのまま表示するため、
 * 認証情報を含む値が端末に出うる。不正な E2E_API_URL は、playwright.config.ts の検査が値を出さずに止める。
 */
export const API_ORIGIN = ((): string => {
  try {
    return new URL(API_URL).origin;
  } catch {
    return "null";
  }
})();

export interface Account {
  readonly email: string;
  readonly password: string;
}

/** backend/seed_local_e2e.py が投入するテスト口座。 */
export const ACCOUNTS = {
  /** ADMIN_EMAILS に一致し role=admin。 */
  admin: { email: "e2e-admin@example.com", password: "Admin-Pass-2026" },
  /** 依頼者（案件3件の所有者）。 */
  seller: { email: "seller@example.com", password: "Seller-Pass-2026" },
  /** 業者A（active・許可証提出済み）。 */
  vendor: { email: "vendor@example.com", password: "Vendor-Pass-2026" },
  /** 業者B（active・案件1で業者Aより高値）。 */
  rival: { email: "rival@example.com", password: "Rival-Pass-2026" },
  /** 業者C（招待なし＝審査中）。ログイン失敗を積む 429 テストで使う。 */
  pending: { email: "pending@example.com", password: "Pending-Pass-2026" },
} as const satisfies Record<string, Account>;

/** 出品可能な都県（backend の prefecture Literal と一致させること）。 */
export const SUPPORTED_PREFECTURE = "東京都";

/** 1回の実行で衝突しない一意サフィックスを作る。 */
export function uniqueSuffix(): string {
  return `${Date.now().toString(36)}${Math.floor(Math.random() * 1e4).toString(36)}`;
}
