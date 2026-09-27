/**
 * 訪問日程（業者が提示する候補日・依頼者が確定する訪問日程）に関する純関数群。
 *
 * 日程構造化 DESIGN §13: 候補は自由記述のラベルではなく {date:"YYYY-MM-DD", start:"HH:MM"|null,
 * end:"HH:MM"|null} の構造化データで送り、表示ラベル（例: "2026年10月1日（木）9:00〜12:00"）と
 * 確定値はサーバーだけが作る。ここには web 側で必要な規則（時刻の規則・時間帯ラベル・日本時間基準の
 * 期限判定）と、メッセージ meta の実行時の型ガード（提示 v2 / v1 / unknown、確定 v2 / 旧形式）を置く。
 * ラベルから日付を解析する処理（旧 parseSlotDate・SLOT_DATE_PATTERN）は全廃した（SEC-I1 / QA-L5）。
 *
 * - 規則は backend app/services/visit_schedule.py と一致させる。ラベルの正解データは
 *   visit-slots.golden.json（backend・web の両方のテストで照合する）。
 * - VISIT_TIME_SLOTS は backend の一致テストが正規表現で1行ずつ読むため、日程構造化 DESIGN §13.2 の
 *   書式（`{ value: "...", label: "...", start: ..., end: ... },` を1行ずつ）を崩さない。
 *
 * import を持たない純関数のみを置く（node --test でアプリ全体を起動せず単体検証するため。
 * 同じ理由で categories.ts も import できないので、表示時の制御文字の除去は呼び出し側で行う）。
 * 単体テスト: src/lib/visit-slots.test.mts（review-verdict.test.mts と同じ node --test 流儀）。
 */

/** /schedule で確定できる固定5種の時間帯の値（backend の FIXED_VISIT_TIME_SLOTS と1文字違わず一致させる）。 */
export type VisitTimeSlotValue = "9:00〜12:00" | "12:00〜15:00" | "15:00〜18:00" | "18:00〜21:00" | "時間指定なし";

/**
 * 固定の時間帯1件。value は確定値（＝時間帯ラベル）、label はボタンの小見出し、
 * start/end は業者が候補として送る時刻（時間指定なしは両方 null）。
 */
export interface VisitTimeSlot {
  value: VisitTimeSlotValue;
  label: string;
  start: string | null;
  end: string | null;
}

/** 希望時間帯（訪問日程調整ページ・業者の候補日提案フォームで共有する唯一の情報源）。 */
export const VISIT_TIME_SLOTS: VisitTimeSlot[] = [
  { value: "9:00〜12:00", label: "午前", start: "09:00", end: "12:00" },
  { value: "12:00〜15:00", label: "昼", start: "12:00", end: "15:00" },
  { value: "15:00〜18:00", label: "午後", start: "15:00", end: "18:00" },
  { value: "18:00〜21:00", label: "夜", start: "18:00", end: "21:00" },
  { value: "時間指定なし", label: "業者に一任", start: null, end: null },
];

/** value が固定5種のいずれかか（/schedule の確定で送れる値か）。 */
export function isVisitTimeSlotValue(value: string): value is VisitTimeSlotValue {
  return VISIT_TIME_SLOTS.some((slot) => slot.value === value);
}

/** start/end が固定の時間帯のどれかに一致すればそれを返す（業者の入力欄の初期値づくり用）。 */
export function findVisitTimeSlot(start: string | null, end: string | null): VisitTimeSlot | undefined {
  return VISIT_TIME_SLOTS.find((slot) => slot.start === start && slot.end === end);
}

const DOW_LABELS = ["日", "月", "火", "水", "木", "金", "土"] as const;

/* ---------------------------------------------------------------------------
 * 時刻の規則（日程構造化 DESIGN §13.1）
 * ------------------------------------------------------------------------- */

/** 候補の時刻の書式（"HH:MM"・ゼロ詰め・分は 00 か 30）。 */
const VISIT_TIME_PATTERN = /^([01]\d|2[0-3]):(00|30)$/;

