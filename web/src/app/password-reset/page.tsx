"use client";

/** パスワード再設定の手続き（/password-reset）。
 *  登録メールアドレスと種別（依頼者／業者）を送ると、登録がある場合だけ backend が再設定の案内メールを送る。
 *  登録の有無は画面に出さない（backend も常に同じ 202 を返す）。送信後は常に同じ案内を表示する。
 *  業者ログインからは ?type=operator 付きで来るため、種別の初期値に使う。 */

import { Suspense, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { KdzLogo } from "@/components/kdz/Logo";
import { Field } from "@/components/kdz/auth";
import { KdzApiError } from "@/lib/katadzuke-api";
import { requestPasswordReset, toResetAccountType, type ResetAccountType } from "./reset-api";
import "./password-reset.css";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const SENT_MESSAGE = "入力されたアドレスが登録されている場合は、再設定の案内を送りました。";

function PasswordResetRequestForm() {
  const searchParams = useSearchParams();
  const [accountType, setAccountType] = useState<ResetAccountType>(() =>
    toResetAccountType(searchParams.get("type")),
  );
  const [email, setEmail] = useState("");
  const [emailErr, setEmailErr] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  const loginHref = accountType === "operator" ? "/operator/login" : "/login";

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    const trimmed = email.trim();
    if (!EMAIL_RE.test(trimmed)) {
      setEmailErr("メールアドレスの形式で入力してください");
      return;
    }
    setEmailErr(null);
    setError(null);
    setBusy(true);
    try {
      await requestPasswordReset(trimmed, accountType);
      setSent(true);
    } catch (err) {
      // 429（回数の上限）・入力の形式エラーは backend の文言を出す。通信の失敗は再試行を促す。
      setError(
        err instanceof KdzApiError
          ? err.message
          : "通信に失敗しました。電波の状況を確かめて、もう一度お試しください。",
      );
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <div className="reset-card" role="status">
        <div className="sent-ic" aria-hidden="true">
          <svg viewBox="0 0 24 24">
            <rect x="3" y="5" width="18" height="14" />
            <path d="M3 7l9 6 9-6" />
          </svg>
        </div>
        <h1 className="reset-panel-title">メールをご確認ください</h1>
        <p className="reset-panel-sub">{SENT_MESSAGE}</p>
        <div className="reset-note">
          メールのリンクから30分以内に新しいパスワードを設定してください。リンクは1回だけ使えます。
          届かない場合は、迷惑メールフォルダもご確認のうえ、少し時間をおいてからもう一度お試しください。
        </div>
        <Link href={loginHref} className="btn btn-primary btn-block btn-lg">
          ログインに戻る
        </Link>
      </div>
    );
  }

  return (
    <div className="reset-card reset-wrap">
      <h1 className="reset-panel-title">パスワードの再設定</h1>
      <p className="reset-panel-sub">
        ご登録のメールアドレスを入力してください。新しいパスワードを設定するためのリンクをお送りします。
      </p>

      {error ? (
        <div className="auth-error" role="alert">
          {error}
        </div>
      ) : null}

      <form onSubmit={onSubmit} noValidate>
        <fieldset className="reset-type">
          <legend>アカウントの種類</legend>
          <label>
            <input
              type="radio"
              name="account-type"
              value="user"
              checked={accountType === "user"}
              onChange={() => setAccountType("user")}
            />
            ご依頼の方
          </label>
          <label>
            <input
              type="radio"
              name="account-type"
              value="operator"
              checked={accountType === "operator"}
              onChange={() => setAccountType("operator")}
            />
            業者の方
          </label>
        </fieldset>

        <Field label="メールアドレス" htmlFor="reset-email" error={emailErr}>
          <input
            type="email"
            id="reset-email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="example@email.com"
            autoComplete="email"
            inputMode="email"
            maxLength={254}
            required
          />
        </Field>

        <button type="submit" className="btn btn-primary btn-block btn-lg" disabled={busy}>
          {busy ? "送信中…" : "再設定の案内を送る"}
        </button>
      </form>

      <div className="reset-back">
        <Link href={loginHref}>ログインに戻る</Link>
      </div>
    </div>
  );
}

export default function PasswordResetPage() {
  return (
    <main id="main" className="reset-page">
      {/* N-10/H-6（2周目監査）: スキップリンク（#main）の飛び先と、ページの主題の h1 を持たせる。 */}
      <Link href="/" className="reset-logo" aria-label="カタヅケ トップへ">
        <KdzLogo size={22} />
      </Link>
      <Suspense fallback={null}>
        <PasswordResetRequestForm />
      </Suspense>
    </main>
  );
}
