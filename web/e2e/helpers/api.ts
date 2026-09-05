/**
 * バックエンド API の薄いクライアント（E2E の前提データ作成 / ID 引き当て用）。
 *
 * 画面に依存しない前提づくりはすべてここを経由する。web/src/lib/katadzuke-api.ts は
 * "use client" 側の依存（next-auth 等）を持つため import せず、E2E で使う分だけ
 * 最小の型を再定義している（型が食い違ったらバックエンドが正）。
 */
import fs from "node:fs";
import path from "node:path";
import { APIRequestContext, APIResponse, request as playwrightRequest } from "@playwright/test";

import { ACCOUNTS, API_ORIGIN, API_URL, Account, SUPPORTED_PREFECTURE } from "./env";

export type CaseStatus = "draft" | "open" | "bidding" | "closed" | "cancelled";
export type TransactionStatus = "pending" | "visiting" | "completed" | "cancelled";
export type BidStatus = "pending" | "selected" | "rejected" | "withdrawn";

export interface BidSummary {
  id: string;
  amount: number;
  status: BidStatus;
  operator: { id: string; company_name: string } | null;
}

export interface CaseSummary {
  id: string;
  status: CaseStatus;
  purpose: string;
  prefecture: string;
  city: string;
}

export interface CaseDetail extends CaseSummary {
  bids: BidSummary[];
}

export interface TransactionSummary {
  id: string;
  case_id: string;
  status: TransactionStatus;
  unread_count: number;
  initial_amount: number;
  final_amount: number | null;
  visit_date: string | null;
  has_pending_reduction?: boolean;
}

export interface TransactionDetail extends TransactionSummary {
  reductions: { id: string; status: string; requested_amount: number }[];
}

/** 業者ログインのレスポンス。 */
export interface OperatorSession {
  token: string;
  operatorId: string;
}

const PHOTO_PATH = path.resolve(__dirname, "..", "..", "..", "test-room.jpg");

/** レスポンスを検査して JSON を返す。想定外ステータスは本文つきで即座に失敗させる。 */
async function expectJson<T>(res: APIResponse, ...codes: number[]): Promise<T> {
  if (!codes.includes(res.status())) {
    const body = await res.text().catch(() => "<body 読み取り不可>");
    throw new Error(
      `API ${res.url()} -> ${res.status()} ${res.statusText()} (期待 ${codes.join("/")}): ${body.slice(0, 500)}`,
    );
  }
  const text = await res.text();
  return (text ? JSON.parse(text) : {}) as T;
}

/** E2E 用 API クライアント。`Api.create()` で生成し、`dispose()` で後片付けする。 */
export class Api {
  private constructor(private readonly ctx: APIRequestContext) {}

  static async create(): Promise<Api> {
    return new Api(await playwrightRequest.newContext({ timeout: 60_000 }));
  }

  async dispose(): Promise<void> {
    await this.ctx.dispose();
  }

  /** 生のレスポンスが欲しい場合（409 等のステータス自体を検証するテスト）に使う。 */
  raw(): APIRequestContext {
    return this.ctx;
  }

