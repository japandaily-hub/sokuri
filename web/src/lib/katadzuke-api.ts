/**
 * カタヅケ API クライアント — backend schemas_katadzuke.py と 1:1 対応。
 * 既存の api.ts（旧版流用分）には手を入れず分離する。
 *
 * 認証が必要な関数は token（backend JWT / session.accessToken）を受け取る。
 */

import { signOut } from "next-auth/react";
import { isProtectedRoutePath } from "./protected-routes";

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
  /** 業者都合でキャンセルした取引の累計件数（運営がキャンセル常習を検知する材料）。r8-fix-frontend2 M1 対応。 */
  cancel_count: number;
}

export interface OperatorPublic {
  id: string;
  company_name: string;
  rating: number | null;
  verified_at: string | null;
  /** 顧客→業者レビューの件数（口コミは常時公開）。 */
  review_count: number;
  /** 最新の口コミ本文の抜粋（無ければ null）。 */
  latest_review_comment: string | null;
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
  /**
   * 冪等キー（crypto.randomUUID() で生成）。同一送信の再試行では同じ値を送ることで、
   * 通信断・二重タップによる案件の二重作成を防ぐ（backend: 同一ユーザー・同一キーが
   * 直近10分に存在すれば新規作成せず既存案件を 200 で返す）。
   */
  idempotency_key?: string;
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
  /**
   * AI 解析の進捗。案件作成は解析の完了を待たずに応答するため、"pending" の間は
   * GET /cases/{id} を3秒間隔でポーリングする（最大3分）。"failed" でも案件自体は有効で、
   * ai_summary には作成時のフォールバック文が入る。未対応の古いレスポンスとの互換のため
   * 省略時は "done" 相当として扱うこと。
   */
  ai_status: "pending" | "done" | "failed";
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
  /**
   * 入札業者が運営により利用停止中か。true の入札は選択不可として扱い
   * 「この業者は現在利用停止中です。運営にお問い合わせください。」を表示する
   * （一覧からは除外されず旗が立つ方式。r6-flow ADD-1）。
   */
  operator_suspended: boolean;
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
  /** 相手方から届いた未読メッセージ数（自分側の last_read_at より後のもの）。r6-flow M-3 対応。 */
  unread_count: number;
  /**
   * 依頼者が運営により利用停止中か（業者側にのみ意味がある）。
   * r8-fix-frontend2 M4 対応。
   */
  user_suspended: boolean;
}

/** キャンセルの記録（誰が・なぜ・いつ）。r8-fix-frontend2 H2 対応。 */
export interface TransactionCancellation {
  cancelled_by: "user" | "operator" | "admin";
  reason: string | null;
  cancelled_at: string;
}

/** cancelled_by の表示ラベル。 */
export const CANCELLED_BY_LABEL: Record<TransactionCancellation["cancelled_by"], string> = {
  user: "依頼者",
  operator: "業者",
  admin: "運営",
};

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
  /**
   * 落札業者が利用停止中か（依頼者側にのみ意味がある。業者側は 403 の
   * detail.code=account_suspended で自身の停止を知れる）。r6-flow H-2 対応。
   */
  operator_suspended: boolean;
  /**
   * 依頼者が運営により利用停止中か（業者側にのみ意味がある）。
   * r8-fix-frontend2 M4 対応。
   */
  user_suspended: boolean;
  /** キャンセル済みの場合のみ非null。誰が・なぜ・いつキャンセルしたか。r8-fix-frontend2 H2 対応。 */
  cancellation: TransactionCancellation | null;
  /** 落札業者が退会済みか（依頼者・業者双方の画面で取引継続不可の判定に使う）。r8-fix-frontend5 対応。 */
  operator_deleted: boolean;
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
  return request(`/transactions/${encodeURIComponent(transactionId)}/messages${query}`, { token });
}

export function sendMessage(
  transactionId: string,
  body: string,
  token: string,
): Promise<MessageOut> {
  return request(`/transactions/${encodeURIComponent(transactionId)}/messages`, {
    method: "POST",
    body: JSON.stringify({ body }),
    token,
  });
}

