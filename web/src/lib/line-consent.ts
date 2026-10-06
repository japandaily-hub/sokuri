/**
 * LINE ログイン／登録ボタンの「明示の同意」判定（React・他モジュール非依存の純関数）。
 *
 * 背景（2周目監査 N-2・N-9）: LINE ログインはバックエンド /auth/line/exchange で、未登録の LINE
 * アカウントならその場で依頼者アカウントを新規作成する（web/src/auth.ts 冒頭の「新規登録/ログイン」、
 * backend auth の LINE 交換処理）。つまり /login の LINE ボタンも実質の新規登録を兼ねる。
 * そこで /signup・/login とも、メール登録フォームと同じく「利用規約・プライバシーポリシーに同意します」の
 * 必須チェックを LINE ボタンの上に置き、チェックするまでボタンを押せないようにする
 * （「続行すると同意したものとみなします」のみなし同意はやめる）。
 *
 * 判定をここに切り出し、画面（components/kdz/auth.tsx の LineConsentAuth）は結果を描くだけにする。
 */

/** 同意前に、無効化したボタンの理由として示す文言（aria-describedby でボタンと結ぶ）。 */
export const LINE_CONSENT_REQUIRED_HINT =
  "利用規約とプライバシーポリシーへの同意にチェックを入れると、LINEのボタンを押せます。";

export interface LineAuthGateState {
  /** 同意のチェックボックスがオンか。 */
  agreed: boolean;
  /** LINE の認可画面へ遷移中か（二重押し防止）。 */
  busy: boolean;
}

/**
 * LINE の認可フローを始めてよいか。
 * 同意済みかつ遷移中でないときだけ true。値は厳密に boolean の true のみを同意とみなす
 * （未定義・文字列などの取り違えで同意扱いにしない）。
 */
export function canStartLineAuth(state: LineAuthGateState): boolean {
  return state.agreed === true && state.busy !== true;
}

/**
 * ボタンの下に出す補足文。未同意のときだけ理由を返し、同意後は null（表示しない）。
 * 遷移中は理由を出さない（押した後に「同意してください」と出ると誤解を招くため）。
 */
export function lineConsentHint(state: LineAuthGateState): string | null {
  if (state.busy === true) return null;
  return state.agreed === true ? null : LINE_CONSENT_REQUIRED_HINT;
}

// ---------------------------------------------------------------------------
// 同意の値をサーバー（backend /auth/line/exchange）へ届ける（3周目の法務監査・中）
//
// 背景: 同意の判定が画面のチェックボックスだけで、サーバーに記録されていなかった。backend は
// 未登録の LINE アカウントから依頼者を新規作成するときだけ `agreed_terms: true` を必須にし、
// 版数と日時を保存する（既存ユーザーのログインでは見ない）。
//
// 経路の設計: LINE の交換は OAuth のコールバック（/api/auth/callback/line）で動く auth.ts の
// signIn コールバックが行い、ボタンを押した画面の状態は届かない。そこでボタンを押した時点
// （同意済みのときだけ押せる）で、短命の Cookie に「同意した規約の版数」を置き、コールバックで
// 読んで交換のリクエストに `agreed_terms: true`・`terms_version` として載せる。
// - Path=/api/auth: コールバックにだけ送る（他の画面の要求には載せない）。
// - SameSite=Lax: LINE からのトップレベルの GET 遷移では送られる。Max-Age=600（10分）で自然に消える。
// - 中身は版数（日付）だけで個人情報を含まない。利用者自身が書き換え得るが、同意は本人の意思表示
//   そのもので、他サイトからは当サイトの Cookie を書けない（*.vercel.app は Public Suffix List 登録済み）。
// - 値の形式（YYYY-MM-DD）を満たさなければ「同意なし」として扱う（未登録なら backend が 422）。
// ---------------------------------------------------------------------------

/**
 * 依頼者向け利用規約・プライバシーポリシーの現行の版数（/terms・/privacy の「最終改定」の日付）。
 * backend の CURRENT_USER_TERMS_VERSION（app/schemas_katadzuke.py）と同じ値に揃える
 * （食い違っても登録は通り、記録はサーバーの版数。backend は食い違いを INFO に残す）。
 */
export const USER_TERMS_VERSION = "2026-10-06";

/** 同意の版数を運ぶ Cookie の名前。 */
export const LINE_TERMS_CONSENT_COOKIE = "kdz_line_terms";

/** Cookie の有効期間（秒）。LINE の認可画面（友だち追加の確認を含む）を往復する間だけ持てばよい。 */
export const LINE_TERMS_CONSENT_MAX_AGE_SECONDS = 600;

/** NextAuth のルート（コールバックを含む）。Cookie はここにだけ送る。 */
const LINE_TERMS_CONSENT_COOKIE_PATH = "/api/auth";

const TERMS_VERSION_RE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * 同意したときに document.cookie へ代入する文字列を作る。
 * @param secure https で配信しているか（true なら Secure を付ける。ローカルの http では付けない）
 */
export function buildLineTermsConsentCookie(secure: boolean): string {
  const attrs = [
    `${LINE_TERMS_CONSENT_COOKIE}=${USER_TERMS_VERSION}`,
    `Path=${LINE_TERMS_CONSENT_COOKIE_PATH}`,
    `Max-Age=${LINE_TERMS_CONSENT_MAX_AGE_SECONDS}`,
    "SameSite=Lax",
  ];
  if (secure) attrs.push("Secure");
  return attrs.join("; ");
}

/** 使い終わった Cookie を消すときの文字列（同じ Path で Max-Age=0）。 */
export function clearLineTermsConsentCookie(): string {
  return `${LINE_TERMS_CONSENT_COOKIE}=; Path=${LINE_TERMS_CONSENT_COOKIE_PATH}; Max-Age=0; SameSite=Lax`;
}

/** LINE 交換のリクエスト本文に足す同意の項目。 */
export type LineExchangeConsentFields = { agreed_terms: true; terms_version: string } | Record<string, never>;

/**
 * コールバックで読んだ Cookie の値から、LINE 交換の本文に足す項目を決める。
 * 形式（YYYY-MM-DD）を満たす文字列のときだけ同意として `agreed_terms: true` を返し、
 * それ以外（未設定・空・形式違い・文字列以外）は空（＝同意を送らない）を返す。
 */
export function lineExchangeConsentFields(cookieValue: unknown): LineExchangeConsentFields {
  if (typeof cookieValue !== "string" || !TERMS_VERSION_RE.test(cookieValue)) return {};
  return { agreed_terms: true, terms_version: cookieValue };
}

/** backend が「新規作成に同意が必要」で拒否したときの detail.code（auth.py の TERMS_AGREEMENT_REQUIRED_CODE）。 */
export const TERMS_AGREEMENT_REQUIRED_CODE = "terms_agreement_required";

/** 同意なしで LINE の新規登録が拒否されたときに /login へ付ける reason の値と、画面に出す案内。 */
export const LINE_TERMS_REQUIRED_REASON = "terms_required";
export const LINE_TERMS_REQUIRED_MESSAGE =
  "LINEで初めてご利用の方は、利用規約とプライバシーポリシーへの同意が必要です。同意のチェックを入れてから、もう一度LINEのボタンを押してください。";