  private headers(token?: string): Record<string, string> {
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  // ---- 認証 ---------------------------------------------------------------

  async loginUser(account: Account): Promise<string> {
    const res = await this.ctx.post(`${API_URL}/auth/login`, {
      data: { email: account.email, password: account.password },
    });
    const data = await expectJson<{ access_token: string }>(res, 200);
    return data.access_token;
  }

  async loginOperator(account: Account): Promise<OperatorSession> {
    const res = await this.ctx.post(`${API_URL}/auth/operator/login`, {
      data: { email: account.email, password: account.password },
    });
    const data = await expectJson<{ access_token: string; operator: { id: string } }>(res, 200);
    return { token: data.access_token, operatorId: data.operator.id };
  }

  // ---- 案件 ---------------------------------------------------------------

  async listCases(token: string): Promise<CaseSummary[]> {
    const res = await this.ctx.get(`${API_URL}/cases`, { headers: this.headers(token) });
    return expectJson<CaseSummary[]>(res, 200);
  }

  async getCase(caseId: string, token: string): Promise<CaseDetail> {
    // GET /cases/{id} は入札を含まないため /cases/{id}/bids を合成して返す（依頼者トークン向け）。
    const res = await this.ctx.get(`${API_URL}/cases/${encodeURIComponent(caseId)}`, { headers: this.headers(token) });
    const detail = await expectJson<CaseDetail>(res, 200);
    const bidsRes = await this.ctx.get(`${API_URL}/cases/${encodeURIComponent(caseId)}/bids`, { headers: this.headers(token) });
    const bids = bidsRes.status() === 200 ? await expectJson<BidSummary[]>(bidsRes, 200) : [];
    return { ...detail, bids: Array.isArray(bids) ? bids : [] };
  }

  /** 写真を1枚アップロードして storage_key を返す（presign → PUT）。 */
  private async uploadPhoto(token: string): Promise<string> {
    const pre = await expectJson<{ upload_url: string; storage_key: string }>(
      await this.ctx.post(`${API_URL}/upload/presign`, {
        data: { filename: "room.jpg", content_type: "image/jpeg" },
        headers: this.headers(token),
      }),
      200,
    );
    const put = await this.ctx.put(`${API_ORIGIN}${pre.upload_url}`, {
      data: fs.readFileSync(PHOTO_PATH),
      headers: { ...this.headers(token), "Content-Type": "image/jpeg" },
    });
    await expectJson(put, 200, 204);
    return pre.storage_key;
  }

  /**
   * 案件を1件作成する。**AI解析を伴い IP軸/アカウント軸ともに時間あたり上限
   * （既定 10件/時）があるため、既存案件を再利用できない場合の最後の手段として使うこと。**
   */
  async createCase(token: string, items: string[] = ["ソファ", "本棚"]): Promise<CaseSummary> {
    const photos = await Promise.all(items.map(() => this.uploadPhoto(token)));
    const res = await this.ctx.post(`${API_URL}/cases`, {
      headers: this.headers(token),
      data: {
        purpose: "引っ越し",
        prefecture: SUPPORTED_PREFECTURE,
        city: "世田谷区",
        address_detail: "1-2-3 E2Eハイツ 201",
        housing_type: "マンション",
        floor_plan: "2LDK",
        floor_number: 2,
        has_elevator: true,
        items: items.map((name, i) => ({
          name,
          sort_order: i,
          photos: [{ storage_key: photos[i], sort_order: 0 }],
        })),
      },
    });
    return expectJson<CaseSummary>(res, 201);
  }

  // ---- 入札・成約 ---------------------------------------------------------

  async createBid(caseId: string, amount: number, message: string, operatorToken: string): Promise<BidSummary> {
    const res = await this.ctx.post(`${API_URL}/cases/${encodeURIComponent(caseId)}/bids`, {
      headers: this.headers(operatorToken),
      data: { amount, message },
    });
    return expectJson<BidSummary>(res, 201);
  }

  async selectBid(caseId: string, bidId: string, sellerToken: string): Promise<TransactionSummary> {
    const res = await this.ctx.post(
      `${API_URL}/cases/${encodeURIComponent(caseId)}/bids/${encodeURIComponent(bidId)}/select`,
      { headers: this.headers(sellerToken) },
    );
    return expectJson<TransactionSummary>(res, 201);
  }

  // ---- 取引 ---------------------------------------------------------------

  async listTransactions(token: string): Promise<TransactionSummary[]> {
    const res = await this.ctx.get(`${API_URL}/transactions`, { headers: this.headers(token) });
    return expectJson<TransactionSummary[]>(res, 200);
  }

  async getTransaction(transactionId: string, token: string): Promise<TransactionDetail> {
    const res = await this.ctx.get(`${API_URL}/transactions/${encodeURIComponent(transactionId)}`, {
      headers: this.headers(token),
    });
    return expectJson<TransactionDetail>(res, 200);
  }

  /** メッセージ送信。ステータス自体を検証したいテスト向けに生のレスポンスを返す。 */
  sendMessageRaw(transactionId: string, body: string, token: string): Promise<APIResponse> {
    return this.ctx.post(`${API_URL}/transactions/${encodeURIComponent(transactionId)}/messages`, {
      headers: this.headers(token),
      data: { body },
    });
  }

  async sendMessage(transactionId: string, body: string, token: string): Promise<{ id: string }> {
    return expectJson<{ id: string }>(await this.sendMessageRaw(transactionId, body, token), 201, 200);
  }

  async proposeSchedule(transactionId: string, slots: string[], operatorToken: string): Promise<{ id: string }> {
    const res = await this.ctx.post(
      `${API_URL}/transactions/${encodeURIComponent(transactionId)}/schedule/propose`,
      { headers: this.headers(operatorToken), data: { slots } },
    );
    return expectJson<{ id: string }>(res, 201, 200);
  }

  async createReduction(
    transactionId: string,
    payload: { requested_amount: number; reason: string },
    operatorToken: string,
  ): Promise<{ id: string; status: string }> {
    const res = await this.ctx.post(`${API_URL}/transactions/${encodeURIComponent(transactionId)}/reduction`, {
      headers: this.headers(operatorToken),
      data: payload,
    });
    return expectJson<{ id: string; status: string }>(res, 201, 200);
  }

  // ---- 運営 ---------------------------------------------------------------

  /** 運営による取引の強制終了（＝キャンセル）。 */
  async adminCancelTransaction(transactionId: string, reason: string, adminToken: string): Promise<void> {
    const res = await this.ctx.patch(`${API_URL}/admin/transactions/${encodeURIComponent(transactionId)}/cancel`, {
      headers: this.headers(adminToken),
      data: { reason },
    });
    await expectJson(res, 200);
  }

  // ---- 公開フォーム -------------------------------------------------------

  async submitContact(payload: { name: string; email: string; category: string; message: string }): Promise<void> {
    const res = await this.ctx.post(`${API_URL}/contact`, { data: payload });
    await expectJson(res, 200, 201, 202);
  }

  /** /business の事前申込（運営が /admin/operator-applications で審査する対象）。 */
  async submitOperatorApplication(payload: {
    company_name: string;
    email: string;
    license_number: string;
  }): Promise<{ application_id: string }> {
    const res = await this.ctx.post(`${API_URL}/operator-applications`, {
      data: {
        company_name: payload.company_name,
        representative_name: "検証 太郎",
        registered_address: "東京都千代田区1-1-1",
        contact_name: "検証 花子",
        email: payload.email,
        phone: "03-1234-5678",
        business_type: "corp",
        service_area: "東京都",
        categories: "家具・家電",
        message: "E2E 自動テストからの申込です。",
        license_number: payload.license_number,
        invoice_number: "T1234567890123",
        bank_account: {
          bank_name: "テスト銀行",
          branch_name: "本店",
          account_type: "ordinary",
          account_number: "1234567",
          account_holder: "ケンシヨウ",
        },
        agreed: true,
      },
    });
    return expectJson<{ application_id: string }>(res, 200, 201, 202);
  }
}

/** 5口座ぶんのトークンをまとめて取得する（各 spec の beforeAll から使う）。 */
export async function loginAll(api: Api): Promise<{
  admin: string;
  seller: string;
  vendor: OperatorSession;
}> {
  const [admin, seller, vendor] = await Promise.all([
    api.loginUser(ACCOUNTS.admin),
    api.loginUser(ACCOUNTS.seller),
    api.loginOperator(ACCOUNTS.vendor),
  ]);
  return { admin, seller, vendor };
}