export function markMessagesRead(
  transactionId: string,
  token: string,
): Promise<TransactionOut> {
  return request(`/transactions/${encodeURIComponent(transactionId)}/messages/read`, {
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
  return request(`/transactions/${encodeURIComponent(transactionId)}/schedule/propose`, {
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
  return request(`/transactions/${encodeURIComponent(transactionId)}/schedule/confirm`, {
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
  show_message: boolean;
  accept_unsellable: boolean;
  /** 顧客→業者レビューの件数。評価・口コミは常時公開。 */
  review_count: number;
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

/**
 * 業者アカウントを退会（削除）する。パスワード再照合が必須（403: パスワード不一致）。
 * 進行中の取引が残っている場合は 409（detail は文字列）。短時間の連打は 429。
 * r8-fix-frontend2 M6 / r8-review H-4 対応。
 */
export function deleteMyOperatorAccount(password: string, token: string): Promise<void> {
  return request("/operator/me", {
    method: "DELETE",
    body: JSON.stringify({ password }),
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
    await throwHttpError(res);
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
  review_count: number;
  reviews: PublicReview[];
}

export function getVendorPublicProfile(operatorId: string): Promise<OperatorPublicProfile> {
  return request(`/vendors/${encodeURIComponent(operatorId)}`);
}

/** 業者一覧（GET /vendors）の1行。承認済み・停止中でない業者のみ。個人情報は含まない。 */
export interface VendorListItem {
  operator_id: string;
  company_name: string;
  is_approved: boolean;
  areas: string[];
  strong_categories: string[];
  accept_unsellable: boolean;
  rating: number | null;
  review_count: number;
  latest_review_comment: string | null;
}

export function getVendors(): Promise<VendorListItem[]> {
  return request(`/vendors`);
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

// ---------------------------------------------------------------------------
// セッション失効（401）／アカウント停止（403 account_suspended）共通処理
//
// backend は JWT 失効時に英語の生 detail（"Invalid credentials. Please log in
// again."）を返す（backend/app/api/deps.py、編集除外のため直せない）。
// これをそのまま画面に出さず、日本語文言 + signOut → 役割別ログイン画面への
// 誘導に差し替える。line-link.ts の linkLineToCurrentUser は本ファイルの
// request() を使わず独自 fetch で 401 を reauth_required（正常系）として
// 扱っているため、ここでの自動リダイレクトの影響を受けない（opt-out 不要）。
//
// r3 セキュリティレビュー H-2 是正: signOut 失敗時にまで無条件で画面遷移すると、
// 遷移後も古いセッションが残り 401 → 遷移 → 401 の無限ループになりうる。
// signOut を await し成功時のみ遷移し、失敗時は遷移せず案内文言のみ返す。
// ループ検知はモジュール変数（フルページ遷移でリセットされる）ではなく
// sessionStorage に発火時刻を永続化し、60秒以内に3回以上発火したら
// signOut/遷移そのものを止めて案内だけ出す。
//
// r6-fix-frontend4 是正: NextAuth のセッション（cookie）は残っているが backend の
// JWT が無効（7日期限切れ・退会・DB入れ替え等）な状態で公開ページ（/, /faq,
// /vendors 等）を開くと、AppHeaderBell 等の「装飾的」な認証付き呼び出しが 401 を
// 受け、以下がそのまま作動して訪問者を /login に強制送還し「セッションの有効期限が
// 切れました」を出していた。公開ページで表示すべきものは何もログインを要さない
// ため、これは誤検知の強制ログアウトである。
// 是正後は2段構えにする。
//  (1) パス判定: lib/protected-routes.ts の isProtectedRoutePath() で判定し、
//      保護ルート（USER_PROTECTED_PATHS / OPERATOR系 / /admin）でなければ
//      signOut({redirect:false}) でセッションだけ静かに破棄し、画面遷移も
//      文言表示もしない（ヘッダー表示がログアウト状態に切り替わるのみ）。
//      保護ルートでは従来どおり案内文言＋役割別ログイン画面への遷移を行う。
//  (2) 呼び出し側判定: AppHeaderBell のような「装飾的」呼び出しは request() に
//      { decorative: true } を渡すことで、保護ルート上であっても常に (1) の
//      「静かに破棄するだけ」の分岐を強制される（ページの主要データではなく
//      ヘッダー表示の付随情報でしかないため、保護ルートであっても強制遷移
//      までは正当化されない）。signOut自体は sessionExpiredHandled による
//      モジュールスコープの1回ガード（既存のループ検知キーを流用）で複数の
//      装飾的呼び出しが同時に401しても1回に抑えられる。
// ---------------------------------------------------------------------------

export const SESSION_EXPIRED_MESSAGE =
  "セッションの有効期限が切れました。もう一度ログインしてください。";

export const SESSION_SUSPENDED_MESSAGE =
  "このアカウントは利用停止中です。お問い合わせ窓口までご連絡ください。";

/** signOut に失敗した場合／リダイレクトループを検知した場合に表示する文言（画面遷移はしない）。 */
export const SESSION_EXPIRED_STUCK_MESSAGE =
  "セッションを終了できませんでした。ページを再読み込みするか、ログアウトしてください。";

/** 同時に複数の401/403が発生しても signOut/遷移を1回だけに絞るモジュールスコープのガード。 */
let sessionExpiredHandled = false;

const REDIRECT_LOOP_STORAGE_KEY = "kdz_session_redirect_attempts";
const REDIRECT_LOOP_WINDOW_MS = 60_000;
const REDIRECT_LOOP_MAX_ATTEMPTS = 3;

/**
 * リダイレクトループ検知。sessionExpiredHandled はフルページ遷移
 * （window.location.href の代入）でモジュールが再読込されリセットされるため、
 * それをまたいで検知できるよう sessionStorage に発火時刻を永続化する。
 * 直近60秒以内の発火回数が3回以上ならループとみなし true を返す。
 * sessionStorage が使えない環境（プライベートブラウズ等）では検知をスキップする（fail-open）。
 */
function isRedirectLooping(): boolean {
  try {
    const now = Date.now();
    const raw = window.sessionStorage.getItem(REDIRECT_LOOP_STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    const prevTimestamps = Array.isArray(parsed)
      ? parsed.filter((t): t is number => typeof t === "number")
      : [];
    const recent = prevTimestamps.filter((t) => now - t < REDIRECT_LOOP_WINDOW_MS);
    recent.push(now);
    window.sessionStorage.setItem(REDIRECT_LOOP_STORAGE_KEY, JSON.stringify(recent));
    return recent.length >= REDIRECT_LOOP_MAX_ATTEMPTS;
  } catch {
    return false;
  }
}

/**
 * r3 セキュリティレビュー N-8 是正: ログインに成功した経路で呼ぶ。
 * ループ検知用の発火履歴を消し、直後に 401/403 を踏んだ場合の誤検知
 * （実際にはループしていないのに3回とカウントされてしまう）を防ぐ。
 * sessionStorage が使えない環境では何もしない（fail-safe）。
 */
export function clearRedirectLoopStorage(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(REDIRECT_LOOP_STORAGE_KEY);
  } catch {
    /* プライベートブラウズ等で sessionStorage が使えない場合は無視 */
  }
}

/**
 * backend 401／停止アカウントの 403 を検知した際の共通後始末。
 * NextAuth の signOut を await し、成功した場合は現在のパスに応じて分岐する。
 *  - 保護ルート（isProtectedRoutePath === true）かつ decorative でない呼び出し:
 *    従来どおり役割別ログイン画面（依頼者 /login・業者 /operator/login）または
 *    停止案内（/login?reason=suspended）へ遷移し、案内文言を返す。
 *  - それ以外（公開ページ、または decorative な呼び出し）:
 *    画面遷移も文言表示もしない。セッションを静かに破棄するだけに留め、
 *    空文字を返す（呼び出し元が誤って画面に表示しても空欄になるだけで、
 *    誤検知の「セッション期限切れ」文言が出ないようにする）。
 * signOut 失敗時・直近60秒に3回以上発火したループ検知時は遷移せず、
 * 呼び出し元にそのまま表示させる案内文言を返す。
 * サーバー側（SSR/RSC）実行時は window が無いため何もしない（fail-safe）。
 */
async function handleSessionExpired(
  opts: { suspended?: boolean; decorative?: boolean } = {},
): Promise<string> {
  const fallbackMessage = opts.suspended ? SESSION_SUSPENDED_MESSAGE : SESSION_EXPIRED_MESSAGE;
  if (typeof window === "undefined") return fallbackMessage;
  if (sessionExpiredHandled) return fallbackMessage;
  sessionExpiredHandled = true;

  if (isRedirectLooping()) return SESSION_EXPIRED_STUCK_MESSAGE;

  try {
    await signOut({ redirect: false });
  } catch {
    return SESSION_EXPIRED_STUCK_MESSAGE;
  }

  const shouldRedirect = !opts.decorative && isProtectedRoutePath(window.location.pathname);
  if (!shouldRedirect) return "";

  const isOperator = window.location.pathname.startsWith("/operator");
  if (opts.suspended) {
    // r3 セキュリティレビュー N-6 是正: 業者停止時は /login ではなく
    // /operator/login?reason=suspended へ送り、業者向けの案内文言を出す。
    window.location.href = isOperator ? "/operator/login?reason=suspended" : "/login?reason=suspended";
    return SESSION_SUSPENDED_MESSAGE;
  }
  const loginPath = isOperator ? "/operator/login" : "/login";
  window.location.href = `${loginPath}?callbackUrl=${encodeURIComponent(
    window.location.pathname + window.location.search,
  )}`;
  return SESSION_EXPIRED_MESSAGE;
}

/**
 * !res.ok の共通エラー化。401 はここで日本語文言へ差し替え、セッション失効の後始末を行う。
 * 403 かつ detail.code === "account_suspended"（backend 停止ゲート）も同じ後始末に合流させる。
 */
async function throwHttpError(
  res: Response,
  opts?: { skipAuthRedirect?: boolean; decorative?: boolean },
): Promise<never> {
  if (res.status === 401 && !opts?.skipAuthRedirect) {
    const message = await handleSessionExpired({ decorative: opts?.decorative });
    throw new KdzApiError(401, message);
  }
  let message = `HTTP ${res.status}`;
  let detailCode: string | undefined;
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") {
      message = body.detail;
    } else if (body.detail && typeof body.detail === "object") {
      const detail = body.detail as { code?: unknown; message?: unknown };
      if (typeof detail.code === "string") detailCode = detail.code;
      if (typeof detail.message === "string") message = detail.message;
    }
  } catch {
    /* JSON でないレスポンスは無視 */
  }
  if (res.status === 403 && detailCode === "account_suspended" && !opts?.skipAuthRedirect) {
    const suspendedMessage = await handleSessionExpired({
      suspended: true,
      decorative: opts?.decorative,
    });
    throw new KdzApiError(403, suspendedMessage);
  }
  throw new KdzApiError(res.status, message);
}

/**
 * AbortSignal.timeout の代替。Safari 15 以前・古い Android WebView・LINE内蔵ブラウザ等
 * 未実装の環境で AbortSignal.timeout(ms) を直接呼ぶと同期的な TypeError が投げられ
 * 送信ボタンが即座に失敗するため（QAレビュー未解決リスク1）、呼び出し前に必ずこれを経由する。
 * フォールバック時も TimeoutError 名の DOMException で abort し、
 * 呼び出し側の isTimeout 判定（err.cause?.name === "TimeoutError"）と互換にする。
 */
export function createTimeoutSignal(ms: number): AbortSignal {
  if (typeof AbortSignal.timeout === "function") return AbortSignal.timeout(ms);
  const controller = new AbortController();
  setTimeout(() => {
    controller.abort(new DOMException("The operation timed out.", "TimeoutError"));
  }, ms);
  return controller.signal;
}

async function request<T>(
  path: string,
  init?: RequestInit & { token?: string; skipAuthRedirect?: boolean; decorative?: boolean },
): Promise<T> {
  const { token, skipAuthRedirect, decorative, ...rest } = init ?? {};
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
    await throwHttpError(res, { skipAuthRedirect, decorative });
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
  /** "YYYY-MM-DD"。なりすまし・不正出品の防止および運営からの本人確認のため（任意提出）に使用。古物営業法第15条の確認義務を負うのは訪問する古物商（業者）であり、当社ではない。 */
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
// 住所（なりすまし・不正出品の防止および運営からの本人確認のため（任意提出）に使用。成約時は業者へ開示。古物営業法第15条の確認義務を負うのは訪問する古物商＝業者であり、当社ではない）
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
// 振込口座（お振込みを希望する場合に業者へ伝える口座情報。業者へ自動開示はしない）
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
  /** has_password === true のユーザーは必須（未入力→422、不一致→400）。LINE専用ユーザーは省略可。 */
  current_password?: string | null;
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

/**
 * 振込口座を削除する。has_password === true のユーザーは currentPassword が必須
 * （未入力→422、不一致→400）。LINE専用ユーザー（has_password === false）は null を渡してよい。
 */
export function deleteMyBankAccount(
  currentPassword: string | null,
  token: string,
): Promise<void> {
  return request("/users/me/bank-account", {
    method: "DELETE",
    body: JSON.stringify({ current_password: currentPassword }),
    token,
  });
}

// ---------------------------------------------------------------------------
// 本人確認（なりすまし・不正出品の防止のため。任意提出）
// ---------------------------------------------------------------------------

/** 書類種別の内部トークン。backend の doc_type と1:1対応する。 */
export type IdentityDocType =
  | "drivers_license"
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
  { id: "drivers_license", label: "運転免許証", backRequired: true },
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
    await throwHttpError(res);
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
      `${apiBase()}/users/me/identity-documents/${encodeURIComponent(documentId)}/file?${new URLSearchParams({ side })}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
  } catch (e) {
    if (e instanceof KdzApiError) throw e;
    throw new KdzNetworkError(e);
  }
  if (!res.ok) {
    await throwHttpError(res);
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
  params: { limit?: number; offset?: number },
  token: string,
): Promise<AdminIdentityDocument[]> {
  const sp = new URLSearchParams({ status });
  sp.set("limit", String(params.limit ?? ADMIN_LIST_DEFAULT_LIMIT));
  sp.set("offset", String(params.offset ?? 0));
  return request(`/admin/identity-documents?${sp.toString()}`, { token });
}

export async function fetchIdentityDocumentBlobAdmin(
  documentId: string,
  side: "front" | "back",
  token: string,
): Promise<Blob> {
  let res: Response;
  try {
    res = await fetch(
      `${apiBase()}/admin/identity-documents/${encodeURIComponent(documentId)}/file?${new URLSearchParams({ side })}`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
  } catch (e) {
    if (e instanceof KdzApiError) throw e;
    throw new KdzNetworkError(e);
  }
  if (!res.ok) {
    await throwHttpError(res);
  }
  return await res.blob();
}

export function approveIdentityDocument(
  documentId: string,
  token: string,
): Promise<AdminIdentityDocument> {
  return request(`/admin/identity-documents/${encodeURIComponent(documentId)}/approve`, {
    method: "PATCH",
    token,
  });
}

export function rejectIdentityDocument(
  documentId: string,
  rejectReason: string,
  token: string,
): Promise<AdminIdentityDocument> {
  return request(`/admin/identity-documents/${encodeURIComponent(documentId)}/reject`, {
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
// お問い合わせ（/contact）
// ---------------------------------------------------------------------------

export interface ContactMessagePayload {
  name: string;
  email: string;
  category: string;
  message: string;
}

/**
 * お問い合わせフォームの送信。未ログイン訪問者も送信できるため token なし。
 * 成功: 202 { ok: true }。422（入力不正）/429（送信過多）/5xx はいずれも
 * 呼び出し側で日本語の案内へ変換して表示し、偽の完了表示は出さないこと
 * （運営導線監査 r3-operator.md H1 是正）。
 */
export function submitContactMessage(
  payload: ContactMessagePayload,
): Promise<{ ok: boolean }> {
  return request("/contact", { method: "POST", body: JSON.stringify(payload) });
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
// 管理: 業者事前申込（/business 経由）の審査・承認・却下・口座開示
// r4監査 H1/ADD-H1 対応: 一覧・詳細・承認・却下・口座開示のいずれも画面から到達できなかった穴を埋める。
// ---------------------------------------------------------------------------

export type OperatorApplicationStatus = "received" | "approved" | "rejected";

/** admin一覧・詳細用。口座番号は下4桁マスクのみ含む（全桁はreveal APIで別途取得）。 */
export interface BankAccountMaskedOut {
  bank_name: string;
  branch_name: string;
  account_type: "ordinary" | "checking";
  account_number_masked: string;
  account_holder: string;
}

export interface OperatorApplicationOut {
  id: string;
  status: OperatorApplicationStatus;
  company_name: string;
  representative_name: string;
  registered_address: string;
  contact_name: string;
  contact_email: string;
  contact_phone: string;
  license_number: string;
  business_type: "corp" | "sole" | null;
  service_area: string | null;
  categories: string | null;
  message: string | null;
  invoice_number: string | null;
  bank_account: BankAccountMaskedOut | null;
  agreed_terms_version: string | null;
  agreed_at: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  reject_reason: string | null;
  operator_id: string | null;
  created_at: string;
}

/** admin向け: 口座情報の全桁復号結果。取得のたびに backend 側でアクセスログが記録される。 */
export interface OperatorApplicationBankAccountRevealOut {
  bank_name: string;
  branch_name: string;
  account_type: string;
  account_number: string;
  account_holder: string;
}

export interface OperatorApplicationApproveResponse {
  application: OperatorApplicationOut;
  invite_code: string;
}

/**
 * admin一覧のレスポンス（r4-fix-frontend2 M4: backend が status/q 絞り込み＋total 集計に対応）。
 * items は status="received" 優先ソート（backend側）。
 */
export interface OperatorApplicationListResponse {
  items: OperatorApplicationOut[];
  total: number;
}

/**
 * status/q/limit/offset はすべて backend 側で絞り込み・集計される
 * （r4-fix-frontend2 M4: 旧「先頭ページのみが検索・件数の対象」制約を解消）。
 * status は AdminListParams.status を流用し "all" 指定時は絞り込みなし（buildAdminListQuery参照）。
 */
export function adminListOperatorApplications(
  params: AdminListParams,
  token: string,
): Promise<OperatorApplicationListResponse> {
  return request(`/admin/operator-applications?${buildAdminListQuery(params)}`, { token });
}

export function adminGetOperatorApplication(
  applicationId: string,
  token: string,
): Promise<OperatorApplicationOut> {
  return request(`/admin/operator-applications/${encodeURIComponent(applicationId)}`, { token });
}

/**
 * admin が業者申込の振込先口座情報を全桁復号して取得する。
 * 必要な時（口座内容を実際に確認する時）だけ呼び出すこと（backend でアクセスがログ記録される）。
 */
export function adminRevealOperatorApplicationBankAccount(
  applicationId: string,
  token: string,
): Promise<OperatorApplicationBankAccountRevealOut> {
  return request(
    `/admin/operator-applications/${encodeURIComponent(applicationId)}/reveal-bank-account`,
    { method: "POST", token },
  );
}

/** admin が業者申込を承認する。招待コードが新規発行され、申込者へ承認メールが送られる。 */
export function adminApproveOperatorApplication(
  applicationId: string,
  token: string,
): Promise<OperatorApplicationApproveResponse> {
  return request(
    `/admin/operator-applications/${encodeURIComponent(applicationId)}/approve`,
    { method: "PATCH", token },
  );
}

/** admin が業者申込を却下する。理由は申込者へ却下メールで送られる。 */
export function adminRejectOperatorApplication(
  applicationId: string,
  rejectReason: string,
  token: string,
): Promise<OperatorApplicationOut> {
  return request(
    `/admin/operator-applications/${encodeURIComponent(applicationId)}/reject`,
    { method: "PATCH", body: JSON.stringify({ reject_reason: rejectReason }), token },
  );
}

// ---------------------------------------------------------------------------
// 写真アップロード
// ---------------------------------------------------------------------------

/** アップロード可能な画像形式（backend の storage.sniff_image_ext と一致させる）。 */
const ALLOWED_PHOTO_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

/** 写真アップロードのサイズ上限（backend の services/storage.py MAX_UPLOAD_BYTES = 10MB と一致）。 */
export const MAX_PHOTO_UPLOAD_BYTES = 10 * 1024 * 1024;

export async function uploadCasePhoto(
  file: File,
  token: string,
): Promise<PresignResponse> {
  // r8-fix-frontend2 H4 是正: 非対応形式（HEIC 等）を "image/jpeg" と偽って送ると
  // backend のマジックバイト判定で必ず 415 になり、原因不明の失敗として再試行を招く。
  // 送信前にクライアント側で弾き、対応形式・上限サイズを明示する。
  // r8-review M-3: file.type が空文字（拡張子なし／未知拡張子の JPEG を一部の
  // Android ピッカー・Linux Chrome で選んだ場合）は「非対応形式」ではなく
  // 「ブラウザが判定できなかった」だけ。ここで弾くと従来成功していた正当な写真が
  // 必ず失敗する回帰になるため、従来どおり image/jpeg として送り、最終判断は
  // backend のマジックバイト判定（services/storage.sniff_image_ext）に委ねる。
  if (file.type !== "" && !ALLOWED_PHOTO_TYPES.has(file.type)) {
    throw new KdzApiError(422, "対応形式は JPEG / PNG / WebP です。別の形式（HEIC等）の場合は変換してからお試しください。");
  }
  if (file.size > MAX_PHOTO_UPLOAD_BYTES) {
    throw new KdzApiError(422, "ファイルサイズが上限（10MB）を超えています。");
  }
  const contentType = (file.type === "" ? "image/jpeg" : file.type) as
    | "image/jpeg"
    | "image/png"
    | "image/webp";

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
  // r8-fix-frontend2 H4 是正: 従来は 401 以外の全エラーを汎用文言に潰していたため、
  // 413/415/422 の backend detail（サイズ超過・非対応形式・空ファイル等）が
  // 一切表示されなかった。throwHttpError に一本化し detail をそのまま出す。
  if (!res.ok) await throwHttpError(res);
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

/**
 * 案件を作成する。AI画像解析は backend 側で BackgroundTasks 化されており、
 * このリクエスト自体は即応答する（`CaseOut.ai_status` が "pending" で返る）。
 * 呼び出し側は `payload.idempotency_key` に `crypto.randomUUID()` を渡し、
 * 同一送信の再試行では同じ値を使うこと（通信断・二重タップによる二重作成の防止）。
 * 解析結果は `getCase` を "pending" の間 3 秒間隔でポーリングして取得する（最大3分）。
 */
export function createCase(
  payload: CaseCreatePayload,
  token: string,
  signal?: AbortSignal,
): Promise<CaseOut> {
  return request("/cases", { method: "POST", body: JSON.stringify(payload), token, signal });
}

export function listMyCases(token: string): Promise<CaseOut[]> {
  // backend は依頼者の自分の案件一覧に limit を適用しない（全件返す。cases.py:list_cases 参照）ため
  // クエリは付けない。
  return request("/cases", { token });
}

/** 一覧のページング既定値（backend の既定100・上限200と一致させる。r6 H-1）。 */
export const LIST_DEFAULT_LIMIT = 100;
export const LIST_MAX_LIMIT = 200;

export interface ListPageParams {
  limit?: number;
  offset?: number;
}

/**
 * 「さらに読み込む」で継ぎ足したリストを id で重複排除する（最初の出現を残す）。
 * offset ページングは総件数を持たないため、ページ境界の前後で新規作成・削除が起きると
 * 次ページが1件ずれて重複・欠落しうる（r6-verify N3）。重複表示は React の key 衝突にも
 * つながるため、追記のたびにこれを通す。
 */
export function dedupeById<T extends { id: string }>(items: T[]): T[] {
  const seen = new Set<string>();
  const out: T[] = [];
  for (const item of items) {
    if (seen.has(item.id)) continue;
    seen.add(item.id);
    out.push(item);
  }
  return out;
}

function buildListPageQuery(params?: ListPageParams): string {
  const sp = new URLSearchParams();
  sp.set("limit", String(params?.limit ?? LIST_DEFAULT_LIMIT));
  sp.set("offset", String(params?.offset ?? 0));
  return sp.toString();
}

/**
 * 業者向け「入札可能案件」一覧。backend は既定100・上限200件で切り詰める（r6 H-1）。
 * 総件数はレスポンスに含まれないため、呼び出し側は取得件数が limit と一致する間
 * 「さらに読み込む余地がある」と判断すること（未満なら終端）。
 */
export function listOpenCases(token: string, params?: ListPageParams): Promise<CaseMasked[]> {
  return request(`/cases?${buildListPageQuery(params)}`, { token });
}

export function getCase(caseId: string, token: string): Promise<CaseOut> {
  return request(`/cases/${encodeURIComponent(caseId)}`, { token });
}

export function getCaseMasked(caseId: string, token: string): Promise<CaseMasked> {
  return request(`/cases/${encodeURIComponent(caseId)}`, { token });
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
  return request(`/cases/${encodeURIComponent(caseId)}/items/${encodeURIComponent(itemId)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
    token,
  });
}

export function deleteCaseItem(caseId: string, itemId: string, token: string): Promise<void> {
  return request(`/cases/${encodeURIComponent(caseId)}/items/${encodeURIComponent(itemId)}`, { method: "DELETE", token });
}

export function deleteCasePhoto(caseId: string, photoId: string, token: string): Promise<void> {
  return request(`/cases/${encodeURIComponent(caseId)}/photos/${encodeURIComponent(photoId)}`, { method: "DELETE", token });
}

export function addCaseItemPhoto(
  caseId: string,
  itemId: string,
  payload: { storage_key: string; sort_order: number },
  token: string,
): Promise<CasePhoto> {
  return request(`/cases/${encodeURIComponent(caseId)}/items/${encodeURIComponent(itemId)}/photos`, {
    method: "POST",
    body: JSON.stringify(payload),
    token,
  });
}

// ---------------------------------------------------------------------------
// 入札
// ---------------------------------------------------------------------------

export function listBids(caseId: string, token: string): Promise<BidOut[]> {
  return request(`/cases/${encodeURIComponent(caseId)}/bids`, { token });
}

export function createBid(
  caseId: string,
  payload: { amount: number; message?: string },
  token: string,
): Promise<BidOut> {
  return request(`/cases/${encodeURIComponent(caseId)}/bids`, {
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
  return request(`/cases/${encodeURIComponent(caseId)}/bids/${encodeURIComponent(bidId)}/select`, { method: "POST", token });
}

// ---------------------------------------------------------------------------
// 成約
// ---------------------------------------------------------------------------

/**
 * 成約一覧（ユーザー: 自分の成約 / 業者: 落札案件）。backend は既定100・上限200件で
 * 切り詰める（r6 H-1）。総件数はレスポンスに含まれないため、取得件数が limit と
 * 一致する間は「さらに読み込む余地がある」と判断すること。
 */
/**
 * opts.decorative: true の場合、401/403(account_suspended) を検知しても
 * 強制ログアウト後の画面遷移・文言表示をしない（AppHeaderBell 等の装飾的な
 * 呼び出し専用。r6-fix-frontend4）。
 */
export function listTransactions(
  token: string,
  params?: ListPageParams,
  opts?: { decorative?: boolean },
): Promise<TransactionListItem[]> {
  return request(`/transactions?${buildListPageQuery(params)}`, { token, decorative: opts?.decorative });
}

export function getTransaction(
  transactionId: string,
  token: string,
  opts?: { decorative?: boolean },
): Promise<TransactionDetail> {
  return request(`/transactions/${encodeURIComponent(transactionId)}`, {
    token,
    decorative: opts?.decorative,
  });
}

export function completeTransaction(
  transactionId: string,
  token: string,
): Promise<TransactionOut> {
  return request(`/transactions/${encodeURIComponent(transactionId)}/complete`, { method: "POST", token });
}

export function cancelTransaction(
  transactionId: string,
  reason: string | null,
  token: string,
): Promise<TransactionOut> {
  return request(`/transactions/${encodeURIComponent(transactionId)}/cancel`, {
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
  return request(`/cases/${encodeURIComponent(caseId)}/cancel`, {
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
  return request(`/transactions/${encodeURIComponent(transactionId)}/reduction`, {
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
  return request(`/transactions/${encodeURIComponent(transactionId)}/reduction/${encodeURIComponent(reductionId)}`, {
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

/** 一覧の既定/上限ページサイズ（backend の _DEFAULT_LIST_LIMIT=100 未満に抑え、無言truncateを避ける）。 */
export interface AdminOffsetListParams {
  limit?: number;
  offset?: number;
}

function buildOffsetListQuery(params: AdminOffsetListParams): string {
  const sp = new URLSearchParams();
  sp.set("limit", String(params.limit ?? ADMIN_LIST_DEFAULT_LIMIT));
  sp.set("offset", String(params.offset ?? 0));
  return sp.toString();
}

export function adminListInvites(
  params: AdminOffsetListParams,
  token: string,
): Promise<InviteOut[]> {
  return request(`/admin/invites?${buildOffsetListQuery(params)}`, { token });
}

/**
 * admin業者一覧のレスポンス（r5-fix-frontend H-1: backend が status/q 絞り込み＋total集計、
 * および現在の絞り込みに関わらず常に正確な状態別件数を返す counts に対応）。
 * items は pending 優先ソート（backend側）。
 */
export interface AdminOperatorListResponse {
  items: OperatorOut[];
  total: number;
  /** 状態別の全体件数。status/q の絞り込み内容に関わらず常に全件の内訳を返す
   *  （審査待ちバッジを常に正確に保つため。r5-ops.md H-1 是正・backend の counts と 1:1）。 */
  counts: {
    all: number;
    pending: number;
    limited: number;
    active: number;
    rejected: number;
    suspended: number;
  };
}

/**
 * status（"all"|"pending"|"limited"|"active"|"rejected"|"suspended"）/q/limit/offset は
 * すべて backend 側で絞り込み・集計される（r5-fix-frontend H-1: 旧「表示中ページのみが
 * 検索・件数の対象」制約を解消。/admin/operator-applications と同型）。
 */
export function adminListOperators(
  params: AdminListParams,
  token: string,
): Promise<AdminOperatorListResponse> {
  return request(`/admin/operators?${buildAdminListQuery(params)}`, { token });
}

export function adminVerifyOperator(
  operatorId: string,
  verified: boolean,
  token: string,
): Promise<OperatorOut> {
  return request(`/admin/operators/${encodeURIComponent(operatorId)}/verify`, {
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
  return request(`/admin/operators/${encodeURIComponent(operatorId)}/suspend`, {
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
    res = await fetch(`${apiBase()}/admin/operators/${encodeURIComponent(operatorId)}/license-image`, {
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch (e) {
    if (e instanceof KdzApiError) throw e;
    throw new KdzNetworkError(e);
  }
  if (!res.ok) {
    await throwHttpError(res);
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
// 管理: 案件・成約の横断閲覧（トラブル介入の起点。r3-operator H2 対応）
// ---------------------------------------------------------------------------

export interface AdminCaseListItem {
  id: string;
  status: CaseStatus;
  created_at: string;
  purpose: string;
  prefecture: string;
  city: string;
  /** admin専用のためマスクなし。 */
  user_email: string | null;
  /** 成約済み（selected bid）の場合のみ非null。 */
  company_name: string | null;
  /** 成約済みの場合のみ非null。 */
  amount: number | null;
  /** 成約済みの場合のみ非null。 */
  visit_date: string | null;
}

export interface AdminCaseListResponse {
  items: AdminCaseListItem[];
  total: number;
}

export interface AdminTransactionListItem {
  id: string;
  case_id: string;
  status: TransactionStatus;
  created_at: string;
  user_email: string | null;
  company_name: string | null;
  amount: number | null;
  visit_date: string | null;
  /** キャンセル済みの場合のみ非null。r8-fix-frontend2 H2 対応。 */
  cancelled_by: string | null;
}

export interface AdminTransactionListResponse {
  items: AdminTransactionListItem[];
  total: number;
}

/**
 * 運営が取引を強制終了する（理由必須。cancelled_by="admin" として記録される）。
 * 依頼者停止等で当事者が動かせなくなった取引を運営が終わらせるための唯一の手段。
 * r8-fix-frontend2 M5 対応。
 */
export function adminCancelTransaction(
  transactionId: string,
  reason: string,
  token: string,
): Promise<{ id: string; status: TransactionStatus }> {
  return request(`/admin/transactions/${encodeURIComponent(transactionId)}/cancel`, {
    method: "PATCH",
    body: JSON.stringify({ reason }),
    token,
  });
}

/** admin一覧APIの既定ページサイズ（backend の _ADMIN_CASE_TXN_DEFAULT_LIMIT と同値）。 */
export const ADMIN_LIST_DEFAULT_LIMIT = 50;

export interface AdminListParams {
  q?: string;
  status?: string;
  limit?: number;
  offset?: number;
}

function buildAdminListQuery(params: AdminListParams): string {
  const sp = new URLSearchParams();
  if (params.q && params.q.trim()) sp.set("q", params.q.trim());
  if (params.status && params.status !== "all") sp.set("status", params.status);
  sp.set("limit", String(params.limit ?? ADMIN_LIST_DEFAULT_LIMIT));
  sp.set("offset", String(params.offset ?? 0));
  return sp.toString();
}

export function adminListCases(
  params: AdminListParams,
  token: string,
): Promise<AdminCaseListResponse> {
  return request(`/admin/cases?${buildAdminListQuery(params)}`, { token });
}

export function adminListTransactions(
  params: AdminListParams,
  token: string,
): Promise<AdminTransactionListResponse> {
  return request(`/admin/transactions?${buildAdminListQuery(params)}`, { token });
}

// ---------------------------------------------------------------------------
// 管理: 依頼者アカウント（一覧・停止／解除。r3-verify-operator ADD-2 対応）
// ---------------------------------------------------------------------------

export interface AdminUserListItem {
  id: string;
  email: string;
  display_name: string | null;
  role: "user" | "admin";
  is_suspended: boolean;
  suspended_at: string | null;
  created_at: string;
  case_count: number;
}

export interface AdminUserListResponse {
  items: AdminUserListItem[];
  total: number;
}

export function adminListUsers(
  params: Pick<AdminListParams, "q" | "limit" | "offset">,
  token: string,
): Promise<AdminUserListResponse> {
  return request(`/admin/users?${buildAdminListQuery(params)}`, { token });
}

export interface AdminUserSuspendResponse {
  id: string;
  is_suspended: boolean;
  suspended_at: string | null;
  /** r3 セキュリティレビュー R-M5 是正: 停止操作時点の進行中案件（open/bidding）件数。 */
  open_case_count: number;
}

/**
 * admin が依頼者アカウントを停止（true）／停止解除（false）する。
 * role=admin のユーザーを対象にした場合は 409（backend側で拒否）。
 */
export function adminSuspendUser(
  userId: string,
  suspended: boolean,
  reason: string | null,
  token: string,
): Promise<AdminUserSuspendResponse> {
  return request(`/admin/users/${encodeURIComponent(userId)}/suspend`, {
    method: "PATCH",
    body: JSON.stringify({ suspended, reason }),
    token,
  });
}

export interface AdminUserRoleResponse {
  id: string;
  role: "user" | "admin";
}

/**
 * admin が依頼者アカウントを管理者へ昇格させる。
 * 停止中のアカウントは対象外（backend側で拒否）。
 */
export function adminPromoteUser(userId: string, token: string): Promise<AdminUserRoleResponse> {
  return request(`/admin/users/${encodeURIComponent(userId)}/promote`, {
    method: "POST",
    token,
  });
}

/**
 * admin が管理者アカウントを一般ユーザーへ降格させる。
 * 自分自身・最後の1名の管理者は対象外（backend側で409拒否）。
 */
export function adminDemoteUser(userId: string, token: string): Promise<AdminUserRoleResponse> {
  return request(`/admin/users/${encodeURIComponent(userId)}/demote`, {
    method: "POST",
    token,
  });
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

/**
 * ReductionStatus の表示ラベル・チップ色（旧 operator/transactions/[id]/page.tsx の
 * ローカル定義を移設）。依頼者側の減額履歴表示（cases/[id]/page.tsx）と共通化するため
 * ここに一本化する（r6-flow M-4 対応）。
 */
export const REDUCTION_STATUS_LABEL: Record<ReductionStatus, string> = {
  pending: "回答待ち",
  approved: "承認",
  rejected: "却下",
};
export const REDUCTION_CHIP_CLASS: Record<ReductionStatus, string> = {
  pending: "warn",
  approved: "bidding",
  rejected: "done",
};
