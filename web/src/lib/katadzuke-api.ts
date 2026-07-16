/**
 * カタヅケ API クライアント — backend schemas_katadzuke.py と 1:1 対応。
 * 既存の api.ts（旧版流用分）には手を入れず分離する。
 *
 * 認証が必要な関数は token（backend JWT / session.accessToken）を受け取る。
 */

// ---------------------------------------------------------------------------
// 型定義
// ---------------------------------------------------------------------------

export type CaseStatus = "draft" | "open" | "bidding" | "closed" | "cancelled";
export type BidStatus = "pending" | "selected" | "rejected";
export type TransactionStatus = "pending" | "visiting" | "completed" | "cancelled";
export type ReductionStatus = "pending" | "approved" | "rejected";

export interface UserOut {
  id: string;
  email: string;
  name: string | null;
  role: "user" | "admin";
}

export interface OperatorOut {
  id: string;
  company_name: string;
  contact_email: string;
  license_number: string | null;
  verified_at: string | null;
  vendor_status: string;
  rating: number | null;
  is_suspended: boolean;
  created_at: string;
}

export interface OperatorPublic {
  id: string;
  company_name: string;
  rating: number | null;
  verified_at: string | null;
}

export interface AuthTokenResponse {
  access_token: string;
  token_type: string;
  account_type: "user" | "operator";
  user: UserOut | null;
  operator: OperatorOut | null;
}

export interface PresignResponse {
  storage_key: string;
  upload_url: string;
  public_url: string;
}

export interface CasePhoto {
  id: string;
  url: string | null;
  sort_order: number;
}

export interface CaseCreatePayload {
  purpose: string;
  prefecture: string;
  city: string;
  address_detail?: string | null;
  housing_type?: string | null;
  floor_plan?: string | null;
  floor_number?: number | null;
  has_elevator?: boolean | null;
  photos: { storage_key: string; sort_order: number }[];
}

/** ユーザー向け案件（住所詳細あり） */
export interface CaseOut {
  id: string;
  status: CaseStatus;
  purpose: string;
  prefecture: string;
  city: string;
  address_detail: string | null;
  housing_type: string | null;
  floor_plan: string | null;
  floor_number: number | null;
  has_elevator: boolean | null;
  ai_summary: string | null;
  created_at: string;
  photos: CasePhoto[];
  bid_count: number;
}

/** 業者向け案件（住所詳細マスク） */
export interface CaseMasked {
  id: string;
  status: CaseStatus;
  purpose: string;
  prefecture: string;
  city: string;
  housing_type: string | null;
  floor_plan: string | null;
  floor_number: number | null;
  has_elevator: boolean | null;
  ai_summary: string | null;
  created_at: string;
  photos: CasePhoto[];
  bid_count: number;
  my_bid: BidOut | null;
  /**
   * 現在の最高入札額（バックエンド並行実装中のため optional）。
   * 未対応の間は undefined/null のまま届く想定で、フロントは「—」等にフォールバックする。
   */
  top_bid_amount?: number | null;
}

export interface BidOut {
  id: string;
  case_id: string;
  amount: number;
  message: string | null;
  status: BidStatus;
  created_at: string;
  operator: OperatorPublic | null;
  /** selected の場合のみ: 成約 ID（落札管理への導線） */
  transaction_id: string | null;
}

export interface TransactionListItem {
  id: string;
  case_id: string;
  status: TransactionStatus;
  initial_amount: number;
  final_amount: number | null;
  visit_date: string | null;
  created_at: string;
  purpose: string;
  prefecture: string;
  city: string;
  company_name: string | null;
  has_pending_reduction: boolean;
  /** ユーザーが既にこの取引にレビュー（reviewer_type==="user"）を投稿済みか。 */
  has_review: boolean;
}

export interface TransactionOut {
  id: string;
  case_id: string;
  bid_id: string;
  initial_amount: number;
  final_amount: number | null;
  fee_amount: number;
  /** "YYYY-MM-DD" 形式（date型）。ISO日時ではないため new Date() でのUTC解釈は不可（JST日付がズレる）。 */
  visit_date: string | null;
  /** 例: "10:00-12:00"。confirmSchedule で設定される訪問時間帯。未確定時は null。 */
  visit_time_slot: string | null;
  status: TransactionStatus;
  created_at: string;
}

