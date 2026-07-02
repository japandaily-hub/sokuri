"use client";

/** 業者新規登録（招待コード任意）→ 自動ログイン → 案件一覧へ。
 * 招待コードあり → vendor_status=active（即フル稼働）
 * 招待コードなし → vendor_status=limited（即暫定稼働、住所開示は admin 承認後）
 */

import { useState } from "react";
import { useRouter } from "next/navigation";
import { signIn } from "next-auth/react";
import Link from "next/link";
import { signupOperator, toDisplayMessage } from "@/lib/katadzuke-api";
import { AuthCard, ErrorNote, Field, inputClass, primaryButtonClass } from "@/components/AuthCard";

export default function OperatorSignupPage() {
  const router = useRouter();
  const [showInviteField, setShowInviteField] = useState(false);
  const [inviteCode, setInviteCode] = useState("");
  const [company, setCompany] = useState("");
  const [license, setLicense] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [agree, setAgree] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!agree) {
      setError("利用規約・プライバシーポリシーへの同意が必要です。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await signupOperator({
        invite_code: inviteCode.trim() || null,
        company_name: company,
        email,
        password,
        license_number: license || undefined,
        agreed: agree,
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
      setError(toDisplayMessage(err, "登録に失敗しました。"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthCard
      title="業者登録"
      subtitle={
        <>
          業者登録には運営の審査があります。まだお申し込みでない方は、まず
          <Link href="/business" className="font-semibold text-brand-700 hover:underline">
            業者登録のお申し込み
          </Link>
          からご案内しています。招待コードをお持ちの方はこちらからアカウントを作成してください。
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4">
        <ErrorNote message={error} />

        {/* 招待コード（任意・アコーディオン表示） */}
        <div>
          <button
            type="button"
            onClick={() => setShowInviteField((v) => !v)}
            className="flex items-center gap-1 text-sm font-medium text-brand-700 hover:underline"
          >
            {showInviteField ? "▼" : "▶"} 招待コードをお持ちの方はこちら（任意）
          </button>
          {showInviteField ? (
            <div className="mt-2">
              <input
                type="text"
                value={inviteCode}
                onChange={(e) => setInviteCode(e.target.value)}
                className={inputClass}
                placeholder="KDZ-XXXXXXXX"
              />
              <p className="mt-1 text-xs text-slate-500">
                招待コードがあると登録直後からフル機能で入札できます。
              </p>
            </div>
          ) : null}
        </div>

        {!showInviteField ? (
          <div className="rounded-lg bg-blue-50 px-3 py-2 text-xs text-blue-700">
            招待コードなしでも登録できます。ただし、入札には運営の承認が必要です（案件の閲覧は登録後すぐに可能です）。
          </div>
        ) : null}

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
        <div className="flex items-start gap-2 text-sm text-slate-700">
          <input
            type="checkbox"
            id="operator-agree-terms"
            required
            checked={agree}
            onChange={(e) => setAgree(e.target.checked)}
            className="mt-0.5 h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-200"
          />
          <label htmlFor="operator-agree-terms">
            <a href="/terms" className="font-semibold text-brand-700 hover:underline">
              利用規約
            </a>
            および
            <a href="/privacy" className="font-semibold text-brand-700 hover:underline">
              プライバシーポリシー
            </a>
            に同意します
          </label>
        </div>
        <button type="submit" disabled={busy} className={primaryButtonClass}>
          {busy ? "登録中…" : "アカウントを作成する"}
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
