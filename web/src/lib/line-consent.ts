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
