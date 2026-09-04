"use client";

/** ユーザーログイン（新デザイン）。admin も同じフォーム（role で /admin へ誘導）。
 *  認証は既存の NextAuth Credentials（user-credentials → backend JWT）を維持。 */

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { signIn, signOut, useSession } from "next-auth/react";
import { AuthBar, Field, PasswordField, LineAuthButton, TrustRow } from "@/components/kdz/auth";
import { safeInternalPath } from "@/lib/safe-path";
import { clearRedirectLoopStorage } from "@/lib/katadzuke-api";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  // オープンリダイレクト対策: サイト内パスのみ許可
  const callbackUrl = safeInternalPath(params.get("callbackUrl"), "/cases");
  const toCreate = callbackUrl.startsWith("/create");
  // r3 セキュリティレビュー L-2 是正: backend が停止アカウントを 403
  // { code: "account_suspended" } で返した際、共通処理（katadzuke-api.ts）が
  // signOut 後にここへ ?reason=suspended 付きで遷移させる。
  const suspended = params.get("reason") === "suspended";
  const { data: session, status } = useSession();
  // ログイン済みなら（LINEではじめる 等から来た場合）そのまま目的地へ。
  // r3 セキュリティレビュー H-2 是正: callbackUrl が自分の役割で到達できないパス
  // （/operator配下、admin以外なのに/admin配下）を指す場合はそこへ送らず、
  // 既定の遷移先（/cases）へフォールバックする。
  // r3 再レビュー N-3 是正: 業者アカウントで /login に迷い込んだ場合（このページは
  // accountType==="user" のセッションのみを想定）に callbackUrl（/cases 等）へ
  // 自動 replace してしまうと、その後 middleware が accountType 不一致で /login に
  // 送り返す無限ループになりうる。accountType==="user" を必須条件に加える。
  // r3 再レビュー3回目 是正: 業者セッションの場合はそもそも replace せず（=行き先が無く
  // ループの起点になっていた）、下の「サインアウトして依頼者ログインへ」バナーに委ねる。
  useEffect(() => {
    if (status !== "authenticated") return;
    if (session?.accountType !== "user") return;
    const role = session?.role;
    const reachable =
      !callbackUrl.startsWith("/operator") &&
      (!callbackUrl.startsWith("/admin") || role === "admin");
    // ログイン済み（LINE等の経路含む）でここへ到達した成功ケースなので、
    // ループ検知の発火履歴をリセットする（N-8と同趣旨）。
    clearRedirectLoopStorage();
    router.replace(reachable ? callbackUrl : "/cases");
  }, [status, session, callbackUrl, router]);

  // r3 再レビュー3回目 是正: 業者アカウントでログイン中に /login を開いた場合、
  // フォームは表示したまま上部に案内バナー＋サインアウト導線を出す（行き止まり解消）。
  const otherAccountSignedIn = status === "authenticated" && session?.accountType !== "user";
  const [signOutBusy, setSignOutBusy] = useState(false);
  async function onSignOutToUserLogin() {
    setSignOutBusy(true);
    await signOut({ callbackUrl: "/login" });
  }

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [emailErr, setEmailErr] = useState<string | null>(null);
  const [pwErr, setPwErr] = useState<string | null>(null);
  const [authErr, setAuthErr] = useState<string | null>(null);
  // r3 再レビュー R-M1 是正: signIn の結果が停止アカウント専用エラー（auth.ts の
  // AccountSuspendedError, code="account_suspended"）の場合、
  // 「メールアドレスまたはパスワードが正しくありません」ではなく停止案内を出す。
  const [suspendedNow, setSuspendedNow] = useState(false);
  // r8-fix-frontend2 H1 是正: 429（試行集中）／5xx・ネットワーク失敗を
  // 「パスワードが違います」と誤診させず、事実に即した文言を個別に出す。
  const [rateLimited, setRateLimited] = useState(false);
  const [serverError, setServerError] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setAuthErr(null);
    setSuspendedNow(false);
    setRateLimited(false);
    setServerError(false);
    let ok = true;
    if (!EMAIL_RE.test(email)) {
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
    if (res?.code === "account_suspended") {
      setSuspendedNow(true);
      return;
    }
    if (res?.code === "rate_limited") {
      setRateLimited(true);
      return;
    }
    if (res?.code === "server_error") {
      setServerError(true);
      return;
    }
    if (res?.error) {
      setAuthErr("メールアドレスまたはパスワードが正しくありません");
      return;
    }
    // r3 再レビュー N-8 是正: ログイン成功時にループ検知の発火履歴をリセットする。
    clearRedirectLoopStorage();
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
              <p className="auth-sub">{toCreate ? "出品（撮影）に進む前にログインしてください。LINEなら1タップで登録できます。" : "入札状況や業者との交渉はログイン後に確認できます"}</p>
            </div>

            {otherAccountSignedIn ? (
              <div className="auth-error" role="alert" style={{ flexDirection: "column", alignItems: "flex-start", gap: 8 }}>
                <span>現在は業者アカウントでログイン中です。依頼者としてご利用になる場合は、いったんサインアウトしてください。</span>
                <button
                  type="button"
                  className="btn btn-ghost btn-block"
                  onClick={() => void onSignOutToUserLogin()}
                  disabled={signOutBusy}
                >
                  {signOutBusy ? "サインアウト中…" : "サインアウトして依頼者ログインへ"}
                </button>
              </div>
            ) : null}

            <LineAuthButton callbackUrl={callbackUrl} />

            <div className="auth-divider">メールアドレスで続ける</div>

            {suspended || suspendedNow ? (
              <div className="auth-error" role="alert">
                <svg viewBox="0 0 24 24" style={{ width: 16, height: 16, fill: "none", stroke: "var(--danger)", strokeWidth: 2, strokeLinecap: "round", flexShrink: 0 }}>
                  <circle cx="12" cy="12" r="9" />
                  <path d="M12 8v4M12 16h.01" />
                </svg>
                <span>
                  このアカウントは利用停止中です。お問い合わせ窓口までご連絡ください。
                  <Link href="/contact" style={{ marginLeft: 4, textDecoration: "underline" }}>
                    お問い合わせはこちら
                  </Link>
                </span>
              </div>
            ) : null}

            {rateLimited ? (
              <div className="auth-error" role="alert">
                <svg viewBox="0 0 24 24" style={{ width: 16, height: 16, fill: "none", stroke: "var(--danger)", strokeWidth: 2, strokeLinecap: "round", flexShrink: 0 }}>
                  <circle cx="12" cy="12" r="9" />
                  <path d="M12 8v4M12 16h.01" />
                </svg>
                <span>しばらく時間をおいてから再度お試しください（短時間に試行が集中しました）</span>
              </div>
            ) : null}

            {serverError ? (
              <div className="auth-error" role="alert">
                <svg viewBox="0 0 24 24" style={{ width: 16, height: 16, fill: "none", stroke: "var(--danger)", strokeWidth: 2, strokeLinecap: "round", flexShrink: 0 }}>
                  <circle cx="12" cy="12" r="9" />
                  <path d="M12 8v4M12 16h.01" />
                </svg>
                <span>サーバーに接続できませんでした。時間をおいて再度お試しください</span>
              </div>
            ) : null}

            {authErr ? (
              <div className="auth-error" role="alert">
                <svg viewBox="0 0 24 24" style={{ width: 16, height: 16, fill: "none", stroke: "var(--danger)", strokeWidth: 2, strokeLinecap: "round", flexShrink: 0 }}>
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
