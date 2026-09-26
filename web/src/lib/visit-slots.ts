/**
 * 訪問日程の候補ラベル（例: "2026年10月15日（木）9:00〜12:00"）に関する純関数群。
 *
 * 元は以下の2箇所に重複実装されていた（判断パターン⑩ 隣接・複製伝播の是正）。
 * - web/src/components/kdz/ChatPanel.tsx（依頼者向け: 候補日確定の解析）
 * - web/src/app/schedule/page.tsx（依頼者向け: 日程調整ページの候補日ハイライト）
 * 加えて web/src/app/operator/chat/[id]/page.tsx（業者向け: 候補日提案フォームのラベル生成）
 * でも同じ「月日パターンの抽出／年の推定」ロジックが必要になるため、ここへ一本化する。
 *
 * @/ の import を持たない純関数のみを置く（node --test でアプリ全体を起動せず単体検証するため）。
 * 単体テスト: src/lib/visit-slots.test.mts（review-verdict.test.mts と同じ node --test 流儀）。
 */

/**
 * 希望時間帯（訪問日程調整ページ・業者の候補日提案フォームで共有する唯一の情報源）。
 * value は backend/app/schemas_katadzuke.py の SCHEDULE_FIXED_TIME_SLOTS と 1文字違わず
 * 一致させること（不一致だと日程調整ページからの日程確定が 422 になる。backend の
 * tests/test_schedule_input_validation.py がこのファイルを読んで両者の一致を検査する）。
 */
export const VISIT_TIME_SLOTS: { value: string; label: string }[] = [
  { value: "9:00〜12:00", label: "午前" },
  { value: "12:00〜15:00", label: "昼" },
  { value: "15:00〜18:00", label: "午後" },
  { value: "18:00〜21:00", label: "夜" },
  { value: "時間指定なし", label: "業者に一任" },
];

const DOW_LABELS = ["日", "月", "火", "水", "木", "金", "土"] as const;

/**
 * 候補日ラベルの最大文字数（backend ScheduleConfirmRequest.visit_time_slot の列長上限の写し。
 * REVIEW_COMMENT_MAX と同じ「フロントに定数を持ち、backend の制約とズレたら手動で追随する」前例）。
 * 年入りラベル（例: "2026年10月15日（木）18:00〜21:00"）は最大でも26字程度で収まるが、
 * 旧仕様の自由入力データ（32字超）を確定前に弾くための上限としても使う。
 */
export const VISIT_TIME_SLOT_MAX_LENGTH = 32;

/**
 * 候補日ラベルから「(YYYY年)M月D日」を抽出する正規表現。年は任意（無ければ繰り上げ推定）。
 * NFKC 正規化した文字列に当て、ASCII の [0-9] のみを数字とみなし、数字と「年」「月」「日」の
 * 間の空白を許容する（backend の transactions._SLOT_DATE_PATTERN と同じ形。backend が
 * 照合に使う月日・年と、ここで読み取って送る visit_date が食い違わないようにする。
 * 日程検証レビュー SEC-I1/SEC-I4/QA-M4）。
 */
const SLOT_DATE_PATTERN = /(?:([0-9]{4})\s*年\s*)?([0-9]+)\s*月\s*([0-9]+)\s*日/;

/** year 年 month 月 day 日が暦の上で実在するか（2月30日・平年の2月29日等は false）。 */
function existsOnCalendar(year: number, month: number, day: number): boolean {
  const d = new Date(year, month - 1, day);
  return d.getFullYear() === year && d.getMonth() === month - 1 && d.getDate() === day;
}

/**
 * Date（ローカルタイムの年月日）を "YYYY-MM-DD" に整形する。
 * new Date(isoString) の UTC 解釈によるズレを避けるため、年月日の各フィールドから直接組み立てる。
 */
export function toIsoDateString(d: Date): string {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/**
 * ISO日付（"YYYY-MM-DD"）と時間帯の値から候補日ラベルを生成する
 * （例: formatSlotLabel("2026-10-15", "9:00〜12:00") → "2026年10月15日（木）9:00〜12:00"）。
 * 曜日は new Date(y, m-1, d)（ローカルタイムのコンストラクタ引数形式）で求め、
 * new Date(isoString) は使わない（UTC 解釈されると JST では前日にずれる場合があるため）。
 * 日付と時間の間に空白は入れない。isoDate が "YYYY-MM-DD" 形式でない、または実在しない日付
 * （例: 2月30日）の場合は空文字を返す。
 */
export function formatSlotLabel(isoDate: string, timeValue: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate);
  if (!m) return "";
  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = Number(m[3]);
  const d = new Date(year, month - 1, day);
  if (d.getFullYear() !== year || d.getMonth() !== month - 1 || d.getDate() !== day) return "";
  return `${year}年${month}月${day}日（${DOW_LABELS[d.getDay()]}）${timeValue}`;
}

/**
 * 業者が提示・入力した候補日ラベル（新形式 "2026年10月15日（木）9:00〜12:00"、
 * 旧形式 "10月15日（木）9:00〜12:00" のいずれも対象）から ISO日付（"YYYY-MM-DD"）を抽出する。
 * ラベルを NFKC 正規化してから SLOT_DATE_PATTERN の最初の一致を使うため、全角数字
 * 「１０月１日」や合字「㋉」「㏠」、「10月 1日」のような空白入りも読める。
 * 抽出できない場合は null を返す（呼び出し側でエラー表示にフォールバックする）。
 *
 * - 年が明記されている場合: その年を使い、実在する日付か検証する（2月30日等は null）。
 *   過去日でも解析自体は成功する（過去日かどうかの判定は呼び出し側の責務）。
 * - 年が無い場合（旧形式）: today の年→翌年の順に、その年で実在し、かつ today 以降になる
 *   最初の年を採用する（どちらでも満たさなければ null）。年を先に1つに決めてから実在を
 *   確かめると、2月29日の候補で平年/うるう年の境目をまたいだときに解析失敗・存在しない
 *   日付の送信が起きるため、年ごとに実在を確かめ直す（日程検証レビュー SEC-N3 / QA-R-M1）。
 *
 * today は年月日の比較にのみ使う（時刻は無視する）。
 */
export function parseSlotDate(label: string, today: Date): string | null {
  const m = SLOT_DATE_PATTERN.exec(label.normalize("NFKC"));
  if (!m) return null;
  const month = Number(m[2]);
  const day = Number(m[3]);
  if (!Number.isInteger(month) || !Number.isInteger(day) || month < 1 || month > 12 || day < 1 || day > 31) {
    return null;
  }

  if (m[1]) {
    const year = Number(m[1]);
    return existsOnCalendar(year, month, day) ? toIsoDateString(new Date(year, month - 1, day)) : null;
  }

  const todayMidnight = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  for (const year of [today.getFullYear(), today.getFullYear() + 1]) {
    if (!existsOnCalendar(year, month, day)) continue;
    const candidate = new Date(year, month - 1, day);
    if (candidate < todayMidnight) continue;
    return toIsoDateString(candidate);
  }
  return null;
}
