"use client";

/** ユーザーログイン（新デザイン）。admin も同じフォーム（role で /admin へ誘導）。
 *  認証は既存の NextAuth Credentials（user-credentials → backend JWT）を維持。 */

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { signIn } from "next-auth/react";
import { AuthBar, Field, PasswordField, LineAuthButton, TrustRow } from "@/components/kdz/auth";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const callbackUrl = params.get("callbackUrl") ?? "/cases";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [emailErr, setEmailErr] = useState<string | null>(null);
  const [pwErr, setPwErr] = useState<string | null>(null);
  const [authErr, setAuthErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setAuthErr(null);
    let ok = true;
    if (!email || !email.includes("@")) {
      setEmailErr("メールアドレスを正しく入力してください");
      ok = false;
    } else setEmailErr(null);
    if (!password || password.length < 8) {
      setPwErr("パスワードを8文字以上で入力してください");
      ok = false;
    } else setPwErr(null);
    if (!ok) return;

    setBusy(true);
    const res = await signIn("user-credentials", { email, password, redirect: false });
    setBusy(false);
    if (res?.error) {
      setAuthErr("メールアドレスまたはパスワードが正しくありません");
      return;
    }
    router.push(callbackUrl);
    router.refresh();
  }

  return (
    <div className="auth-page">
      <AuthBar rightHref="/signup" rightLabel="新規登録はこちら →" />
      <main id="main">
        <div className="auth-wrap">
          <div className="auth-card">
            <div className="auth-head">
              <h1 className="auth-title">ログイン</h1>
              <p className="auth-sub">入札状況や業者との交渉はログイン後に確認できます</p>
            </div>

            <LineAuthButton />

            <div className="auth-divider">メールアドレスで続ける</div>

            {authErr ? (
              <div className="auth-error">
                <svg viewBox="0 0 24 24" style={{ width: 16, height: 16, fill: "none", stroke: "#cc3333", strokeWidth: 2, strokeLinecap: "round", flexShrink: 0 }}>
                  <circle cx="12" cy="12" r="9" />
                  <path d="M12 8v4M12 16h.01" />
                </svg>
                {authErr}
              </div>
            ) : null}

            <form onSubmit={onSubmit} noValidate>
              <Field label="メールアドレス" htmlFor="inp-email" error={emailErr}>
                <input
                  type="email"
                  id="inp-email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="example@email.com"
                  autoComplete="email"
                  inputMode="email"
                />
              </Field>
              <Field
                label="パスワード"
                htmlFor="inp-pw"
                error={pwErr}
                rightSlot={
                  <Link href="/password-reset" className="forget-link">
                    パスワードを忘れた方
                  </Link>
                }
              >
                <PasswordField id="inp-pw" value={password} onChange={setPassword} />
              </Field>

              <button
                type="submit"
                className="btn btn-primary btn-block btn-lg"
                style={{ marginTop: 4 }}
                disabled={busy}
              >
                {busy ? (
                  <>
                    <span className="spinning">↻</span> ログイン中…
                  </>
                ) : (
                  "ログイン"
                )}
              </button>
            </form>

            <TrustRow />
          </div>

          <div className="auth-switch">
            アカウントをお持ちでない方は
            <br />
            <Link href="/signup">無料で新規登録する →</Link>
          </div>
          <div className="auth-switch" style={{ marginTop: 10 }}>
            業者の方は <Link href="/operator/login">業者ログイン →</Link>
          </div>
        </div>
      </main>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
