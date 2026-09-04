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
export type BidStatus = "pending" | "selected" | "rejected" | "withdrawn";
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
  /** 古物商許可証画像を提出済みか（admin一覧のバッジ表示・確認ボタン活性化に使用）。 */
  has_license_image: boolean;
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

/** 商品単位のアルバム（バックエンド並行実装中のため CaseOut/CaseMasked では optional）。 */
export interface CaseItemOut {
  id: string;
  name: string | null;
  sort_order: number;
  ai_detected_name: string | null;
  ai_condition: string | null;
  ai_summary: string | null;
  /** ユーザーが編集した状態（未編集時は null。表示上の実効値は ai_condition にフォールバックする）。 */
  user_condition: string | null;
  /** ユーザーが編集した説明文（未編集時は null。表示上の実効値は ai_summary にフォールバックする）。 */
  user_description: string | null;
  photos: CasePhoto[];
}

/** PUT /cases/{case_id}/items/{item_id} のリクエストボディ。いずれも null で未設定に戻せる。 */
export interface CaseItemUpdatePayload {
  name: string | null;
  user_condition: string | null;
  user_description: string | null;
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
  /** 商品ごとにまとめる場合の内訳。既存の photos（フラット）と併用可（合計20枚まで）。 */
  items?: {
    name?: string;
    sort_order: number;
    photos: { storage_key: string; sort_order: number }[];
  }[];
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
  /** バックエンド並行実装中のため optional。未対応の間は undefined のまま届く想定。 */
  items?: CaseItemOut[];
  item_count?: number;
  photo_count?: number;
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
  /** バックエンド並行実装中のため optional。未対応の間は undefined のまま届く想定。 */
  items?: CaseItemOut[];
  item_count?: number;
  photo_count?: number;
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
  /** 許可証画像の最終アップロード日時。未提出の場合 null。 */
  license_image_uploaded_at: string | null;
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

export interface OperatorLicenseImageUploadResponse {
  uploaded_at: string;
}

/**
 * 業者の古物商許可証画像をアップロードする（multipart/form-data）。
 * request<T>() は Content-Type: application/json を固定注入するため multipart 送信には使えない。
 * uploadCasePhoto と同様に生 fetch でエラーハンドリングを踏襲する。
 * ファイル形式・サイズの事前検証は呼び出し側（operator/profile/page.tsx）で行う。
 */
export async function uploadOperatorLicenseImage(
  file: File,
  token: string,
): Promise<OperatorLicenseImageUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  let res: Response;
  try {
    res = await fetch(`${apiBase()}/operator/license-image`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
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
  return (await res.json()) as OperatorLicenseImageUploadResponse;
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
  /** 運営承認済み（vendor_status === "active"）。公開バッジの根拠。 */
  is_approved: boolean;
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
// ユーザープロフィール
// ---------------------------------------------------------------------------

export type IdentityStatus = "unverified" | "pending" | "approved" | "rejected";

/** GET/PUT /users/me/profile 共通のレスポンス形。 */
export interface UserProfile {
  email: string;
  family_name: string | null;
  given_name: string | null;
  family_name_kana: string | null;
  given_name_kana: string | null;
  phone: string | null;
  residence_area: string | null;
  /** false の場合 LINE専用アカウント（パスワード未設定）。 */
  has_password: boolean;
  line_linked: boolean;
  /** "YYYY-MM-DD"。古物営業法の本人確認・年齢確認に使用。 */
  birth_date: string | null;
  occupation: string | null;
  identity_status: IdentityStatus;
  has_bank_account: boolean;
}

export interface UpdateProfilePayload {
  family_name: string;
  given_name: string;
  family_name_kana?: string | null;
  given_name_kana?: string | null;
  phone?: string | null;
  residence_area?: string | null;
  /** "YYYY-MM-DD" */
  birth_date?: string | null;
  occupation?: string | null;
}

export interface ChangePasswordPayload {
  current_password: string;
  new_password: string;
}

/** access_token はパスワード変更で旧JWTが即時失効するため、必ずセッションへ反映すること。 */
export interface ChangePasswordResponse {
  detail: string;
  access_token: string;
}

export interface DeleteAccountPayload {
  /** has_password === false（LINE専用）のユーザーは省略可。 */
  password?: string | null;
  confirm: boolean;
}

/** 都道府県（47件・北海道〜沖縄の正式表記）。住所フォームの select の単一情報源。 */
export const PREFECTURES = [
  "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
  "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
  "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県", "岐阜県",
  "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県",
  "奈良県", "和歌山県", "鳥取県", "島根県", "岡山県", "広島県", "山口県",
  "徳島県", "香川県", "愛媛県", "高知県", "福岡県", "佐賀県", "長崎県",
  "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
] as const;

/** 職業（プロフィール「職業」select の選択肢）。 */
export const OCCUPATIONS = [
  "会社員", "公務員", "自営業・フリーランス", "経営者・役員",
  "パート・アルバイト", "学生", "主婦・主夫", "無職", "年金受給者", "その他",
] as const;

/** お住まいのエリア（8トークン+日本語ラベル）。residence_area の単一情報源。 */
export const RESIDENCE_AREAS = [
  { id: "tokyo", label: "東京都" },
  { id: "kanagawa", label: "神奈川県" },
  { id: "saitama", label: "埼玉県" },
  { id: "chiba", label: "千葉県" },
  { id: "osaka", label: "大阪府" },
  { id: "aichi", label: "愛知県" },
  { id: "fukuoka", label: "福岡県" },
  { id: "other", label: "その他" },
] as const;

export function getMyProfile(token: string): Promise<UserProfile> {
  return request("/users/me/profile", { token });
}

export function updateMyProfile(
  payload: UpdateProfilePayload,
  token: string,
): Promise<UserProfile> {
  return request("/users/me/profile", {
    method: "PUT",
    body: JSON.stringify(payload),
    token,
  });
}

export function changeMyPassword(
  payload: ChangePasswordPayload,
  token: string,
): Promise<ChangePasswordResponse> {
  return request("/users/me/password", {
    method: "PUT",
    body: JSON.stringify(payload),
    token,
  });
}

export function deleteMyAccount(
  payload: DeleteAccountPayload,
  token: string,
): Promise<{ detail: string }> {
  return request("/users/me", {
    method: "DELETE",
    body: JSON.stringify(payload),
    token,
  });
}

// ---------------------------------------------------------------------------
// 住所（古物営業法の本人確認・成約時開示に使用）
// ---------------------------------------------------------------------------

export interface AddressOut {
  postal_code: string | null;
  prefecture: string | null;
  city: string | null;
  address_line1: string | null;
  address_line2: string | null;
  /** RESIDENCE_AREAS のトークン。住所保存時にバックエンド側で自動同期される。 */
  residence_area: string | null;
}

export interface AddressUpdatePayload {
  /** 7桁（ハイフン可）。 */
  postal_code: string;
  prefecture: string;
  city: string;
  address_line1: string;
  address_line2?: string | null;
}

export function getMyAddress(token: string): Promise<AddressOut> {
  return request("/users/me/address", { token });
}

export function updateMyAddress(
  payload: AddressUpdatePayload,
  token: string,
): Promise<AddressOut> {
  return request("/users/me/address", {
    method: "PUT",
    body: JSON.stringify(payload),
    token,
  });
}

// ---------------------------------------------------------------------------
// 振込口座（買取代金の受取先。業者には非開示）
// ---------------------------------------------------------------------------

export type BankAccountType = "普通" | "当座";

export interface BankAccountOut {
  has_bank_account: boolean;
  bank_name: string | null;
  branch_name: string | null;
  account_type: BankAccountType | null;
  /** 例 "***4567"。マスク済みのため一覧・確認画面にそのまま表示してよい。 */
  account_number_masked: string | null;
  account_holder_kana: string | null;
  updated_at: string | null;
}

export interface BankAccountUpdatePayload {
  bank_name: string;
  branch_name: string;
  account_type: BankAccountType;
  /** 7桁の数字のみ。 */
  account_number: string;
  /** 全角カタカナ。 */
  account_holder_kana: string;
}

export function getMyBankAccount(token: string): Promise<BankAccountOut> {
  return request("/users/me/bank-account", { token });
}

export function updateMyBankAccount(
  payload: BankAccountUpdatePayload,
  token: string,
): Promise<BankAccountOut> {
  return request("/users/me/bank-account", {
    method: "PUT",
    body: JSON.stringify(payload),
    token,
  });
}

export function deleteMyBankAccount(token: string): Promise<void> {
  return request("/users/me/bank-account", { method: "DELETE", token });
}

// ---------------------------------------------------------------------------
// 本人確認（古物営業法対応。1万円以上の買取で住所・氏名・職業・年齢確認が必要）
// ---------------------------------------------------------------------------

/** 書類種別の内部トークン。backend の doc_type と1:1対応する。 */
export type IdentityDocType =
  | "driver_license"
  | "my_number_card"
  | "passport"
  | "residence_card"
  | "health_insurance_card";

export const IDENTITY_STATUS_LABEL: Record<IdentityStatus, string> = {
  unverified: "未提出",
  pending: "審査中",
  approved: "承認済み",
  rejected: "差し戻し",
};

/** 提出フォームの書類種別 select 選択肢（裏面要否・注記を含む）。この配列が唯一の情報源。 */
export const IDENTITY_DOC_TYPES: {
  id: IdentityDocType;
  label: string;
  backRequired: boolean;
  note?: string;
}[] = [
  { id: "driver_license", label: "運転免許証", backRequired: true },
  {
    id: "my_number_card",
    label: "マイナンバーカード",
    backRequired: false,
    note: "裏面（個人番号面）は送らないでください。表面のみご提出ください。",
  },
  { id: "passport", label: "パスポート", backRequired: false },
  { id: "residence_card", label: "在留カード", backRequired: true },
  {
    id: "health_insurance_card",
    label: "健康保険証",
    backRequired: true,
    note: "住所記載がない場合、承認できないことがあります。",
  },
];

export interface IdentityOut {
  status: IdentityStatus;
  document_id: string | null;
  doc_type: IdentityDocType | null;
  submitted_at: string | null;
  reviewed_at: string | null;
  reject_reason: string | null;
  has_back: boolean;
}

export function getMyIdentity(token: string): Promise<IdentityOut> {
  return request("/users/me/identity", { token });
}

/**
 * 本人確認書類を提出する（multipart/form-data）。
 * request<T>() は Content-Type: application/json を固定注入するため使えず、
 * uploadOperatorLicenseImage と同様に生 fetch で送る。
 * 422: 生年月日未登録/18歳未満/裏面不足/非画像、409: 審査中または承認済み、
 * 413/422: サイズ超過、429: リクエスト過多。
 */
export async function uploadIdentityDocument(
  payload: { docType: IdentityDocType; front: File; back?: File | null },
  token: string,
): Promise<IdentityOut> {
  const formData = new FormData();
  formData.append("doc_type", payload.docType);
  formData.append("front", payload.front);
  if (payload.back) formData.append("back", payload.back);

  let res: Response;
  try {
    res = await fetch(`${apiBase()}/users/me/identity-documents`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
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
  return (await res.json()) as IdentityOut;
}

/**
 * 提出済み本人確認書類の画像を取得する（本人のみ・Blob）。
 * <img src> による直参照はAuthorizationヘッダーを付けられないため不可。
 * 呼び出し側で URL.createObjectURL → 表示後 URL.revokeObjectURL すること。
 */
export async function fetchMyIdentityDocumentBlob(
  documentId: string,
  side: "front" | "back",
  token: string,
): Promise<Blob> {
  let res: Response;
  try {
    res = await fetch(
      `${apiBase()}/users/me/identity-documents/${documentId}/file?side=${side}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
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
  return await res.blob();
}

// ---------------------------------------------------------------------------
// 管理: 本人確認書類の審査
// ---------------------------------------------------------------------------

export interface AdminIdentityDocument {
  id: string;
  user_id: string;
  user_email: string;
  user_name: string | null;
  doc_type: IdentityDocType;
  status: IdentityStatus;
  submitted_at: string;
  reviewed_at: string | null;
  reject_reason: string | null;
  has_back: boolean;
}

export function listIdentityDocumentsAdmin(
  status: "pending" | "all",
  token: string,
): Promise<AdminIdentityDocument[]> {
  return request(`/admin/identity-documents?status=${status}`, { token });
}

export async function fetchIdentityDocumentBlobAdmin(
  documentId: string,
  side: "front" | "back",
  token: string,
): Promise<Blob> {
  let res: Response;
  try {
    res = await fetch(
      `${apiBase()}/admin/identity-documents/${documentId}/file?side=${side}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
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
  return await res.blob();
}

export function approveIdentityDocument(
  documentId: string,
  token: string,
): Promise<AdminIdentityDocument> {
  return request(`/admin/identity-documents/${documentId}/approve`, {
    method: "PATCH",
    token,
  });
}

export function rejectIdentityDocument(
  documentId: string,
  rejectReason: string,
  token: string,
): Promise<AdminIdentityDocument> {
  return request(`/admin/identity-documents/${documentId}/reject`, {
    method: "PATCH",
    body: JSON.stringify({ reject_reason: rejectReason }),
    token,
  });
}

// ---------------------------------------------------------------------------
// LINE通知連携（ログイン済みユーザーの後付け連携/解除。ログイン自体はauth.tsのLINE provider）
// ---------------------------------------------------------------------------

export interface ReauthTokenResponse {
  reauth_token: string;
  expires_in: number;
}

/**
 * パスワード再確認トークンを発行する（LINE連携等、機微操作の直前に要求する短命トークン）。
 * 400: パスワード不一致（change_my_password/delete_my_account と同じ規約） /
 * 401: トークン自体が無効（セッション切れ） / 409: has_password===false（LINE専用アカウント）ユーザー。
 */
export function requestLineReauthToken(
  currentPassword: string,
  token: string,
): Promise<ReauthTokenResponse> {
  return request("/users/me/reauth-token", {
    method: "POST",
    body: JSON.stringify({ current_password: currentPassword }),
    token,
  });
}

/**
 * LINE通知連携を解除する。
 * 400: パスワード不一致（change_my_password/delete_my_account と同じ規約） /
 * 401: トークン自体が無効（セッション切れ） / 409: has_password===false（LINE専用アカウント）ユーザー。
 */
export function unlinkLine(currentPassword: string, token: string): Promise<void> {
  return request("/users/me/line-link", {
    method: "DELETE",
    body: JSON.stringify({ current_password: currentPassword }),
    token,
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
    // presign.upload_url はバックエンドが返す絶対パス(/api/v1/upload/{key})で、
    // apiBase() 自体に既に /api/v1 が含まれるため、単純連結すると /api/v1 が
    // 二重になり404になる(本番で実際に再現・確認済みの既存バグ)。
    // 同ファイルの photoSrc() が public_url に対して行っている補正と同じパターンで
    // apiBase() 側の /api/v1 を先に取り除いてから連結する。
    res = await fetch(`${apiBase().replace(/\/api\/v1$/, "")}${presign.upload_url}`, {
      method: "PUT",
      headers: { "Content-Type": contentType, Authorization: `Bearer ${token}` },
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
// 案件の商品・写真編集（case.status が draft/open の間のみ許可。それ以外は409）
// ---------------------------------------------------------------------------

export function updateCaseItem(
  caseId: string,
  itemId: string,
  payload: CaseItemUpdatePayload,
  token: string,
): Promise<CaseItemOut> {
  return request(`/cases/${caseId}/items/${itemId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
    token,
  });
}

export function deleteCaseItem(caseId: string, itemId: string, token: string): Promise<void> {
  return request(`/cases/${caseId}/items/${itemId}`, { method: "DELETE", token });
}

export function deleteCasePhoto(caseId: string, photoId: string, token: string): Promise<void> {
  return request(`/cases/${caseId}/photos/${photoId}`, { method: "DELETE", token });
}

export function addCaseItemPhoto(
  caseId: string,
  itemId: string,
  payload: { storage_key: string; sort_order: number },
  token: string,
): Promise<CasePhoto> {
  return request(`/cases/${caseId}/items/${itemId}/photos`, {
    method: "POST",
    body: JSON.stringify(payload),
    token,
  });
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

/**
 * 出品を取り下げる（依頼者本人のみ）。open/bidding の案件を cancelled にし、
 * 付いている入札はすべて rejected になる。
 * 409: draft / 成約済み（取引キャンセルへ誘導）/ 取り下げ済み / 状態競合。
 */
export function cancelCase(
  caseId: string,
  reason: string | null,
  token: string,
): Promise<CaseOut> {
  return request(`/cases/${caseId}/cancel`, {
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

/** admin が業者アカウントを停止（true）／停止解除（false）する。承認状態（vendor_status）は変えない。 */
export function adminSuspendOperator(
  operatorId: string,
  suspended: boolean,
  token: string,
): Promise<OperatorOut> {
  return request(`/admin/operators/${operatorId}/suspend`, {
    method: "PATCH",
    body: JSON.stringify({ suspended }),
    token,
  });
}

/**
 * admin が業者の古物商許可証画像を確認する（画像バイナリ）。
 * request<T>() は JSON専用のためここでも生 fetch を使い、Blob をそのまま返す
 * （表示側は URL.createObjectURL → 表示後 URL.revokeObjectURL でクリーンアップすること）。
 */
export async function adminGetOperatorLicenseImage(
  operatorId: string,
  token: string,
): Promise<Blob> {
  let res: Response;
  try {
    res = await fetch(`${apiBase()}/admin/operators/${operatorId}/license-image`, {
      headers: { Authorization: `Bearer ${token}` },
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
  return await res.blob();
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

/**
 * 商品ごとのアルバム（画面表示用の正規化構造）。
 * id === null は疑似アルバム（items に属さない写真の受け皿）を表す。
 * title === null の場合、見出しを描画せず単一グリッドとして表示すること
 * （items 無しのレガシー案件を現行と完全に同じ見た目にするための後方互換フラグ）。
 */
export type CaseAlbum = {
  id: string | null;
  title: string | null;
  aiDetectedName?: string | null;
  aiCondition?: string | null;
  aiSummary?: string | null;
  /** 表示用の実効値（user_condition ?? ai_condition）。ユーザー編集を優先して見せる。 */
  condition?: string | null;
  /** 表示用の実効値（user_description ?? ai_summary）。ユーザー編集を優先して見せる。 */
  description?: string | null;
  photos: CasePhoto[];
};

/**
 * CaseOut/CaseMasked の items + photos（フラット）から表示用アルバム配列を組み立てる。
 * - items を sort_order 順にアルバムへ変換（タイトルは 商品名 → ai_detected_name → "商品 N" の優先順）。
 * - c.photos のうち、どの item にも属さない写真は末尾の疑似アルバムにまとめる。
 * - items が空/undefined の場合、疑似アルバムの title は null になる
 *   （見出しなしの単一グリッドとして描画され、レガシー案件の見た目を維持する）。
 */
export function toAlbums(c: { items?: CaseItemOut[]; photos: CasePhoto[] }): CaseAlbum[] {
  const items = [...(c.items ?? [])].sort((a, b) => a.sort_order - b.sort_order);

  const albums: CaseAlbum[] = items.map((item, i) => ({
    id: item.id,
    title: (item.name?.trim() || item.ai_detected_name?.trim() || `商品 ${i + 1}`),
    aiDetectedName: item.ai_detected_name,
    aiCondition: item.ai_condition,
    aiSummary: item.ai_summary,
    condition: item.user_condition ?? item.ai_condition,
    description: item.user_description ?? item.ai_summary,
    photos: item.photos,
  }));

  const assignedPhotoIds = new Set(items.flatMap((item) => item.photos.map((p) => p.id)));
  const unassignedPhotos = c.photos.filter((p) => !assignedPhotoIds.has(p.id));

  if (unassignedPhotos.length > 0) {
    albums.push({
      id: null,
      title: albums.length > 0 ? "未分類の写真" : null,
      photos: unassignedPhotos,
    });
  }

  return albums;
}

export const CASE_STATUS_LABEL: Record<CaseStatus, string> = {
  draft: "下書き",
  open: "入札受付中",
  bidding: "入札あり",
  closed: "業者決定済み",
  cancelled: "キャンセル",
};

/**
 * BidStatus の表示ラベル（旧 operator/cases/[id]/page.tsx の MY_BID_STATUS_LABEL を移設）。
 * Record<BidStatus, string> にすることで、将来のステータス追加時に網羅漏れが
 * コンパイルエラーになる（呼び出し側での表示漏れを防ぐ）。
 */
export const BID_STATUS_LABEL: Record<BidStatus, string> = {
  pending: "選定待ち",
  selected: "落札",
  rejected: "未選定",
  withdrawn: "取り下げ済み",
};

/** ItemCondition（商品の状態タグ）の表示ラベル。編集フォームのセレクト選択肢もこのキー順で生成する。 */
export const CASE_ITEM_CONDITION_LABEL: Record<string, string> = {
  new: "新品",
  like_new: "ほぼ新品",
  good: "良好",
  fair: "使用感あり",
  poor: "傷み・破損あり",
  unknown: "不明",
};

export const TXN_STATUS_LABEL: Record<TransactionStatus, string> = {
  pending: "訪問日調整中",
  visiting: "訪問予定",
  completed: "完了",
  cancelled: "キャンセル",
};
