/**
 * API クライアント
 * バックエンド schemas.py に対応した型定義と fetch ラッパーを提供する。
 * 直接 fetch を呼ばず、このモジュール経由で統一すること。
 */

// ---------------------------------------------------------------------------
// 共通型
// ---------------------------------------------------------------------------

/** コンディション（5段階） */
export type Condition = "new" | "like_new" | "good" | "fair" | "poor";

/** チャネル種別（バックエンド ChannelType と 1:1 対応） */
export type ChannelType =
  | "buyer_asp"
  | "flea_market"
  | "bulk_buyer"
  | "car_appraisal"
  | "real_estate_appraisal"
  | "owned_auction";

/** ルーティング判定の出自（バックエンド RoutingMethod と 1:1 対応） */
export type RoutingMethod = "rule" | "llm" | "hybrid";

/** 推奨チャネル 1 件 */
export interface RecommendedChannel {
  rank: number;
  channel_code: string;
  channel_name: string;
  channel_type: ChannelType;
  reason: string | null;
  is_sponsored: boolean;
  outbound_url: string | null;
}

/** 1 コンディションの見積もり詳細（バックエンド ConditionDetail と対応） */
export interface ConditionDetail {
  label: string;
  multiplier: number;
  estimated_price: number;
  defect_evidence_required: boolean;
}

// ---------------------------------------------------------------------------
// リクエスト / レスポンス型
// ---------------------------------------------------------------------------

/** POST /analyze リクエスト（フロントエンド向け） */
export interface AnalyzeRequest {
  /** base64 エンコードされた画像データ（data URI プレフィックス不要） */
  image: string;
  /** MIME タイプ (e.g. "image/jpeg") */
  mime_type: string;
}

/** POST /analyze レスポンス */
export interface AnalyzeResponse {
  item_id: string;
  detected_name: string;
  initial_condition: Condition;
  category_tier: string;
}

/** POST /estimate リクエスト */
export interface EstimateRequest {
  item_id: string;
  condition: Condition;
}

/** POST /estimate レスポンス */
export interface EstimateResponse {
  assessment_id: string;
  estimated_price: number;
  defect_evidence_required: boolean;
  recommendations: RecommendedChannel[];
}

/** GET /assessments/{id} レスポンス */
export interface AssessmentResponse extends EstimateResponse {
  item_id: string;
  condition: Condition;
}

/** POST /assessments/{id}/defects レスポンス */
export interface DefectsResponse {
  success: boolean;
  message: string;
}

/** POST /albums リクエスト */
export interface AlbumCreateRequest {
  assessment_ids: string[];
  total_estimated_jpy?: number;
  /** 業者非開示。運営からの通知用 */
  lead_email?: string | null;
}

/** POST /albums レスポンス */
export interface AlbumCreateResponse {
  album_id: string;
  status: "draft" | "submitted" | "bidding" | "matched" | "closed" | "cancelled";
  item_count: number;
  total_estimated_jpy: number;
}

// ---------------------------------------------------------------------------
// API エラー
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

// ---------------------------------------------------------------------------
// 内部ユーティリティ
// ---------------------------------------------------------------------------

/**
 * 本番フォールバック API URL。
 *
 * Vercel の Environment Variables を Sensitive 扱いにすると ``NEXT_PUBLIC_*`` が
 * クライアントバンドルに inline されない既知制約があり、env var だけに頼ると
 * 本番でフロントが backend に到達できなくなる。確実性のため本番 Render URL を
 * フォールバックとして埋め込む。
 *
 * Railway → Render 移行履歴:
 *   旧: https://backend-production-e4f0d.up.railway.app/api/v1 (deploy 不安定で廃止)
 *   現: https://sokuri-backend.onrender.com/api/v1
 *
 * ローカル開発時は ``.env.local`` の ``NEXT_PUBLIC_API_URL`` が優先される。
 */
const FALLBACK_PROD_API_URL = "https://sokuri-backend.onrender.com/api/v1";

function getBaseUrl(): string {
  const url = process.env.NEXT_PUBLIC_API_URL || FALLBACK_PROD_API_URL;
  return url.replace(/\/$/, "");
}

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const base = getBaseUrl();
  const res = await fetch(`${base}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  if (!res.ok) {
    let message = `HTTP ${res.status}`;
    try {
      const body: unknown = await res.json();
      if (
        body !== null &&
        typeof body === "object" &&
        "detail" in body &&
        typeof (body as Record<string, unknown>).detail === "string"
      ) {
        message = (body as Record<string, string>).detail;
      }
    } catch {
      // レスポンスが JSON でない場合は無視
    }
    throw new ApiError(res.status, message);
  }

  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// 公開 API 関数
// ---------------------------------------------------------------------------

/**
 * 商品画像を解析して識別情報を返す。
 * フロントエンドは { image, mime_type } で渡すが、
 * バックエンドが期待する { base_image: "data:...;base64,..." } 形式に変換する。
 */
export async function analyzeImage(
  payload: AnalyzeRequest,
): Promise<AnalyzeResponse> {
  return request<AnalyzeResponse>("/analyze", {
    method: "POST",
    body: JSON.stringify({
      base_image: `data:${payload.mime_type};base64,${payload.image}`,
    }),
  });
}

/**
 * コンディションを指定して査定額と推奨チャネルを取得する。
 */
export async function estimatePrice(
  payload: EstimateRequest,
): Promise<EstimateResponse> {
  return request<EstimateResponse>("/estimate", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * 査定結果を assessment_id で取得する（/result ページのフォールバック用）。
 */
export async function getAssessment(
  assessmentId: string,
): Promise<AssessmentResponse> {
  return request<AssessmentResponse>(`/assessments/${assessmentId}`);
}

/**
 * アルバム（一括査定束）を作成する。
 * 「まとめてソクウリ」フローのバックエンド永続化エントリポイント。
 */
export async function createAlbum(
  payload: AlbumCreateRequest,
): Promise<AlbumCreateResponse> {
  return request<AlbumCreateResponse>("/albums", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/**
 * 瑕疵写真をアップロードする。
 * Content-Type は multipart/form-data になるため headers を上書きして送る。
 */
export async function uploadDefects(
  assessmentId: string,
  files: File[],
): Promise<DefectsResponse> {
  const base = getBaseUrl();
  const form = new FormData();
  for (const file of files) {
    form.append("images", file);
  }
  const res = await fetch(`${base}/assessments/${assessmentId}/defects`, {
    method: "POST",
    body: form,
    // Content-Type は fetch が自動設定する (boundary 付き multipart)
  });
  if (!res.ok) {
    throw new ApiError(res.status, `defects upload failed: ${res.status}`);
  }
  return res.json() as Promise<DefectsResponse>;
}
