"use client";

/**
 * 業者新規登録（/operator/signup）。招待コード任意 → 自動ログイン → 案件一覧へ。
 * 招待コードあり → vendor_status=active（即フル稼働）
 * 招待コードなし → vendor_status=limited（即暫定稼働、住所開示は admin 承認後）
 *
 * デザインレビュー B-3 対応: 旧 slate 系 AuthCard（components/AuthCard.tsx）を廃し、
 * ユーザー側 /signup と同じ視覚言語（AuthBar/auth-card/Field、katazuke-pages.css）に統一。
 * 認証ロジック（signupOperator → signIn("operator-credentials")）は変更していない。
 */

import "../operator-auth.css";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { signIn } from "next-auth/react";
import Link from "next/link";
import { signupOperator, toDisplayMessage } from "@/lib/katadzuke-api";
import { AuthBar, Field } from "@/components/kdz/auth";

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
      const res = await signIn("operator-credentials", { email, password, redirect: false });
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
    <div className="auth-page operator-auth">
      <AuthBar rightHref="/operator/login" rightLabel="ログインはこちら →" />
      <main id="main">
        <div className="auth-wrap">
          <div className="auth-card">
            <div className="auth-head">
              <span className="buyer-tag">BUYER</span>
              <h1 className="auth-title">業者登録</h1>
              <p className="auth-sub">
                業者登録には運営の審査があります。まだお申し込みでない方は、まず
                <Link href="/business" style={{ color: "var(--blue)", fontWeight: 700 }}>
                  業者登録のお申し込み
                </Link>
                からご案内しています。招待コードをお持ちの方はこちらからアカウントを作成してください。
              </p>
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
              {/* 招待コード（任意・アコーディオン表示） */}
              <div style={{ marginBottom: 18 }}>
                <button type="button" className="invite-toggle" onClick={() => setShowInviteField((v) => !v)}>
                  {showInviteField ? "▼" : "▶"} 招待コードをお持ちの方はこちら（任意）
                </button>
                {showInviteField ? (
                  <div style={{ marginTop: 10 }}>
                    <Field label="招待コード" htmlFor="op-invite">
                      <input
                        id="op-invite"
                        type="text"
                        value={inviteCode}
                        onChange={(e) => setInviteCode(e.target.value)}
                        placeholder="KDZ-XXXXXXXX"
                      />
                    </Field>
                    <p className="invite-hint">招待コードがあると登録直後からフル機能で入札できます。</p>
                  </div>
                ) : (
                  <p className="invite-note" style={{ marginTop: 10, marginBottom: 0 }}>
                    招待コードなしでも登録できます。ただし、入札には運営の承認が必要です（案件の閲覧は登録後すぐに可能です）。
                  </p>
                )}
              </div>

              <Field label="会社名" htmlFor="op-company">
                <input
                  id="op-company"
                  type="text"
                  required
                  value={company}
                  onChange={(e) => setCompany(e.target.value)}
                  placeholder="株式会社〇〇リユース"
                />
              </Field>
              <Field label="古物商許可番号" htmlFor="op-license" rightSlot={<span style={{ fontSize: 11.5, color: "var(--body-soft)" }}>任意</span>}>
                <input
                  id="op-license"
                  type="text"
                  value={license}
                  onChange={(e) => setLicense(e.target.value)}
                  placeholder="東京都公安委員会 第XXXXXXXXXX号"
                />
              </Field>
              <Field label="メールアドレス" htmlFor="op-email">
                <input
                  id="op-email"
                  type="email"
                  required
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  inputMode="email"
                />
              </Field>
              <Field label="パスワード（8文字以上）" htmlFor="op-password">
                <input
                  id="op-password"
                  type="password"
                  required
                  minLength={8}
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </Field>

              <div className="agree-row">
                <input
                  type="checkbox"
                  id="operator-agree-terms"
                  className="agree-cb"
                  required
                  checked={agree}
                  onChange={(e) => setAgree(e.target.checked)}
                />
                <label htmlFor="operator-agree-terms">
                  <Link href="/terms">利用規約</Link>および<Link href="/privacy">プライバシーポリシー</Link>に同意します
                </label>
              </div>

              <button type="submit" disabled={busy} className="btn btn-primary btn-block btn-lg">
                {busy ? (
                  <>
                    <span className="spinning">↻</span> 登録中…
                  </>
                ) : (
                  "アカウントを作成する"
                )}
              </button>
            </form>
          </div>

          <div className="auth-switch">
            既に登録済みの方は
            <br />
            <Link href="/operator/login">業者ログイン →</Link>
          </div>
        </div>
      </main>
    </div>
  );
}
