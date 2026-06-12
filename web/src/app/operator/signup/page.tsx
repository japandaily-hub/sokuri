"use client";

/** 業者新規登録（招待コード必須）→ 自動ログイン → 案件一覧へ。 */

import { useState } from "react";
import { useRouter } from "next/navigation";
import { signIn } from "next-auth/react";
import { signupOperator, KdzApiError } from "@/lib/katadzuke-api";
import { AuthCard, ErrorNote, Field, inputClass, primaryButtonClass } from "@/components/AuthCard";

export default function OperatorSignupPage() {
  const router = useRouter();
  const [inviteCode, setInviteCode] = useState("");
  const [company, setCompany] = useState("");
  const [license, setLicense] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signupOperator({
        invite_code: inviteCode.trim(),
        company_name: company,
        email,
        password,
        license_number: license || undefined,
      });
      const res = await signIn("operator-credentials", {
        email,
        password,
        redirect: false,
      });
      if (res?.error) throw new Error("登録後のログインに失敗しました。");
      router.push("/operator/cases");
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
      title="業者登録"
      subtitle="運営から発行された招待コードが必要です。登録後、運営の承認を経て案件を閲覧できます。"
    >
      <form onSubmit={onSubmit} className="space-y-4">
        <ErrorNote message={error} />
        <Field label="招待コード">
          <input
            type="text"
            required
            value={inviteCode}
            onChange={(e) => setInviteCode(e.target.value)}
            className={inputClass}
            placeholder="KDZ-XXXXXXXX"
          />
        </Field>
        <Field label="会社名">
          <input
            type="text"
            required
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            className={inputClass}
            placeholder="株式会社〇〇リユース"
          />
        </Field>
        <Field label="古物商許可番号（任意）">
          <input
            type="text"
            value={license}
            onChange={(e) => setLicense(e.target.value)}
            className={inputClass}
            placeholder="東京都公安委員会 第XXXXXXXXXX号"
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
          {busy ? "登録中…" : "登録する"}
        </button>
      </form>
      <p className="mt-6 text-center text-sm text-slate-500">
        既に登録済みの方は{" "}
        <a href="/operator/login" className="font-semibold text-brand-700 hover:underline">
          業者ログイン
        </a>
      </p>
    </AuthCard>
  );
}
