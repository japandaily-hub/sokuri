"use client";

/** ユーザー新規登録 → 自動ログイン → 案件作成へ。 */

import { useState } from "react";
import { useRouter } from "next/navigation";
import { signIn } from "next-auth/react";
import { signupUser, KdzApiError } from "@/lib/katadzuke-api";
import { AuthCard, ErrorNote, Field, inputClass, primaryButtonClass } from "@/components/AuthCard";

export default function SignupPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signupUser({ email, password, name: name || undefined });
      const res = await signIn("user-credentials", {
        email,
        password,
        redirect: false,
      });
      if (res?.error) throw new Error("登録後のログインに失敗しました。");
      router.push("/create");
      router.refresh();
    } catch (err) {
      setError(
        err instanceof KdzApiError || err instanceof Error
          ? err.message
          : "登録に失敗しました。",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title="新規登録"
      subtitle="写真を撮って送るだけ。業者から見積もりが届きます。"
    >
      <form onSubmit={onSubmit} className="space-y-4">
        <ErrorNote message={error} />
        <Field label="お名前（ニックネーム可）">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className={inputClass}
            placeholder="カタヅケ太郎"
          />
        </Field>
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
        <Field label="パスワード（8文字以上）">
          <input
            type="password"
            required
            minLength={8}
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={inputClass}
          />
        </Field>
        <button type="submit" disabled={busy} className={primaryButtonClass}>
          {busy ? "登録中…" : "登録してはじめる"}
        </button>
      </form>
      <p className="mt-6 text-center text-sm text-slate-500">
        既にアカウントをお持ちの方は{" "}
        <a href="/login" className="font-semibold text-brand-700 hover:underline">
          ログイン
        </a>
      </p>
    </AuthCard>
  );
}