export interface ReductionOut {
  id: string;
  transaction_id: string;
  original_amount: number;
  requested_amount: number;
  reason: string;
  status: ReductionStatus;
  created_at: string;
}

export interface ReviewOut {
  id: string;
  transaction_id: string;
  reviewer_type: "user" | "operator";
  rating: number;
  comment: string | null;
  created_at: string;
}

export interface TransactionDetail extends TransactionOut {
  case: CaseMasked | null;
  operator: OperatorPublic | null;
  /** 落札確定済みの当事者にのみ含まれる（バックエンド制御） */
  address: { prefecture: string; city: string; address_detail: string | null } | null;
  contact_email: string | null;
  /** limited業者が落札した場合、admin承認待ちで住所非開示中 */
  awaiting_approval: boolean;
  reduction_requests: ReductionOut[];
  reviews: ReviewOut[];
  /** 相手が送信し、自分がまだ既読にしていないメッセージ数。 */
  unread_count: number;
}

// ---------------------------------------------------------------------------
// チャット
// ---------------------------------------------------------------------------

export type MessageSenderType = "user" | "operator" | "system";
export type MessageKind = "text" | "schedule_proposal" | "schedule_confirmed" | "system";

export interface MessageOut {
  id: string;
  sender_type: MessageSenderType;
  body: string;
  kind: MessageKind;
  meta: Record<string, unknown> | null;
  created_at: string;
  /** 自分が送信したメッセージかどうか（サーバー側で actor から判定済み）。 */
  mine: boolean;
}

/** チャットメッセージ一覧。after 指定時はそれ以降の差分のみ返る。 */
export function listMessages(
  transactionId: string,
  token: string,
  after?: string,
): Promise<MessageOut[]> {
  const query = after ? `?after=${encodeURIComponent(after)}` : "";
  return request(`/transactions/${transactionId}/messages${query}`, { token });
}

export function sendMessage(
  transactionId: string,
  body: string,
  token: string,
): Promise<MessageOut> {
  return request(`/transactions/${transactionId}/messages`, {
    method: "POST",
    body: JSON.stringify({ body }),
    token,
  });
}

export function markMessagesRead(
  transactionId: string,
  token: string,
): Promise<TransactionOut> {
  return request(`/transactions/${transactionId}/messages/read`, {
    method: "POST",
    token,
  });
}

// ---------------------------------------------------------------------------
// 日程調整
// ---------------------------------------------------------------------------

/** 訪問日程の候補提示（落札業者のみ）。 */
export function proposeSchedule(
  transactionId: string,
  slots: string[],
  token: string,
): Promise<MessageOut> {
  return request(`/transactions/${transactionId}/schedule/propose`, {
    method: "POST",
    body: JSON.stringify({ slots }),
    token,
  });
}

/** 訪問日程の確定（所有ユーザーのみ）。 */
export function confirmSchedule(
  transactionId: string,
  payload: { visit_date: string; visit_time_slot: string; note?: string },
  token: string,
): Promise<TransactionOut> {
  return request(`/transactions/${transactionId}/schedule/confirm`, {
    method: "POST",
    body: JSON.stringify(payload),
    token,
  });
}

// ---------------------------------------------------------------------------
// 業者プロフィール
// ---------------------------------------------------------------------------

export interface OperatorProfile {
  operator_id: string;
  company_name: string;
  license_number: string | null;
  verified_at: string | null;
  vendor_status: string;
  rating: number | null;
  areas: string[];
  categories: string[];
  strong_categories: string[];
  staff_count: number | null;
  business_hours: string | null;
  intro_message: string | null;
  is_public: boolean;
  show_stats: boolean;
  show_reviews: boolean;
  show_message: boolean;
  accept_unsellable: boolean;
}

export interface OperatorProfileUpdatePayload {
  areas: string[];
  categories: string[];
  strong_categories: string[];
  staff_count: number | null;
  business_hours: string | null;
  intro_message: string | null;
  is_public: boolean;
  show_stats: boolean;
  show_reviews: boolean;
  show_message: boolean;
  accept_unsellable: boolean;
}

export function getOperatorProfile(token: string): Promise<OperatorProfile> {
  return request("/operator/profile", { token });
}

