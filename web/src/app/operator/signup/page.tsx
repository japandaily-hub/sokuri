"use client";

/**
 * 業者新規登録（/operator/signup）。招待コード任意 → 自動ログイン → 案件一覧へ
 * （承認前は案件一覧が ApprovalPendingNotice＝承認待ちの案内に差し替わる）。
 * 招待コードの有無にかかわらず、案件の閲覧と入札は古物商許可証の提出と
 * 運営（admin）の承認後に開放される（backend 仕様変更に合わせ、招待コードでの即時入札は廃止）。
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
import { AuthBar, Field, PasswordField } from "@/components/kdz/auth";
import { Reveal } from "@/components/kdz/interactions";

export default function OperatorSignupPage() {
  const router = useRouter();
  // 招待コードは任意項目。既定で開くと、コードを持たない大半の業者が最初に見る入力欄が
  // 任意欄になり、必須の会社名・古物商許可番号より前に出てしまう（ラウンド2 指摘）。既定は閉じる。
  const [showInviteField, setShowInviteField] = useState(false);
  const [inviteCode, setInviteCode] = useState("");
  const [company, setCompany] = useState("");
  const [license, setLicense] = useState("");
  const [licenseError, setLicenseError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [agree, setAgree] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  /** 古物商許可番号は個人・法人問わず必須（backend OperatorSignupRequest.license_number: min_length=5）。 */
  const LICENSE_MIN_LENGTH = 5;
  /** パスワードは 8 文字以上（backend OperatorSignupRequest.password: min_length=8）。 */
  const PASSWORD_MIN_LENGTH = 8;

  function validateLicense(): boolean {
    const trimmed = license.trim();
    if (trimmed.length === 0) {
      setLicenseError("古物商許可番号を入力してください。");
      return false;
    }
    if (trimmed.length < LICENSE_MIN_LENGTH) {
      setLicenseError(`古物商許可番号は${LICENSE_MIN_LENGTH}文字以上で入力してください。`);
      return false;
    }
    setLicenseError(null);
    return true;
  }

  /** QA H2 是正: フォームは noValidate のため required/minLength は発火しない。
   *  空パスワードのまま signupOperator() が走り backend 422 を汎用エラーで見せていた。 */
  function validatePassword(): boolean {
    if (password.length === 0) {
      setPasswordError("パスワードを入力してください。");
      return false;
    }
    if (password.length < PASSWORD_MIN_LENGTH) {
      setPasswordError(`パスワードは${PASSWORD_MIN_LENGTH}文字以上で入力してください。`);
      return false;
    }
    setPasswordError(null);
    return true;
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    // 先に両方を評価する（片方で return すると、もう一方のエラーが出ず二度手間になる）
    const licenseOk = validateLicense();
    const passwordOk = validatePassword();
    if (!licenseOk || !passwordOk) return;
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
        license_number: license.trim(),
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
    <div className="auth-page auth-page--split operator-auth">
      <AuthBar rightHref="/operator/login" rightLabel="ログインはこちら →" />
      <main id="main">
        <Reveal as="aside" variant="zoom" className="auth-side">
          {/* eslint-disable @next/next/no-img-element */}
          <img src="/img/v2/os-side.webp" width={900} height={1350} alt="" loading="lazy" decoding="async" />
          <p className="auth-side__line">審査制。古物商許可を確認します。</p>
        </Reveal>
        <div className="auth-wrap">
          <div className="auth-card">
            <div className="auth-head">
              <span className="buyer-tag"><span className="buyer-tag__en">BUYER</span>買取業者さま向け</span>
              <h1 className="auth-title">業者登録</h1>
              {/* ラウンド5 指摘（18）: 依頼者（売りたい方）が誤って開いても戻る導線が無く、
                  必須の古物商許可番号まで見えるため「これが自分の登録画面か」と不安になる。
                  h1 の直下＝入力より手前に 1 行だけ置く。 */}
              <p className="op-other-side">
                ご依頼（売りたい）の方は<Link href="/signup">こちらから無料登録 →</Link>
              </p>
              {/* ラウンド5 指摘（21）: 「審査のお申し込みへ」→「招待コードをお持ちの方はこちらから」→
                  直後の「招待コードなしでも登録できます」で入口が3転していた。
                  導入文からは招待コードの話を落とし、「このページで何ができるか」の 1 文に統一する
                  （案件の閲覧と入札の可否は直下の .op-gate-note が受ける）。 */}
              <p className="auth-sub">
                このページから業者アカウントを作成できます。審査のお申し込みがまだの方は
                <Link href="/business" style={{ color: "var(--blue)", fontWeight: 600 }}>
                  業者登録のお申し込み
                </Link>
                へお進みください。
              </p>
            </div>

            {/* 参加条件の要点。左カラムの1行（審査制）を、右カラムの事実で受ける */}
            <ul className="op-points">
              <li>古物商許可の確認</li>
              <li>初期費用0円</li>
              <li>下見なし</li>
            </ul>

            {/* 承認前にできること／できないこと。アコーディオンの開閉に関わらず常時表示（日数は書かない） */}
            <p className="op-gate-note">
              案件の閲覧と入札は、古物商許可証をご提出いただき、運営が承認した後にご利用いただけます。
            </p>

            {error ? (
              <div className="auth-error" role="alert">
                <svg viewBox="0 0 24 24" aria-hidden="true" style={{ width: 16, height: 16, fill: "none", stroke: "var(--danger)", strokeWidth: 2, strokeLinecap: "round", flexShrink: 0 }}>
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
                    <Field label="招待コード" htmlFor="op-invite" rightSlot={<span className="opt">任意</span>}>
                      <input
                        id="op-invite"
                        type="text"
                        value={inviteCode}
                        onChange={(e) => setInviteCode(e.target.value)}
                        placeholder="KDZ-XXXXXXXX"
                      />
                    </Field>
                    <p className="invite-hint">招待コードをお使いの場合も、入札には古物商許可証の提出と運営の承認が必要です。</p>
                  </div>
                ) : (
                  // 淡青の面ではなく、折りたたみラベル行に添える補足テキスト（operator-auth.css .invite-note）
                  // 指摘（21）: 導入文から招待コードの話を外したので、ここは「持っている人だけの欄」だと
                  // 言い切るだけに縮める（「なしでも登録できます」の打消しが不要になった）。
                  <p className="invite-note">お持ちの方のみご入力ください。</p>
                )}
              </div>

              <Field label="会社名" htmlFor="op-company" rightSlot={<span className="req">必須</span>}>
                <input
                  id="op-company"
                  type="text"
                  required
                  value={company}
                  onChange={(e) => setCompany(e.target.value)}
                  placeholder="株式会社〇〇リユース"
                />
              </Field>
              <Field
                label="古物商許可番号"
                htmlFor="op-license"
                rightSlot={<span className="req">必須</span>}
                error={licenseError}
              >
                <>
                  <input
                    id="op-license"
                    type="text"
                    required
                    minLength={LICENSE_MIN_LENGTH}
                    value={license}
                    onChange={(e) => setLicense(e.target.value)}
                    placeholder="東京都公安委員会 第XXXXXXXXXX号"
                  />
                  <p className="field-note">利用者の安心のため、許可証を運営が確認します。</p>
                </>
              </Field>
              <Field label="メールアドレス" htmlFor="op-email" rightSlot={<span className="req">必須</span>}>
                <input
                  id="op-email"
                  type="email"
                  required
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="example@company.co.jp"
                  inputMode="email"
                />
              </Field>
              {/* パスワード表示切替は /operator/login・/login と同じ PasswordField に揃える */}
              <Field
                label="パスワード（8文字以上）"
                htmlFor="op-password"
                rightSlot={<span className="req">必須</span>}
                error={passwordError}
              >
                <PasswordField
                  id="op-password"
                  value={password}
                  onChange={(v) => {
                    setPassword(v);
                    if (passwordError) setPasswordError(null);
                  }}
                  autoComplete="new-password"
                  minLength={PASSWORD_MIN_LENGTH}
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
