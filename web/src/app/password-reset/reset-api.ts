/** パスワード再設定 API（無認証）の呼び出し。/password-reset と /password-reset/confirm だけが使う。
 *
 *  ログイン前の画面から呼ぶため Authorization を付けず、401 のセッション失効処理
 *  （katadzuke-api の request()）も通さない。エラーは既存の KdzApiError / KdzNetworkError に揃え、
 *  backend の detail（文字列、または {code, message}）は、日本語の 4xx のときだけ利用者向けの文言として使う。 */

import { KdzApiError, KdzNetworkError, apiBase, createTimeoutSignal } from "@/lib/katadzuke-api";
import {
  RESET_DEFAULT_ERROR_MESSAGE,
  resolveResetErrorMessage,
  toResetAccountType,
  type ResetAccountType,
} from "@/lib/password-reset";

export { toResetAccountType };
export type { ResetAccountType };

/** 新しいパスワードの要件（backend の PasswordResetConfirmRequest・登録・変更と同じ 8〜128 文字）。 */
export const RESET_PASSWORD_MIN_LENGTH = 8;
export const RESET_PASSWORD_MAX_LENGTH = 128;

const REQUEST_TIMEOUT_MS = 15_000;

async function postJson<T>(path: string, payload: Record<string, string>): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${apiBase()}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      // 再設定のリンク（token 入りの URL）を外部へ送らない（ページ側の no-referrer に加えた多層防御）。
      referrerPolicy: "no-referrer",
      signal: createTimeoutSignal(REQUEST_TIMEOUT_MS),
    });
  } catch (e) {
    throw new KdzNetworkError(e);
  }
  if (!res.ok) {
    let message = RESET_DEFAULT_ERROR_MESSAGE;
    let code: string | undefined;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        message = body.detail;
      } else if (body.detail && typeof body.detail === "object" && !Array.isArray(body.detail)) {
        const detail = body.detail as { code?: unknown; message?: unknown };
        if (typeof detail.code === "string") code = detail.code;
        if (typeof detail.message === "string") message = detail.message;
      }
    } catch {
      /* JSON でない応答は既定の文言のまま */
    }
    // 404／5xx・日本語を含まない detail（"Not Found" 等）は利用者へそのまま見せず既定の文言にする（QA M3）。
    throw new KdzApiError(res.status, resolveResetErrorMessage(res.status, message), code);
  }
  try {
    return (await res.json()) as T;
  } catch (e) {
    throw new KdzNetworkError(e);
  }
}

/** 再設定の案内メールを依頼する。登録の有無にかかわらず backend は同じ 202 を返す。 */
export function requestPasswordReset(email: string, accountType: ResetAccountType): Promise<{ detail: string }> {
  return postJson("/auth/password-reset/request", { email, account_type: accountType });
}

/** メールのリンクの token で新しいパスワードを設定する（1回限り）。 */
export function confirmPasswordReset(
  token: string,
  accountType: ResetAccountType,
  newPassword: string,
): Promise<{ detail: string }> {
  return postJson("/auth/password-reset/confirm", {
    token,
    account_type: accountType,
    new_password: newPassword,
  });
}