export function updateOperatorProfile(
  payload: OperatorProfileUpdatePayload,
  token: string,
): Promise<OperatorProfile> {
  return request("/operator/profile", {
    method: "PUT",
    body: JSON.stringify(payload),
    token,
  });
}

/** 公開プロフィールのレビュー（バックエンド PublicReviewOut。内部IDは含まれない）。 */
export interface PublicReview {
  id: string;
  rating: number;
  comment: string | null;
  created_at: string;
}

export interface OperatorPublicProfile {
  operator_id: string;
  company_name: string;
  verified_at: string | null;
  areas: string[];
  categories: string[];
  strong_categories: string[];
  staff_count: number | null;
  business_hours: string | null;
  intro_message: string | null;
  accept_unsellable: boolean;
  rating: number | null;
  reviews: PublicReview[] | null;
}

export function getVendorPublicProfile(operatorId: string): Promise<OperatorPublicProfile> {
  return request(`/vendors/${operatorId}`);
}

export interface InviteOut {
  id: string;
  code: string;
  email: string | null;
  used_at: string | null;
  operator_id: string | null;
  lot_name: string | null;
  created_at: string;
}

export interface InviteBulkCreateResponse {
  codes: string[];
  lot_name: string | null;
  count: number;
}

// ---------------------------------------------------------------------------
// fetch 基盤
// ---------------------------------------------------------------------------

export class KdzApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "KdzApiError";
  }
}

/** fetch() 自体が失敗した場合（backend未起動・オフライン等）に投げる。HTTPエラー（KdzApiError）とは区別する。 */
export class KdzNetworkError extends Error {
  constructor(
    public readonly cause?: unknown,
    message: string = "ネットワークに接続できませんでした",
  ) {
    super(message);
    this.name = "KdzNetworkError";
  }
}

export function apiBase(): string {
  const url = process.env.NEXT_PUBLIC_API_URL;
  if (!url) throw new Error("NEXT_PUBLIC_API_URL が設定されていません。");
  return url.replace(/\/$/, "");
}

async function request<T>(
  path: string,
  init?: RequestInit & { token?: string },
): Promise<T> {
  const { token, ...rest } = init ?? {};
  let res: Response;
  try {
    res = await fetch(`${apiBase()}${path}`, {
      ...rest,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(rest.headers ?? {}),
      },
    });
  } catch (e) {
    if (e instanceof KdzApiError) throw e;
    throw new KdzNetworkError(e);
  }
  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      /* JSON でないレスポンスは無視 */
    }
    throw new KdzApiError(res.status, message);
  }
  if (res.status === 204) return undefined as T;
  try {
    return (await res.json()) as T;
  } catch (e) {
    if (e instanceof KdzApiError) throw e;
    throw new KdzNetworkError(e);
  }
}

// ---------------------------------------------------------------------------
// 認証
// ---------------------------------------------------------------------------

export function signupUser(payload: {
  email: string;
  password: string;
  name?: string;
}): Promise<AuthTokenResponse> {
  return request("/auth/signup", { method: "POST", body: JSON.stringify(payload) });
}

