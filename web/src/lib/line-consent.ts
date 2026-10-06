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
// - http（ローカル）: Path=/api/auth でコールバックにだけ送る（他の画面の要求には載せない）。
//   https: `__Host-kdz_line_terms`（Secure・Path=/・Domain 無し）。`__Host-` は Path=/ が必須のため全要求に載るが、
//   中身は版数の日付だけで、10分で消え、コールバックが読んだ直後に消す（security L-1）。
// - SameSite=Lax: LINE からのトップレベルの GET 遷移では送られる。Max-Age=600（10分）で自然に消える。
// - 中身は版数（日付）だけで個人情報を含まない。利用者自身が書き換え得るが、同意は本人の意思表示
//   そのもので、他サイトからは当サイトの Cookie を書けない（*.vercel.app は Public Suffix List 登録済み）。
// - 値の形式（YYYY-MM-DD）を満たさなければ「同意なし」として扱う（未登録なら backend が 422）。
// ---------------------------------------------------------------------------

/**
 * 依頼者向け利用規約・プライバシーポリシーの現行の版数（/terms・/privacy の「最終改定」の日付）。
 * backend の CURRENT_USER_TERMS_VERSION（app/schemas_katadzuke.py）と同じ値に揃える
 * （食い違うと backend は 409 `terms_version_outdated` で新規登録を止める。版数を送らない旧画面は現行版として記録して通す）。
 */
export const USER_TERMS_VERSION = "2026-10-06";

/**
 * 同意の版数を運ぶ Cookie の名前（http＝ローカル開発の従来名）。
 * https では `__Host-` 接頭辞付き（{@link lineTermsConsentCookieName}）。`__Host-` の Cookie は
 * Secure・Path=/・Domain 無しが必須で、兄弟サブドメインや http 経由の上書き（Cookie tossing）を受け付けない（security L-1）。
 */
export const LINE_TERMS_CONSENT_COOKIE = "kdz_line_terms";

/** https のときの Cookie 名（`__Host-` 接頭辞）。 */
export const LINE_TERMS_CONSENT_COOKIE_SECURE = `__Host-${LINE_TERMS_CONSENT_COOKIE}`;

/** 配信が https かどうかで Cookie 名を決める。 */
export function lineTermsConsentCookieName(secure: boolean): string {
  return secure ? LINE_TERMS_CONSENT_COOKIE_SECURE : LINE_TERMS_CONSENT_COOKIE;
}

/** Cookie の Path。`__Host-` は Path=/ が必須。http（ローカル）は従来どおり NextAuth のルートだけ。 */
export function lineTermsConsentCookiePath(secure: boolean): string {
  return secure ? "/" : LINE_TERMS_CONSENT_COOKIE_PATH;
}

/**
 * サーバー側で「受信したリクエストは https か」を判定する（auth.ts 用）。
 * リバースプロキシ配下では x-forwarded-proto の先頭の値、無ければ AUTH_URL の接頭辞で決める。
 */
export function isSecureRequest(forwardedProto: string | null | undefined, authUrl: string | null | undefined): boolean {
  if (typeof forwardedProto === "string" && forwardedProto.trim() !== "") {
    return forwardedProto.split(",")[0].trim().toLowerCase() === "https";
  }
  return typeof authUrl === "string" && authUrl.trim().toLowerCase().startsWith("https://");
}

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
    `${lineTermsConsentCookieName(secure)}=${USER_TERMS_VERSION}`,
    `Path=${lineTermsConsentCookiePath(secure)}`,
    `Max-Age=${LINE_TERMS_CONSENT_MAX_AGE_SECONDS}`,
    "SameSite=Lax",
  ];
  if (secure) attrs.push("Secure");
  return attrs.join("; ");
}

/** 使い終わった Cookie を消すときの文字列（同じ名前・同じ Path で Max-Age=0）。 */
export function clearLineTermsConsentCookie(secure: boolean = false): string {
  const base = `${lineTermsConsentCookieName(secure)}=; Path=${lineTermsConsentCookiePath(secure)}; Max-Age=0; SameSite=Lax`;
  return secure ? `${base}; Secure` : base;
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

/** 画面が送った規約の版数が現行と食い違うときの 409 の detail.code（auth.py の TERMS_VERSION_OUTDATED_CODE）。登録済みメールの 409 と取り違えない。 */
export const TERMS_VERSION_OUTDATED_CODE = "terms_version_outdated";

/** 規約が更新されたときの案内（再読み込みで新しい版の画面に変わる）。 */
export const TERMS_VERSION_OUTDATED_MESSAGE = "利用規約が更新されています。ページを再読み込みして、もう一度お試しください。";

/** 同意なしで LINE の新規登録が拒否されたときに /login へ付ける reason の値と、画面に出す案内。 */
export const LINE_TERMS_REQUIRED_REASON = "terms_required";

/** LINE 交換が規約の版数の食い違い（409）で拒否されたときに /login へ戻す理由。再読み込みを案内する。 */
export const LINE_TERMS_OUTDATED_REASON = "terms_outdated";
export const LINE_TERMS_REQUIRED_MESSAGE =
  "LINEで初めてご利用の方は、利用規約とプライバシーポリシーへの同意が必要です。同意のチェックを入れてから、もう一度LINEのボタンを押してください。";