/** 候補の開始の下限（06:00・0時からの分）。 */
export const VISIT_TIME_EARLIEST_MINUTES = 6 * 60;
/** 候補の終了の上限（22:00・0時からの分）。 */
export const VISIT_TIME_LATEST_MINUTES = 22 * 60;
/** 候補の最短の長さ（分）。終了 − 開始がこれ未満なら送信できない。 */
export const VISIT_TIME_MIN_DURATION_MINUTES = 60;
/** 時刻の刻み（分）。 */
export const VISIT_TIME_STEP_MINUTES = 30;

/** "HH:MM" を 0時からの分に変換する。書式（ゼロ詰め・分は 00 か 30）に合わなければ null。 */
export function visitTimeToMinutes(time: string): number | null {
  const m = VISIT_TIME_PATTERN.exec(time);
  if (!m) return null;
  return Number(m[1]) * 60 + Number(m[2]);
}

/** 0時からの分を "HH:MM"（ゼロ詰め）にする。範囲外・刻み外でも機械的に整形する（検査は呼び出し側）。 */
function minutesToVisitTime(minutes: number): string {
  const hour = String(Math.floor(minutes / 60)).padStart(2, "0");
  const minute = String(minutes % 60).padStart(2, "0");
  return `${hour}:${minute}`;
}

/**
 * start/end が時刻の規則を満たすか。
 * 両方 null（時間指定なし）か、両方 "HH:MM" で 06:00 ≤ start < end ≤ 22:00 かつ end − start ≥ 60分。
 * 片方だけ null・書式違いは false（サーバーは Pydantic の 422 で拒否する）。
 */
export function isValidVisitTimeRange(start: string | null, end: string | null): boolean {
  if (start === null && end === null) return true;
  if (start === null || end === null) return false;
  const startMinutes = visitTimeToMinutes(start);
  const endMinutes = visitTimeToMinutes(end);
  if (startMinutes === null || endMinutes === null) return false;
  return (
    startMinutes >= VISIT_TIME_EARLIEST_MINUTES &&
    endMinutes <= VISIT_TIME_LATEST_MINUTES &&
    endMinutes - startMinutes >= VISIT_TIME_MIN_DURATION_MINUTES
  );
}

/** "HH:MM" を表示用の "H:MM"（時はゼロ詰めなし）にする（例: "09:00" → "9:00"）。書式違いは空文字。 */
export function formatVisitTime(time: string): string {
  const minutes = visitTimeToMinutes(time);
  if (minutes === null) return "";
  return `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, "0")}`;
}

/**
 * 時間帯ラベル（日程構造化 DESIGN §13.1 の time_label）。
 * null/null → "時間指定なし"、それ以外 → "9:00〜12:00"（時はゼロ詰めなし・波ダッシュは U+301C）。
 * 固定4枠の time_label は VISIT_TIME_SLOTS の value と1文字違わず一致する。規則違反は空文字。
 */
export function timeLabel(start: string | null, end: string | null): string {
  if (!isValidVisitTimeRange(start, end)) return "";
  if (start === null || end === null) return "時間指定なし";
  return `${formatVisitTime(start)}〜${formatVisitTime(end)}`;
}

/* ---------------------------------------------------------------------------
 * 日付（ブラウザのタイムゾーンに依存しない）
 * ------------------------------------------------------------------------- */

const ISO_DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;

/**
 * "YYYY-MM-DD" が実在する日付なら年・月・日・曜日（0=日）を返す。形式違い・実在しない日付
 * （2月30日・平年の2月29日等）は null。Date.UTC と getUTC* で求めるため、ブラウザの
 * タイムゾーン（夏時間を含む）に依存しない。
 */
function parseIsoDate(isoDate: string): { year: number; month: number; day: number; dow: number } | null {
  const m = ISO_DATE_PATTERN.exec(isoDate);
  if (!m) return null;
  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = Number(m[3]);
  const d = new Date(Date.UTC(year, month - 1, day));
  if (d.getUTCFullYear() !== year || d.getUTCMonth() !== month - 1 || d.getUTCDate() !== day) return null;
  return { year, month, day, dow: d.getUTCDay() };
}

