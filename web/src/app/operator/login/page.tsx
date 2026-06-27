"use client";

/** 業者ログイン。 */

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { signIn } from "next-auth/react";
import { AuthCard, ErrorNote, Field, inputClass, primaryButtonClass } from "@/components/AuthCard";
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
    const res = await signIn("operator-credentials", {
      email,
      password,
      redirect: false,
    });
    setBusy(false);
    if (res?.error) {
      setError("ログインに失敗しました。メール・パスワード・アカウント状態をご確認ください。");
      return;
    }
    router.push(callbackUrl);
    router.refresh();
  }

  return (
    <AuthCard
      title="業者ログイン"
      subtitle="登録業者さま向けの管理画面に入ります。"
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
          />
        </Field>
        <button type="submit" disabled={busy} className={primaryButtonClass}>
          {busy ? "ログイン中…" : "ログイン"}
        </button>
      </form>
      <p className="mt-6 text-center text-sm text-slate-500">
        招待コードをお持ちの方は{" "}
        <a href="/operator/signup" className="font-semibold text-brand-700 hover:underline">
          業者登録
        </a>
      </p>
    </AuthCard>
  );
}

export default function OperatorLoginPage() {
  return (
    <Suspense>
      <OperatorLoginForm />
    </Suspense>
  );
}
