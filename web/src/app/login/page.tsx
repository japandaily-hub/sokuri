"use client";

/** ユーザーログイン。admin も同じフォーム（role で /admin へ誘導）。 */

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { signIn } from "next-auth/react";
import { AuthCard, ErrorNote, Field, inputClass, primaryButtonClass } from "@/components/AuthCard";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const callbackUrl = params.get("callbackUrl") ?? "/cases";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const res = await signIn("user-credentials", {
      email,
      password,
      redirect: false,
    });
    setBusy(false);
    if (res?.error) {
      setError("メールアドレスまたはパスワードが正しくありません。");
      return;
    }
    router.push(callbackUrl);
    router.refresh();
  }

  return (
    <AuthCard
      title="ログイン"
      subtitle="カタヅケのアカウントでログインします。"
    >
      <form onSubmit={onSubmit} className="space-y-4">
        <ErrorNote message={error} />
        <Field label="メールアドレス">
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={inputClass}
            placeholder="you@example.com"
          />
        </Field>
        <Field label="パスワード">
          <input
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={inputClass}
            placeholder="8文字以上"
          />
        </Field>
        <button type="submit" disabled={busy} className={primaryButtonClass}>
          {busy ? "ログイン中…" : "ログイン"}
        </button>
      </form>
      <div className="mt-6 space-y-2 text-center text-sm text-slate-500">
        <p>
          アカウントをお持ちでない方は{" "}
          <a href="/signup" className="font-semibold text-brand-700 hover:underline">
            新規登録
          </a>
        </p>
        <p>
          業者の方は{" "}
          <a href="/operator/login" className="font-semibold text-brand-700 hover:underline">
            業者ログイン
          </a>
        </p>
      </div>
    </AuthCard>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
