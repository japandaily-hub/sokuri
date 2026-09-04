"use client";

/**
 * 業者ログイン（/operator/login）。
 *
 * デザインレビュー B-3 対応: 旧 slate 系 AuthCard（components/AuthCard.tsx）を廃し、
 * ユーザー側 /login と同じ視覚言語（AuthBar/auth-card/Field/PasswordField、
 * katazuke-pages.css）に統一。BUYER タグでアカウント種別を明示する。
 * signIn("operator-credentials") 自体のロジックは変更していない。
 * r4-fix-frontend2 M3: callbackUrl は /operator 配下のみ許可（それ以外は既定の /operator へ）し、
 * 同一アカウント種別（業者）でログイン中でも自動遷移せずバナー＋サインアウト導線を出すよう変更。
 */

import "../operator-auth.css";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { signIn, signOut, useSession } from "next-auth/react";
import { AuthBar, Field, PasswordField } from "@/components/kdz/auth";
import { safeInternalPath } from "@/lib/safe-path";
import { clearRedirectLoopStorage } from "@/lib/katadzuke-api";

function OperatorLoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const { data: session, status } = useSession();
  // オープンリダイレクト対策: サイト内パスのみ許可。
  // r4-fix-frontend2 M3 是正: さらに /operator 配下以外への到達性ガードを追加する
  // （safeInternalPath はサイト内パスかどうかしか見ないため、/mypage 等 /operator 圏外の
  // パスもそのまま通ってしまい、遷移先で middleware に弾かれて /forbidden 行きになっていた）。
  const rawCallbackUrl = safeInternalPath(params.get("callbackUrl"), "/operator");
  const callbackUrl =
    rawCallbackUrl === "/operator" || rawCallbackUrl.startsWith("/operator/")
      ? rawCallbackUrl
      : "/operator";
  // r3 再レビュー N-6 是正: katadzuke-api.ts の共通後始末（403 account_suspended）が
  // /operator配下のパスから発火した場合はここへ ?reason=suspended 付きで遷移させる。
  const suspended = params.get("reason") === "suspended";
  // r8-fix-frontend2 M6 是正: 退会完了後に signOut → ここへ ?reason=withdrawn 付きで遷移させる。
  const withdrawn = params.get("reason") === "withdrawn";

  // r4-fix-frontend2 M3 是正: 従来は accountType==="operator" の一致ケースを
  // useEffect で無条件に自動 replace していたため、既に業者としてログイン中の状態から
  // /operator/login を開いて「別の業者アカウントでログインし直す」導線に一切到達できな
  // かった（自動遷移がフォーム描画直後に発火し、バナーを見る前に離脱させられていた）。
  // 自動遷移は廃止し、同一アカウント種別でもバナー＋ダッシュボードへの手動リンク＋
  // サインアウト導線を表示する。
  const sameAccountSignedIn = status === "authenticated" && session?.accountType === "operator";
  // r3 再レビュー3回目 是正: /login と対称に、依頼者アカウントでログイン中に
  // /operator/login を開いた場合はフォームを表示したまま上部にバナー＋サインアウト導線を出す。
  const otherAccountSignedIn = status === "authenticated" && session?.accountType !== "operator";
  const [signOutBusy, setSignOutBusy] = useState(false);
  async function onSignOutToOperatorLogin() {
    setSignOutBusy(true);
    await signOut({ callbackUrl: "/operator/login" });
  }

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  // r3 再レビュー R-M1 是正: signIn の結果が停止アカウント専用エラー
  // （auth.ts の AccountSuspendedError, code="account_suspended"）の場合に停止案内を出す。
  const [suspendedNow, setSuspendedNow] = useState(false);
  // r8-fix-frontend2 H1 是正: 429（試行集中）／5xx・ネットワーク失敗を
  // 「ログインに失敗しました」と一括表示させず、事実に即した文言を個別に出す。
  const [rateLimited, setRateLimited] = useState(false);
  const [serverError, setServerError] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setSuspendedNow(false);
    setRateLimited(false);
    setServerError(false);
    const res = await signIn("operator-credentials", { email, password, redirect: false });
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
      setError("ログインに失敗しました。メール・パスワード・アカウント状態をご確認ください。");
      return;
    }
    // r3 再レビュー N-8 是正: ログイン成功時にループ検知の発火履歴をリセットする。
    clearRedirectLoopStorage();
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

            {sameAccountSignedIn ? (
              <div className="auth-error" role="status" style={{ flexDirection: "column", alignItems: "flex-start", gap: 8 }}>
                <span>
                  既に業者アカウントでログイン中です。
                  <Link href={callbackUrl} style={{ marginLeft: 4, textDecoration: "underline" }}>
                    ダッシュボードへ進む →
                  </Link>
                </span>
                <button
                  type="button"
                  className="btn btn-ghost btn-block"
                  onClick={() => void onSignOutToOperatorLogin()}
                  disabled={signOutBusy}
                >
                  {signOutBusy ? "サインアウト中…" : "別の業者アカウントでログインする（サインアウト）"}
                </button>
              </div>
            ) : null}

            {otherAccountSignedIn ? (
              <div className="auth-error" role="alert" style={{ flexDirection: "column", alignItems: "flex-start", gap: 8 }}>
                <span>現在は依頼者アカウントでログイン中です。業者としてご利用になる場合は、いったんサインアウトしてください。</span>
                <button
                  type="button"
                  className="btn btn-ghost btn-block"
                  onClick={() => void onSignOutToOperatorLogin()}
                  disabled={signOutBusy}
                >
                  {signOutBusy ? "サインアウト中…" : "サインアウトして業者ログインへ"}
                </button>
              </div>
            ) : null}

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

            {withdrawn ? (
              <div className="auth-error" role="status">
                <svg viewBox="0 0 24 24" style={{ width: 16, height: 16, fill: "none", stroke: "var(--danger)", strokeWidth: 2, strokeLinecap: "round", flexShrink: 0 }}>
                  <circle cx="12" cy="12" r="9" />
                  <path d="M12 8v4M12 16h.01" />
                </svg>
                <span>退会手続きが完了しました。ご利用ありがとうございました。</span>
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

            {error ? (
              <div className="auth-error" role="alert">
                <svg viewBox="0 0 24 24" style={{ width: 16, height: 16, fill: "none", stroke: "var(--danger)", strokeWidth: 2, strokeLinecap: "round", flexShrink: 0 }}>
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