export function signupOperator(payload: {
  invite_code?: string | null;
  company_name: string;
  email: string;
  password: string;
  license_number?: string;
  agreed: boolean;
}): Promise<AuthTokenResponse> {
  return request("/auth/operator/signup", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

// ---------------------------------------------------------------------------
// 業者登録申し込み（/business LP）
// ---------------------------------------------------------------------------

export interface BankAccountInput {
  bank_name: string;
  branch_name: string;
  account_type: "ordinary" | "checking";
  account_number: string;
  account_holder: string;
}

export function submitOperatorApplication(payload: {
  company_name: string;
  representative_name: string;
  registered_address: string;
  contact_name: string;
  email: string;
  phone: string;
  business_type: "corp" | "sole";
  service_area: string;
  categories?: string;
  message?: string;
  license_number: string;
  invoice_number?: string;
  bank_account: BankAccountInput;
  agreed: boolean;
}): Promise<{ application_id: string; status: string }> {
  return request("/operator-applications", { method: "POST", body: JSON.stringify(payload) });
}

// ---------------------------------------------------------------------------
// 写真アップロード
// ---------------------------------------------------------------------------

export async function uploadCasePhoto(
  file: File,
  token: string,
): Promise<PresignResponse> {
  const contentType = (
    ["image/jpeg", "image/png", "image/webp"].includes(file.type)
      ? file.type
      : "image/jpeg"
  ) as "image/jpeg" | "image/png" | "image/webp";

  const presign = await request<PresignResponse>("/upload/presign", {
    method: "POST",
    body: JSON.stringify({ filename: file.name, content_type: contentType }),
    token,
  });

  let res: Response;
  try {
    res = await fetch(`${apiBase()}${presign.upload_url}`, {
      method: "PUT",
      headers: { "Content-Type": contentType },
      body: file,
    });
  } catch (e) {
    if (e instanceof KdzApiError) throw e;
    throw new KdzNetworkError(e);
  }
  if (!res.ok) throw new KdzApiError(res.status, "写真のアップロードに失敗しました");
  return presign;
}

/** 相対 public_url（/api/v1/files/...）を絶対 URL にする。 */
export function photoSrc(url: string | null): string {
  if (!url) return "";
  if (url.startsWith("http")) return url;
  return `${apiBase().replace(/\/api\/v1$/, "")}${url}`;
}

// ---------------------------------------------------------------------------
// 案件
// ---------------------------------------------------------------------------

export function createCase(
  payload: CaseCreatePayload,
  token: string,
): Promise<CaseOut> {
  return request("/cases", { method: "POST", body: JSON.stringify(payload), token });
}

export function listMyCases(token: string): Promise<CaseOut[]> {
  return request("/cases", { token });
}

export function listOpenCases(token: string): Promise<CaseMasked[]> {
  return request("/cases", { token });
}

export function getCase(caseId: string, token: string): Promise<CaseOut> {
  return request(`/cases/${caseId}`, { token });
}

export function getCaseMasked(caseId: string, token: string): Promise<CaseMasked> {
  return request(`/cases/${caseId}`, { token });
}

// ---------------------------------------------------------------------------
// 入札
// ---------------------------------------------------------------------------

export function listBids(caseId: string, token: string): Promise<BidOut[]> {
  return request(`/cases/${caseId}/bids`, { token });
}

export function createBid(
  caseId: string,
  payload: { amount: number; message?: string },
  token: string,
): Promise<BidOut> {
  return request(`/cases/${caseId}/bids`, {
    method: "POST",
    body: JSON.stringify(payload),
    token,
  });
}

export function selectBid(
  caseId: string,
  bidId: string,
  token: string,
): Promise<TransactionOut> {
  return request(`/cases/${caseId}/bids/${bidId}/select`, { method: "POST", token });
}

// ---------------------------------------------------------------------------
// 成約
// ---------------------------------------------------------------------------

export function listTransactions(token: string): Promise<TransactionListItem[]> {
  return request("/transactions", { token });
}

export function getTransaction(
  transactionId: string,
  token: string,
): Promise<TransactionDetail> {
  return request(`/transactions/${transactionId}`, { token });
}

export function completeTransaction(
  transactionId: string,
  token: string,
): Promise<TransactionOut> {
  return request(`/transactions/${transactionId}/complete`, { method: "POST", token });
}

export function cancelTransaction(
  transactionId: string,
  reason: string | null,
  token: string,
): Promise<TransactionOut> {
  return request(`/transactions/${transactionId}/cancel`, {
    method: "POST",
    body: JSON.stringify({ reason }),
    token,
  });
}

// ---------------------------------------------------------------------------
// 減額申請
// ---------------------------------------------------------------------------

export function createReduction(
  transactionId: string,
  payload: { requested_amount: number; reason: string },
  token: string,
): Promise<ReductionOut> {
  return request(`/transactions/${transactionId}/reduction`, {
    method: "POST",
    body: JSON.stringify(payload),
    token,
  });
}

export function decideReduction(
  transactionId: string,
  reductionId: string,
  action: "approve" | "reject",
  token: string,
): Promise<ReductionOut> {
  return request(`/transactions/${transactionId}/reduction/${reductionId}`, {
    method: "PATCH",
    body: JSON.stringify({ action }),
    token,
  });
}

// ---------------------------------------------------------------------------
// レビュー
// ---------------------------------------------------------------------------

export function createReview(
  payload: { transaction_id: string; rating: number; comment?: string },
  token: string,
): Promise<ReviewOut> {
  return request("/reviews", { method: "POST", body: JSON.stringify(payload), token });
}

// ---------------------------------------------------------------------------
// 管理
// ---------------------------------------------------------------------------

export function adminCreateInvite(
  email: string | null,
  token: string,
): Promise<InviteOut> {
  return request("/admin/invites", {
    method: "POST",
    body: JSON.stringify({ email }),
    token,
  });
}

export function adminBulkCreateInvites(
  count: number,
  lotName: string | undefined,
  token: string,
): Promise<InviteBulkCreateResponse> {
  return request("/admin/invites/bulk", {
    method: "POST",
    body: JSON.stringify({ count, lot_name: lotName ?? null }),
    token,
  });
}

export function adminListInvites(token: string): Promise<InviteOut[]> {
  return request("/admin/invites", { token });
}

export function adminListOperators(token: string): Promise<OperatorOut[]> {
  return request("/admin/operators", { token });
}

export function adminVerifyOperator(
  operatorId: string,
  verified: boolean,
  token: string,
): Promise<OperatorOut> {
  return request(`/admin/operators/${operatorId}/verify`, {
    method: "PATCH",
    body: JSON.stringify({ verified }),
    token,
  });
}

export interface CellDensityRow {
  prefecture: string;
  purpose: string;
  open_cases: number;
  active_suppliers: number;
  demand_per_supplier: number;
  status: "dense" | "normal";
}

export function adminGetCellDensity(token: string): Promise<CellDensityRow[]> {
  return request("/admin/cell-density", { token });
}

// ---------------------------------------------------------------------------
// 表示ユーティリティ
// ---------------------------------------------------------------------------

export function formatYen(amount: number | null | undefined): string {
  if (amount == null) return "—";
  return `${amount.toLocaleString("ja-JP")}円`;
}

/** 汎用フォールバック文言（想定外エラー・非Error値の最終防波堤）。 */
const GENERIC_FALLBACK_MESSAGE = "処理に失敗しました。時間をおいて再度お試しください。";
/** ネットワーク到達不可時の固定文言。fallback より優先して表示する。 */
const NETWORK_ERROR_MESSAGE =
  "通信に失敗しました。電波状況を確認し、しばらくしてからもう一度お試しください。";

/**
 * catch(err) で受け取った例外を、ユーザーに安全に表示できる文言へ変換する。
 * 生の Error#message（fetch失敗時の "Failed to fetch" 等）を画面にそのまま出さないための唯一の窓口。
 *
 * 優先順位:
 * 1. KdzNetworkError → 固定のネットワーク文言（fallback より優先）
 * 2. KdzApiError → backend detail（空文字・HTTP xxx のみのプレースホルダは fallback にフォールバック）
 * 3. その他の Error（想定外） → fallback ?? 汎用文言（生の err.message は表示しない）
 * 4. 非 Error 値 → fallback ?? 汎用文言
 */
export function toDisplayMessage(err: unknown, fallback?: string): string {
  if (err instanceof KdzNetworkError) return NETWORK_ERROR_MESSAGE;
  if (err instanceof KdzApiError) {
    // 5xx はサーバー内部エラー文字列が detail に紛れ込むリスクがあるため画面には出さない。
    if (err.status >= 500) return fallback ?? GENERIC_FALLBACK_MESSAGE;
    const detail = err.message.trim();
    const isPlaceholder = detail === "" || /^HTTP \d+$/.test(detail);
    return isPlaceholder ? (fallback ?? GENERIC_FALLBACK_MESSAGE) : detail;
  }
  return fallback ?? GENERIC_FALLBACK_MESSAGE;
}

export const CASE_STATUS_LABEL: Record<CaseStatus, string> = {
  draft: "下書き",
  open: "入札受付中",
  bidding: "入札あり",
  closed: "業者決定済み",
  cancelled: "キャンセル",
};

export const TXN_STATUS_LABEL: Record<TransactionStatus, string> = {
  pending: "訪問日調整中",
  visiting: "訪問予定",
  completed: "完了",
  cancelled: "キャンセル",
};
