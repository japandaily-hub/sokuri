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

/** 希望時間帯（訪問日程調整ページ・業者の候補日提案フォームで共有する唯一の情報源）。 */
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

/** ISO日付（"YYYY-MM-DD"）とその月日を抽出する正規表現。年は任意（無ければ繰り上げ推定）。 */
const SLOT_DATE_PATTERN = /(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日/;

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
 * 「月」「日」の数字パターンのみに依存し、抽出できない場合は null を返す
 * （呼び出し側でエラー表示にフォールバックする）。
 *
 * - 年が明記されている場合: その年を使い、実在する日付か検証する（2月30日等は null）。
 *   過去日でも解析自体は成功する（過去日かどうかの判定は呼び出し側の責務）。
 * - 年が無い場合（旧形式）: today 以降で直近に来る年を採用する
 *   （月が today の月より前なら来年扱いにする、旧仕様との後方互換のための繰り上げ推定）。
 *
 * today は年月日の比較にのみ使う（時刻は無視する）。
 */
export function parseSlotDate(label: string, today: Date): string | null {
  const m = SLOT_DATE_PATTERN.exec(label);
  if (!m) return null;
  const month = Number(m[2]);
  const day = Number(m[3]);
  if (!Number.isInteger(month) || !Number.isInteger(day) || month < 1 || month > 12 || day < 1 || day > 31) {
    return null;
  }

  if (m[1]) {
    const year = Number(m[1]);
    const d = new Date(year, month - 1, day);
    if (d.getFullYear() !== year || d.getMonth() !== month - 1 || d.getDate() !== day) return null;
    return toIsoDateString(d);
  }

  let year = today.getFullYear();
  const candidateThisYear = new Date(year, month - 1, day);
  const todayMidnight = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  if (candidateThisYear < todayMidnight) year += 1;
  const candidate = new Date(year, month - 1, day);
  // 4月31日・平年の2月29日等、繰り上げ推定で決めた年に実在しない月日は null を返す
  // （年ありの分岐と同じ実在チェックを行う。年の決定を先に済ませてから判定することで、
  // 「今年は平年だが繰り上げ先の来年はうるう年」のようなケースも正しく扱える）。
  if (candidate.getFullYear() !== year || candidate.getMonth() !== month - 1 || candidate.getDate() !== day) {
    return null;
  }
  return toIsoDateString(candidate);
}
