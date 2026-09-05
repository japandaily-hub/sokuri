/**
 * E2E 共通の定数。
 *
 * テスト口座は backend/seed_local_e2e.py の ACCOUNTS と 1:1 で対応させること
 * （片方だけ変えるとシード済み DB に対して全テストが落ちる）。
 */

/** フロントの起点。playwright.config.ts の baseURL と同一値。 */
export const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3100";

/** バックエンド API の起点（末尾スラッシュなし）。 */
export const API_URL = (process.env.E2E_API_URL ?? "http://localhost:8000/api/v1").replace(/\/+$/, "");

/** バックエンドのオリジン（presign が返す相対 upload_url の解決に使う）。 */
export const API_ORIGIN = new URL(API_URL).origin;

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
