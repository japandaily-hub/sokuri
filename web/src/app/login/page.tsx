"use client";

/** ユーザーログイン（新デザイン）。admin も同じフォーム（role で /admin へ誘導）。
 *  認証は既存の NextAuth Credentials（user-credentials → backend JWT）を維持。 */

import { Suspense, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { getSession, signIn, signOut, useSession } from "next-auth/react";
import { AuthBar, Field, PasswordField, LineAuthButton, TrustRow } from "@/components/kdz/auth";
import { Reveal } from "@/components/kdz/interactions";
import { safeInternalPath } from "@/lib/safe-path";
import { USER_HOME_PATH, resolvePostLoginPath } from "@/lib/post-login-path";
import { clearRedirectLoopStorage } from "@/lib/katadzuke-api";
import "./login.css";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/**
 * 遷移の出口での多層防御。destination は safeInternalPath を通した値か定数だけのはずだが、
 * 将来の呼び出し誤り（生の callbackUrl や signIn の応答 URL を渡す等）で外部サイトや javascript: へ
 * 遷移しないよう、現在地（location.href。<base> 要素の影響を受けない）を基準に解決し、
 * 同一 origin であることを確かめる。満たさない値は依頼者の既定（/cases）へ置き換える。
 * @returns 同一 origin の絶対 URL
 */
function toSameOriginHref(destination: string): string {
  const here = window.location.href;
  try {
    const target = new URL(destination, here);
    if (target.origin === window.location.origin) return target.href;
  } catch {
    // URL として解釈できない値も下の既定へ置き換える
  }
  console.error("[login] 同一 origin でない遷移先を拒否しました。既定の遷移先へ進みます。");
  return new URL(USER_HOME_PATH, here).href;
}

/**
 * ログイン後の画面遷移（この画面がログイン後に出す唯一の遷移）。ページ全体を読み込み直して遷移する。
 * ルーターの遷移（router.replace / push）を使わない理由は LoginForm の遷移処理のコメント参照。
 * @param destination resolvePostLoginPath が返したサイト内パス
 */
function leaveLoginPage(destination: string): void {
  // ログインに成功した（LINE 等の経路を含む）ので、ループ検知の発火履歴をリセットする（r3 再レビュー N-8）。
  clearRedirectLoopStorage();
  window.location.replace(toSameOriginHref(destination));
}

/**
 * ログイン API は成功したのに、画面側のセッションが依頼者のものになっていない場合の後始末
 * （直後の取得の通信断、または送信前に始まった取得の古い応答＝未ログイン・業者のセッションが
 * 後から届いて上書きした場合）。role を確かめるため 1 回だけ取り直し（broadcast しない＝この画面の
 * 再取得を起こさない）、遷移する。確かめられなければ依頼者の既定へ進む（遷移先のページが読み直す）。
 * ここで止めると「ログイン中…」のまま画面が動かなくなるため、失敗しても必ず遷移する。
 * @param requestedPath safeInternalPath で検証済みの callbackUrl（指定なしは null）
 */
async function recheckSessionAndLeave(requestedPath: string | null): Promise<void> {
  let role: string | undefined;
  try {
    const fresh = await getSession({ broadcast: false });
    if (fresh?.accountType === "user") role = fresh.role;
  } catch (error) {
    console.error("[login] ログイン後のセッションの取り直しに失敗しました", error);
  }
  if (role === undefined) {
    console.error("[login] ログイン後に依頼者のセッションを確認できませんでした。既定の遷移先へ進みます。");
  }
  leaveLoginPage(resolvePostLoginPath(requestedPath, role));
}

function LoginForm() {
  const params = useSearchParams();
  // オープンリダイレクト対策: サイト内パスのみ許可（safeInternalPath）。検証に通らない値は
  // 「指定なし」と同じ扱いにする（fallback を空文字にして区別する。検証済みの値は必ず "/" で始まる）。
  const requestedPath = safeInternalPath(params.get("callbackUrl"), "") || null;
  // 画面の文言切替と LINE ログインの戻り先。ログイン前は役割が分からないため既定は依頼者の /cases。
  const callbackUrl = requestedPath ?? USER_HOME_PATH;
  const toCreate = callbackUrl.startsWith("/create");
  // r3 セキュリティレビュー L-2 是正: backend が停止アカウントを 403
  // { code: "account_suspended" } で返した際、共通処理（katadzuke-api.ts）が
  // signOut 後にここへ ?reason=suspended 付きで遷移させる。
  const suspended = params.get("reason") === "suspended";
  const { data: session, status } = useSession();
  const accountType = session?.accountType;
  const role = session?.role;
  // ログイン後の画面遷移は、ここで 1 回だけ行う（送信直後も、LINE 等でログイン済みのまま /login を
  // 開いた場合も）。遷移先は resolvePostLoginPath（callbackUrl 指定なし → 運営 /admin・それ以外 /cases。
  // 指定あり → 遷移先として許可できればそこ、できなければ既定。r3 セキュリティレビュー H-2 の到達性ガードを含む）。
  // r3 再レビュー N-3 / 3回目 是正: このページは accountType==="user" のセッションだけを想定する。
  // 業者セッションでは遷移せず（行き先が無くループの起点になっていた）、下のバナーに委ねる。
  //
  // 2026-09-26 是正（運営ログインが /login のまま止まる・/cases に着地する）: 以前は送信処理
  // （getSession() → router.push → router.refresh）とこの effect（router.replace）の双方が遷移を出し、
  // getSession() の BroadcastChannel 通知によるセッション再取得で effect も再発火していた。
  // Next 15.5.18 のルーターは、保留中の遷移を後発の遷移で破棄するときに待ち行列の末尾
  // （app-router-instance.js の actionQueue.last）を更新しない。そのため後から積まれた refresh
  // （next dev では HMR の refresh も）が破棄済みの枝につながって永久に解決せず、URL が /login の
  // まま止まることがあった。止まらない場合も最後に効くのは effect の "/cases" で、運営が /admin
  // ではなく /cases に着地していた。遷移元をここ 1 か所に絞り、さらにルーターの待ち行列を通らない
  // ページ全体の読み込み（leaveLoginPage）で遷移する。読み込み直すので router.refresh() は要らない
  // （ルートレイアウトはサーバー側でセッションを読んでいない）。
  const navigatedRef = useRef(false);
  // ログイン API の成功（送信処理が立てる）。直後のセッションが依頼者のものでなかった場合の後始末に使う。
  const [signedIn, setSignedIn] = useState(false);
  useEffect(() => {
    if (navigatedRef.current) return;
    if (status === "authenticated" && accountType === "user") {
      navigatedRef.current = true;
      leaveLoginPage(resolvePostLoginPath(requestedPath, role));
      return;
    }
    // ログイン API は成功したのに、画面側のセッションが依頼者のものになっていない（未ログインのまま、
    // または業者のセッションのまま）。取り直して遷移する（recheckSessionAndLeave）。
    if (signedIn && status !== "loading") {
      navigatedRef.current = true;
      void recheckSessionAndLeave(requestedPath);
    }
  }, [status, accountType, role, requestedPath, signedIn]);

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
    const res = await signIn("user-credentials", { email, password, redirect: false }).catch((error: unknown) => {
      // 通信断等で要求自体が失敗した場合は、下の「サーバーに接続できませんでした」に寄せる
      // （以前は例外が未処理のまま残り、ボタンが「ログイン中…」で止まっていた）。
      console.error("[login] ログインの要求に失敗しました", error);
      return null;
    });
    if (res?.ok && !res.error) {
      // 画面遷移は上の effect が 1 回だけ行う（ここから router.push 等を出すと遷移が競合する）。
      // ループ検知のリセット（r3 再レビュー N-8）も遷移の直前にそちらで行う。
      // 遷移が始まるまで再送信させないよう、ボタンは「ログイン中…」のまま残す。
      setSignedIn(true);
      return;
    }
    setBusy(false);
    if (res?.code === "account_suspended") {
      setSuspendedNow(true);
      return;
    }
    if (res?.code === "rate_limited") {
      setRateLimited(true);
      return;
    }
    // 要求自体の失敗（null）・応答なし（signIn がエラー画面へ遷移した場合の undefined）・
    // エラー無しの失敗応答も、パスワード違いと誤診させない。
    if (!res || res.code === "server_error" || !res.error) {
      setServerError(true);
      return;
    }
    setAuthErr("メールアドレスまたはパスワードが正しくありません。");
  }

  return (
    <div className="login-page auth-page auth-page--split">
      <AuthBar rightHref="/signup" rightLabel="新規登録はこちら →" />
      <main id="main">
        <Reveal as="aside" variant="zoom" className="auth-side">
          {/* eslint-disable @next/next/no-img-element */}
          <img src="/img/v2/li-side.webp" width={900} height={1350} alt="" loading="lazy" decoding="async" />
          <p className="auth-side__line">入札の結果を、確かめに。</p>
        </Reveal>
        <div className="auth-wrap">
          <div className="auth-card">
            <div className="auth-head">
              <h1 className="auth-title">ログイン</h1>
              <p className="auth-sub">{toCreate ? "出品（撮影）に進む前にログインしてください。LINEなら1タップで登録できます。" : "入札状況や業者とのやり取りは、ログイン後に確認できます。"}</p>
            </div>

            {otherAccountSignedIn ? (
              <div className="auth-error" role="alert" style={{ flexDirection: "column", alignItems: "flex-start", gap: 8 }}>
                <span>現在は業者アカウントでログイン中です。ユーザーとしてご利用になる場合は、いったんサインアウトしてください。</span>
                <button
                  type="button"
                  className="btn btn-ghost btn-block btn-swipe"
                  onClick={() => void onSignOutToUserLogin()}
                  disabled={signOutBusy}
                >
                  {signOutBusy ? "サインアウト中…" : "サインアウトしてユーザーログインへ"}
                </button>
              </div>
            ) : null}

            <p style={{ fontSize: 13, color: "var(--body-soft)", lineHeight: 1.75, textAlign: "center", marginBottom: 10 }}>
              LINEで登録した方は、下のボタンからログインできます。
            </p>
            <LineAuthButton callbackUrl={callbackUrl} />
            {/* 同意文は LINE ボタンと同一視野に置く（押す前に規約・ポリシーへ到達できる） */}
            <p style={{ fontSize: 12.5, color: "var(--body-soft)", lineHeight: 1.75, textAlign: "center", marginTop: 10 }}>
              続行すると
              <Link href="/terms" style={{ color: "var(--primary)", textDecoration: "underline" }}>利用規約</Link>
              ・
              <Link href="/privacy" style={{ color: "var(--primary)", textDecoration: "underline" }}>プライバシーポリシー</Link>
              に同意したものとみなします
            </p>

            <div className="auth-divider">メールアドレスで登録した方</div>

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
                <span>短時間にログインの試行が続いたため、一時的に制限しています。しばらく時間をおいてから再度お試しください。</span>
              </div>
            ) : null}

            {serverError ? (
              <div className="auth-error" role="alert">
                <svg viewBox="0 0 24 24" style={{ width: 16, height: 16, fill: "none", stroke: "var(--danger)", strokeWidth: 2, strokeLinecap: "round", flexShrink: 0 }}>
                  <circle cx="12" cy="12" r="9" />
                  <path d="M12 8v4M12 16h.01" />
                </svg>
                <span>サーバーに接続できませんでした。時間をおいて再度お試しください。</span>
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
          {/* 業者導線は依頼者の主導線と混ざらないよう、ヘアラインで一段下げる */}
          <div className="auth-switch" style={{ marginTop: 20, paddingTop: 18, borderTop: "1px solid var(--line)", fontSize: 13 }}>
            業者の方は <Link href="/operator/login">業者ログイン →</Link>
          </div>

          {/* R6 指摘 11（a11y・法務）: 左（モバイルは上部の帯）の人物は生成画像（3Dレンダー）で、
              実在の利用者ではない。/vendors・/signup・/operator/login と同じ文言で 1 行だけ揃える。
              画像は装飾（alt=""）なので読み上げには出ず、この 1 行が音声利用者の手掛かりになる。 */}
          <p className="photo-note">※ 写真はイメージです。</p>
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