/** "YYYY-MM-DD" 形式で実在する日付か。 */
export function isValidIsoDate(isoDate: string): boolean {
  return parseIsoDate(isoDate) !== null;
}

/**
 * Date（ローカルタイムの年月日）を "YYYY-MM-DD" に整形する。
 * new Date(isoString) の UTC 解釈によるズレを避けるため、年月日の各フィールドから直接組み立てる。
 * 日本時間の「今日」が必要な判定には jstTodayIso を使うこと。
 */
export function toIsoDateString(d: Date): string {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/** isoDate に days 日を足した "YYYY-MM-DD"（UTC で計算するので夏時間の影響を受けない）。不正な日付は空文字。 */
export function addDaysIso(isoDate: string, days: number): string {
  const parsed = parseIsoDate(isoDate);
  if (!parsed || !Number.isInteger(days)) return "";
  const d = new Date(Date.UTC(parsed.year, parsed.month - 1, parsed.day + days));
  const month = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${d.getUTCFullYear()}-${month}-${day}`;
}

/**
 * 候補日ラベル（日程構造化 DESIGN §13.1 の label）。業者画面のプレビュー専用
 * （送信・表示に使うラベルはサーバーが作る。正解データ visit-slots.golden.json で一致を検証する）。
 * 例: formatSlotLabel("2026-10-01", "09:00", "12:00") → "2026年10月1日（木）9:00〜12:00"。
 * 括弧は全角、日付と時刻の間に空白は入れない。日付が形式違い・実在しない、または時刻が規則違反なら空文字。
 */
export function formatSlotLabel(isoDate: string, start: string | null, end: string | null): string {
  const parsed = parseIsoDate(isoDate);
  if (!parsed) return "";
  const time = timeLabel(start, end);
  if (!time) return "";
  return `${parsed.year}年${parsed.month}月${parsed.day}日（${DOW_LABELS[parsed.dow]}）${time}`;
}

/* ---------------------------------------------------------------------------
 * 日本時間の現在と期限（日程構造化 DESIGN §13.1）
 * ------------------------------------------------------------------------- */

/** 日本時間（UTC+9。夏時間なし）のずれ（ミリ秒）。 */
const JST_OFFSET_MS = 9 * 60 * 60 * 1000;

/**
 * now（瞬間）の日本時間の日付（"YYYY-MM-DD"）と 0時からの経過分を返す。
 * UTC に 9 時間を足して getUTC* で読むため、ブラウザのタイムゾーンに依存しない。
 * now が不正な Date（NaN）なら RangeError（期限の判定を黙って誤らせないため）。
 */
export function jstNow(now: Date = new Date()): { date: string; minutes: number } {
  const time = now.getTime();
  if (!Number.isFinite(time)) throw new RangeError("jstNow: 不正な日時です");
  const shifted = new Date(time + JST_OFFSET_MS);
  const month = String(shifted.getUTCMonth() + 1).padStart(2, "0");
  const day = String(shifted.getUTCDate()).padStart(2, "0");
  return {
    date: `${shifted.getUTCFullYear()}-${month}-${day}`,
    minutes: shifted.getUTCHours() * 60 + shifted.getUTCMinutes(),
  };
}

/** 日本時間の今日（"YYYY-MM-DD"）。 */
export function jstTodayIso(now: Date = new Date()): string {
  return jstNow(now).date;
}

/**
 * 候補（または /schedule で選んだ日付＋時間帯）が過ぎているか（日本時間）。
 * - date < 今日 → 過ぎている
 * - date = 今日 かつ end が null でなく、現在時刻 ≥ end → 過ぎている
 * - end が null（時間指定なし）の当日は過ぎていない扱い
 * date が形式違い・実在しない、または end が書式違いのときは過ぎている扱い（押させない安全側）。
 */
export function isCandidateExpired(candidate: { date: string; end: string | null }, now: Date = new Date()): boolean {
  if (!isValidIsoDate(candidate.date)) return true;
  const endMinutes = candidate.end === null ? null : visitTimeToMinutes(candidate.end);
  if (candidate.end !== null && endMinutes === null) return true;
  const current = jstNow(now);
  if (candidate.date < current.date) return true;
  if (candidate.date > current.date) return false;
  return endMinutes !== null && current.minutes >= endMinutes;
}

/* ---------------------------------------------------------------------------
 * 「時刻を指定」の選択肢（日程構造化 DESIGN §13.4）
 * ------------------------------------------------------------------------- */

/** fromMinutes〜toMinutes（両端を含む）を VISIT_TIME_STEP_MINUTES 刻みで "HH:MM" にする。 */
function buildVisitTimeOptions(fromMinutes: number, toMinutes: number): readonly string[] {
  const options: string[] = [];
  for (let minutes = fromMinutes; minutes <= toMinutes; minutes += VISIT_TIME_STEP_MINUTES) {
    options.push(minutesToVisitTime(minutes));
  }
  return options;
}

/** 「時刻を指定」の開始の選択肢（6:00〜21:00・30分刻み）。 */
export const CUSTOM_START_TIME_OPTIONS: readonly string[] = buildVisitTimeOptions(
  VISIT_TIME_EARLIEST_MINUTES,
  VISIT_TIME_LATEST_MINUTES - VISIT_TIME_MIN_DURATION_MINUTES,
);
/** 「時刻を指定」の終了の選択肢（7:00〜22:00・30分刻み）。 */
export const CUSTOM_END_TIME_OPTIONS: readonly string[] = buildVisitTimeOptions(
  VISIT_TIME_EARLIEST_MINUTES + VISIT_TIME_MIN_DURATION_MINUTES,
  VISIT_TIME_LATEST_MINUTES,
);
/** 「時刻を指定」を選んだときの既定の開始。 */
export const DEFAULT_CUSTOM_START_TIME = "10:00";
/** 「時刻を指定」を選んだときの既定の終了。 */
export const DEFAULT_CUSTOM_END_TIME = "12:00";

/* ---------------------------------------------------------------------------
 * メッセージ meta の読み分け（実行時の型ガード）
 * ------------------------------------------------------------------------- */

/** 1回の提示で送れる候補の上限（backend の candidates の max_length と同じ）。 */
export const MAX_SCHEDULE_CANDIDATES = 10;

/** サーバーが作った候補1件（schedule_proposal の meta v2 の candidates の要素）。 */
export interface ScheduleCandidate {
  date: string;
  start: string | null;
  end: string | null;
  label: string;
}

/**
 * schedule_proposal の meta を版ごとに読み分けた結果。
 * - version 2: {v:2, seq, candidates:[{date,start,end,label}]}（確定できるのは seq が最大の提示だけ）
 * - version 1: 旧形式 {slots:[...]}（業者の自由記述。表示だけで、確定は日程調整ページへ案内する）
 * - unknown: 上のどちらにも当てはまらない（未知の版・壊れたデータ）
 */
export type ParsedScheduleProposal =
  | { version: 2; seq: number; candidates: ScheduleCandidate[] }
  | { version: 1; slots: string[] }
  | { version: "unknown" };

/** 配列でも null でもない素のオブジェクトか。 */
function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** v2 の候補1件を検査して取り出す。1項目でも規則に合わなければ null。 */
function parseScheduleCandidate(raw: unknown): ScheduleCandidate | null {
  if (!isPlainRecord(raw)) return null;
  const { date, start, end, label } = raw;
  if (typeof date !== "string" || !isValidIsoDate(date)) return null;
  if (!(start === null || typeof start === "string") || !(end === null || typeof end === "string")) return null;
  if (!isValidVisitTimeRange(start, end)) return null;
  if (typeof label !== "string" || label.trim() === "") return null;
  return { date, start, end, label };
}

/**
 * schedule_proposal の meta を実行時に検査して版ごとに読み分ける。
 * v2 は候補が1件でも規則に合わなければ全体を unknown にする（一部だけ捨てると添字がずれ、
 * accept API の candidate_index が別の候補を指してしまうため）。
 */
export function parseScheduleProposalMeta(meta: unknown): ParsedScheduleProposal {
  if (!isPlainRecord(meta)) return { version: "unknown" };
  if (meta.v === 2) {
    const { seq, candidates } = meta;
    if (typeof seq !== "number" || !Number.isSafeInteger(seq) || seq < 1) return { version: "unknown" };
    if (!Array.isArray(candidates) || candidates.length < 1 || candidates.length > MAX_SCHEDULE_CANDIDATES) {
      return { version: "unknown" };
    }
    const parsed: ScheduleCandidate[] = [];
    for (const raw of candidates) {
      const candidate = parseScheduleCandidate(raw);
      if (!candidate) return { version: "unknown" };
      parsed.push(candidate);
    }
    return { version: 2, seq, candidates: parsed };
  }
  if (meta.v === undefined && Array.isArray(meta.slots)) {
    return { version: 1, slots: meta.slots.filter((slot): slot is string => typeof slot === "string") };
  }
  return { version: "unknown" };
}

/**
 * 確定できる「最新の提示」の id。v2 の seq が最大のもの（サーバーの superseded 判定
 * `proposal.seq != MAX(seq)` と同じ定義。件数や created_at では判定しない）。
 * v1・unknown・schedule_proposal 以外は数えない。v2 が1件も無ければ null。
 * 同じ seq が複数ある場合（サーバーはロック下で採番するため起きない想定）は配列で後ろのものを採る。
 */
export function latestProposalId(messages: readonly { id: string; kind: string; meta: unknown }[]): string | null {
  let latestId: string | null = null;
  let latestSeq = 0;
  for (const message of messages) {
    if (message.kind !== "schedule_proposal") continue;
    const parsed = parseScheduleProposalMeta(message.meta);
    if (parsed.version !== 2) continue;
    if (parsed.seq >= latestSeq) {
      latestSeq = parsed.seq;
      latestId = message.id;
    }
  }
  return latestId;
}

/**
 * schedule_confirmed の meta を版ごとに読み分けた結果。
 * - version 2: {v:2, source, visit_date, visit_time_slot, label, confirmed_by, ...}（帯には label を出す）
 * - version 1: 旧形式 {visit_date, visit_time_slot}（本文に業者の文字列が入りうるため、帯には
 *   本文の制御文字を除去して出す）
 * - unknown: どちらにも当てはまらない
 */
export type ParsedScheduleConfirmed =
  | {
      version: 2;
      label: string;
      visitDate: string;
      visitTimeSlot: string;
      source: "proposal" | "calendar" | null;
      confirmedBy: "user" | "admin" | null;
    }
  | { version: 1; visitDate: string | null; visitTimeSlot: string | null }
  | { version: "unknown" };

/** schedule_confirmed の meta を実行時に検査して版ごとに読み分ける。 */
export function parseScheduleConfirmedMeta(meta: unknown): ParsedScheduleConfirmed {
  if (!isPlainRecord(meta)) return { version: "unknown" };
  const visitDate = typeof meta.visit_date === "string" ? meta.visit_date : null;
  const visitTimeSlot = typeof meta.visit_time_slot === "string" ? meta.visit_time_slot : null;
  if (meta.v === 2) {
    const { label, source, confirmed_by: confirmedBy } = meta;
    if (typeof label !== "string" || label.trim() === "" || visitDate === null || visitTimeSlot === null) {
      return { version: "unknown" };
    }
    return {
      version: 2,
      label,
      visitDate,
      visitTimeSlot,
      source: source === "proposal" || source === "calendar" ? source : null,
      confirmedBy: confirmedBy === "user" || confirmedBy === "admin" ? confirmedBy : null,
    };
  }
  if (meta.v === undefined && (visitDate !== null || visitTimeSlot !== null)) {
    return { version: 1, visitDate, visitTimeSlot };
  }
  return { version: "unknown" };
}
