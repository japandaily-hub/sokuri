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
    <div className="auth-page auth-page--split operator-auth">
      <AuthBar rightHref="/operator/signup" rightLabel="業者登録はこちら →" />
      <main id="main">
        <aside className="auth-side">
          {/* eslint-disable @next/next/no-img-element */}
          <img src="/img/v2/ol-side.webp" width={900} height={1350} alt="" loading="lazy" decoding="async" />
          <p className="auth-side__line">業者の方の入口です。</p>
        </aside>
        <div className="auth-wrap">
          <div className="auth-card">
            <div className="auth-head">
              <span className="buyer-tag"><span className="buyer-tag__en">BUYER</span>買取業者さま向け</span>
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
                <span>現在はユーザーアカウントでログイン中です。業者としてご利用になる場合は、いったんサインアウトしてください。</span>
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

          {/* 状態別の案内。審査の所要日数は書かない（確約になるため・BRIEF §2.5） */}
          <div className="op-guide">
            <p className="op-guide-t">ログインできない場合</p>
            <ul className="op-guide-list">
              <li>
                まだお申し込みでない方は、<Link href="/business">業者登録のお申し込み</Link>からご案内しています。
              </li>
              <li>お申し込み済みの方は、審査完了後にメールでお知らせします。</li>
              {/* ラウンド5 指摘（21）の整合: /operator/signup は招待コードが無くても登録できる（任意項目）。
                  ここが「招待コードをお持ちの方は」だと、同じ入口の条件が 2 ページで食い違う。 */}
              <li>
                アカウントをまだ作成していない方は、<Link href="/operator/signup">業者登録</Link>から作成できます（招待コードは任意）。
              </li>
            </ul>
            {/* ラウンド5 指摘（22）: 自己再設定は未実装で窓口対応のみ。窓口だけ示して所要が書かれていないと
                開店前に入れなくなった業者が待ち時間を読めない。/business・/contact の既存表記
                （「通常3営業日以内にご返信します」）と同じ条件をここにも書く（新しい約束は足さない）。 */}
            <p className="op-guide-note">
              パスワードの再設定は<Link href="/contact">お問い合わせ</Link>から承ります（通常3営業日以内にご返信します）。
            </p>
          </div>

          <div className="auth-switch" style={{ marginTop: 20 }}>
            ユーザーの方は <Link href="/login">ユーザーログイン →</Link>
          </div>

          <div className="op-auth-foot">
            運営: カタヅケ運営事務局
            <span aria-hidden="true"> ／ </span>
            <Link href="/company">運営者情報</Link>
          </div>

          {/* R6 指摘 11（a11y・法務）: 左（モバイルは上部の帯）の人物は生成画像（3Dレンダー）で、
              実在の登録業者ではない。/vendors・/signup・/login と同じ文言で 1 行だけ揃える。
              画像は装飾（alt=""）なので読み上げには出ず、この 1 行が音声利用者の手掛かりになる。 */}
          <p className="photo-note">※ 写真はイメージです。</p>
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
