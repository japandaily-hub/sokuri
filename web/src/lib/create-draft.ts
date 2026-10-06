/**
 * 出品作成（/create）の下書き（sessionStorage 保存用）の純関数。React・ブラウザ API 非依存。
 * M-8: アプリ内リンクで離れて戻ると入力が全消えになる問題への対応。
 *
 * 保存するのはテキスト入力（利用目的・エリア・住居の種類・間取り・階数・エレベーター）だけ。
 *  - 写真はブラウザに保存できないため含めない（復元時に「写真は選び直してください」を出す）。
 *  - 個人情報にあたる「番地・建物名・部屋番号」と連絡先は含めない。
 *  - 同意・確定の操作は復元しない（そもそも保存対象に無い）。
 * 読み戻すときは sessionStorage の値を信用せず、選択肢は許可リスト照合・自由入力は長さと制御文字を検査する。
 */

export const CREATE_DRAFT_STORAGE_KEY = "kdz:create-draft:v1";
export const CREATE_DRAFT_VERSION = 1;
/** 市区町村の上限（create の maxLength と一致）。 */
export const CREATE_DRAFT_CITY_MAX = 64;

export interface CreateDraft {
  purpose: string;
  prefecture: string;
  city: string;
  housingType: string;
  floorPlan: string;
  /** 階数（未入力は ""）。0〜100 の整数の文字列。 */
  floorNumber: string;
  /** エレベーターのチェック（未チェックは未回答として扱う）。 */
  hasElevator: boolean;
}

export interface CreateDraftChoices {
  purposes: readonly string[];
  prefectures: readonly string[];
  housingTypes: readonly string[];
  floorPlans: readonly string[];
}

// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\u0000-\u001f\u007f-\u009f\u200b-\u200f\u202a-\u202e\u2066-\u2069]/;

/** 既定値と同じ（＝まだ何も入力していない）下書きか。保存の要否判定に使う。 */
export function isDefaultDraft(draft: CreateDraft, defaults: CreateDraft): boolean {
  return (
    draft.purpose === defaults.purpose &&
    draft.prefecture === defaults.prefecture &&
    draft.city.trim() === "" &&
    draft.housingType === defaults.housingType &&
    draft.floorPlan === defaults.floorPlan &&
    draft.floorNumber === "" &&
    draft.hasElevator === false
  );
}

/** 保存用の JSON 文字列にする（版数付き）。 */
export function serializeCreateDraft(draft: CreateDraft): string {
  return JSON.stringify({ v: CREATE_DRAFT_VERSION, ...draft });
}

/**
 * 保存された文字列を検証して下書きに戻す。壊れている・版が違う・許可リスト外の値を含む場合は null
 * （一部だけ拾うと意図しない組み合わせになるため、全項目が妥当なときだけ復元する）。
 */
export function parseCreateDraft(raw: string | null | undefined, choices: CreateDraftChoices): CreateDraft | null {
  if (typeof raw !== "string" || raw === "" || raw.length > 2000) return null;
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (record.v !== CREATE_DRAFT_VERSION) return null;

  const { purpose, prefecture, city, housingType, floorPlan, floorNumber, hasElevator } = record;
  if (typeof purpose !== "string" || !choices.purposes.includes(purpose)) return null;
  if (typeof prefecture !== "string" || !choices.prefectures.includes(prefecture)) return null;
  if (typeof housingType !== "string" || !choices.housingTypes.includes(housingType)) return null;
  if (typeof floorPlan !== "string" || !choices.floorPlans.includes(floorPlan)) return null;
  if (typeof city !== "string" || city.length > CREATE_DRAFT_CITY_MAX || CONTROL_CHARS.test(city)) return null;
  if (typeof floorNumber !== "string") return null;
  if (floorNumber !== "" && !(/^\d{1,3}$/.test(floorNumber) && Number(floorNumber) <= 100)) return null;
  if (typeof hasElevator !== "boolean") return null;

  return { purpose, prefecture, city, housingType, floorPlan, floorNumber, hasElevator };
}
