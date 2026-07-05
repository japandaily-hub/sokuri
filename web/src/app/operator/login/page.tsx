"use client";

/**
 * 業者ログイン（/operator/login）。
 *
 * デザインレビュー B-3 対応: 旧 slate 系 AuthCard（components/AuthCard.tsx）を廃し、
 * ユーザー側 /login と同じ視覚言語（AuthBar/auth-card/Field/PasswordField、
 * katazuke-pages.css）に統一。BUYER タグでアカウント種別を明示する。
 * 認証ロジック（signIn("operator-credentials")・callbackUrl・オープンリダイレクト対策）は変更していない。
 */

import "../operator-auth.css";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { signIn } from "next-auth/react";
import { AuthBar, Field, PasswordField } from "@/components/kdz/auth";
import { safeInternalPath } from "@/lib/safe-path";

function OperatorLoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  // オープンリダイレクト対策: サイト内パスのみ許可
  const callbackUrl = safeInternalPath(params.get("callbackUrl"), "/operator/cases");

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const res = await signIn("operator-credentials", { email, password, redirect: false });
    setBusy(false);
    if (res?.error) {
      setError("ログインに失敗しました。メール・パスワード・アカウント状態をご確認ください。");
      return;
    }
    router.push(callbackUrl);
    router.refresh();
  }

  return (
    <div className="auth-page operator-auth">
      <AuthBar rightHref="/operator/signup" rightLabel="業者登録はこちら →" />
      <main id="main">
        <div className="auth-wrap">
          <div className="auth-card">
            <div className="auth-head">
              <span className="buyer-tag">BUYER</span>
              <h1 className="auth-title">業者ログイン</h1>
              <p className="auth-sub">登録業者さま向けの管理画面に入ります。</p>
            </div>

            {error ? (
              <div className="auth-error">
                <svg viewBox="0 0 24 24" style={{ width: 16, height: 16, fill: "none", stroke: "#cc3333", strokeWidth: 2, strokeLinecap: "round", flexShrink: 0 }}>
                  <circle cx="12" cy="12" r="9" />
                  <path d="M12 8v4M12 16h.01" />
                </svg>
                {error}
              </div>
            ) : null}

            <form onSubmit={onSubmit} noValidate>
              <Field label="メールアドレス" htmlFor="op-inp-email">
                <input
                  type="email"
                  id="op-inp-email"
                  required
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="example@company.co.jp"
                  inputMode="email"
                />
              </Field>
              <Field label="パスワード" htmlFor="op-inp-pw">
                <PasswordField id="op-inp-pw" value={password} onChange={setPassword} />
              </Field>

              <button type="submit" className="btn btn-primary btn-block btn-lg" style={{ marginTop: 4 }} disabled={busy}>
                {busy ? (
                  <>
                    <span className="spinning">↻</span> ログイン中…
                  </>
                ) : (
                  "ログイン"
                )}
              </button>
            </form>
          </div>

          <div className="auth-switch">
            招待コードをお持ちの方は
            <br />
            <Link href="/operator/signup">業者登録 →</Link>
          </div>
          <div className="auth-switch" style={{ marginTop: 10 }}>
            ユーザーの方は <Link href="/login">ユーザーログイン →</Link>
          </div>
        </div>
      </main>
    </div>
  );
}

export default function OperatorLoginPage() {
  return (
    <Suspense>
      <OperatorLoginForm />
    </Suspense>
  );
}
