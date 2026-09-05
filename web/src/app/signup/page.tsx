"use client";

/** ユーザー新規登録（新デザイン・3ステップ）。
 *  既存の配線を維持: signupUser() → signIn("user-credentials") → /create。
 *  r10-H3 是正: エリア/利用目的は backend signupUser（email/password/name のみ受領）に送信されず
 *  破棄されていたため、フォームごと削除した（説明文と誤認を招く確認表示も併せて撤去）。 */

import { useState } from "react";
import Link from "next/link";
import { signIn } from "next-auth/react";
import { signupUser, toDisplayMessage, clearRedirectLoopStorage } from "@/lib/katadzuke-api";
import { Ic } from "@/components/kdz/Icons";
import { KdzLogo } from "@/components/kdz/Logo";
import { PasswordField, LineAuthButton } from "@/components/kdz/auth";
import "./signup.css";

const STEPS = ["アカウント", "プロフィール", "確認", "完了"];

function pwScore(v: string): number {
  let s = 0;
  if (v.length >= 8) s++;
  if (/[A-Z]/.test(v) || /[0-9]/.test(v)) s++;
  if (/[^A-Za-z0-9]/.test(v) || v.length >= 12) s++;
  return s;
}

function PwStrength({ value }: { value: string }) {
  if (!value) return null;
  const score = pwScore(value);
  const colors = ["var(--danger)", "#f0a030", "var(--primary)"];
  const labels = ["弱い", "普通", "強い"];
  const idx = Math.min(Math.max(score - 1, 0), 2);
  return (
    <div className="pw-strength">
      {[0, 1, 2].map((i) => (
        <div key={i} className="pw-strength-bar" style={{ background: i < score ? colors[idx] : "var(--line)" }} />
      ))}
      <div className="pw-strength-label" style={{ color: score > 0 ? colors[idx] : undefined }}>
        {score > 0 ? labels[idx] : ""}
      </div>
    </div>
  );
}

export default function SignupPage() {
  const [step, setStep] = useState(1);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [name, setName] = useState("");
  const [agree1, setAgree1] = useState(false);
  const [agree2, setAgree2] = useState(false);

  const [errs, setErrs] = useState<Record<string, string>>({});
  const [authErr, setAuthErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function setErr(k: string, v: string | null) {
    setErrs((prev) => {
      const next = { ...prev };
      if (v) next[k] = v;
      else delete next[k];
      return next;
    });
  }

  function goTo(s: number) {
    setStep(s);
    if (typeof window !== "undefined") window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function validateStep1(): boolean {
    let ok = true;
    if (!email || !email.includes("@")) { setErr("email", "メールアドレスを正しく入力してください"); ok = false; } else setErr("email", null);
    if (password.length < 8) { setErr("pw", "8文字以上で入力してください"); ok = false; } else setErr("pw", null);
    if (!password2 || password !== password2) { setErr("pw2", "パスワードが一致しません"); ok = false; } else setErr("pw2", null);
    return ok;
  }
  function validateStep2(): boolean {
    let ok = true;
    if (!name.trim()) { setErr("name", "お名前を入力してください"); ok = false; } else setErr("name", null);
    return ok;
  }

  async function onNext() {
    if (step === 1) { if (!validateStep1()) return; goTo(2); return; }
    if (step === 2) { if (!validateStep2()) return; goTo(3); return; }
    if (step === 3) {
      if (!agree1) { setAuthErr("利用規約への同意が必要です"); return; }
      setBusy(true);
      setAuthErr(null);
      try {
        await signupUser({ email, password, name: name || undefined });
        const res = await signIn("user-credentials", { email, password, redirect: false });
        if (res?.error) throw new Error("登録後のログインに失敗しました。");
        // r3 再レビュー3回目 是正: 新規登録直後のログイン成功でもループ検知の発火履歴をリセットする。
        clearRedirectLoopStorage();
        goTo(4);
      } catch (err) {
        setAuthErr(toDisplayMessage(err, "登録に失敗しました。"));
      } finally {
        setBusy(false);
      }
    }
  }

  return (
    <div className="signup-page flow-bg">
      {/* flow-header */}
      <div className="flow-header">
        <div className="flow-header-inner">
          <Link href="/" aria-label="カタヅケ トップへ">
            <KdzLogo size={18} />
          </Link>
          <div className="flow-steps">
            {STEPS.map((label, i) => {
              const s = i + 1;
              const cls = s < step ? "done" : s === step ? "active" : "";
              return (
                <div key={label} className={`flow-step ${cls}`.trim()}>
                  <div className="fs-dot">{s < step || (s === 4 && step === 4) ? <Ic name="check" style={{ fontSize: 12, strokeWidth: 3 }} /> : s}</div>
                  <div className="fs-label">{label}</div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <main id="main">
        <div className="flow-wrap">
          {/* STEP 1 */}
          {step === 1 && (
            <div>
              <h2 className="step-title">アカウントを作成する</h2>
              <p className="step-desc">メールアドレスとパスワードを設定してください。LINEで続けることもできます。</p>

              <div style={{ marginBottom: 18 }}>
                <LineAuthButton label="LINEで無料登録" callbackUrl="/create" />
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 18, color: "var(--body-soft)", fontSize: 12, fontWeight: 600, letterSpacing: ".04em" }}>
                <div style={{ flex: 1, height: 1, background: "var(--line)" }} />
                メールアドレスで登録
                <div style={{ flex: 1, height: 1, background: "var(--line)" }} />
              </div>

              <div className="form-card">
                <div className={`field${errs.email ? " has-error" : ""}`}>
                  <label htmlFor="inp-email">メールアドレス<span className="req">必須</span></label>
                  <input type="email" id="inp-email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="example@email.com" autoComplete="email" inputMode="email" />
                  {errs.email && <div className="field-error">{errs.email}</div>}
                </div>
                <div className={`field${errs.pw ? " has-error" : ""}`}>
                  <label htmlFor="inp-pw">パスワード<span className="req">必須</span></label>
                  <PasswordField id="inp-pw" value={password} onChange={setPassword} placeholder="8文字以上" autoComplete="new-password" />
                  <PwStrength value={password} />
                  {errs.pw && <div className="field-error">{errs.pw}</div>}
                </div>
                <div className={`field${errs.pw2 ? " has-error" : ""}`}>
                  <label htmlFor="inp-pw2">パスワード（確認）<span className="req">必須</span></label>
                  <PasswordField id="inp-pw2" value={password2} onChange={setPassword2} placeholder="もう一度入力" autoComplete="new-password" />
                  {errs.pw2 && <div className="field-error">{errs.pw2}</div>}
                </div>
              </div>

              <p style={{ fontSize: 12.5, color: "var(--body-soft)", textAlign: "center", lineHeight: 1.75 }}>
                すでにアカウントをお持ちの方は<Link href="/login" style={{ color: "var(--blue)", fontWeight: 600 }}>ログイン →</Link>
              </p>
            </div>
          )}

          {/* STEP 2 */}
          {step === 2 && (
            <div>
              <h2 className="step-title">プロフィールを設定する</h2>
              <p className="step-desc">出品時にお呼びする、お名前を入力してください。</p>

              <div className="form-card">
                <div className={`field${errs.name ? " has-error" : ""}`}>
                  <label htmlFor="inp-name">お名前<span className="req">必須</span></label>
                  <input type="text" id="inp-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="山田 花子" autoComplete="name" />
                  {errs.name && <div className="field-error">{errs.name}</div>}
                </div>
              </div>

              <div className="hint-banner">
                <Ic name="shield" className="hint-ic" />
                <span>業者としてのご登録は<Link href="/business" style={{ color: "var(--blue)", fontWeight: 600 }}>業者登録（審査制）</Link>からお願いします。</span>
              </div>
            </div>
          )}

          {/* STEP 3 */}
          {step === 3 && (
            <div>
              <h2 className="step-title">内容を確認して<br />登録を完了してください</h2>
              <p className="step-desc">以下の内容で登録します。よろしければ同意の上、登録ボタンを押してください。</p>

              {authErr && (
                <div className="auth-error" role="alert" style={{ marginBottom: 16 }}>
                  <svg viewBox="0 0 24 24" style={{ width: 16, height: 16, fill: "none", stroke: "var(--danger)", strokeWidth: 2, strokeLinecap: "round", flexShrink: 0 }}>
                    <circle cx="12" cy="12" r="9" /><path d="M12 8v4M12 16h.01" />
                  </svg>
                  {authErr}
                </div>
              )}

              <div className="form-card">
                <div className="confirm-row"><span className="lbl">メールアドレス</span><span className="val">{email}</span></div>
                <div className="confirm-row"><span className="lbl">お名前</span><span className="val">{name}</span></div>
                <div className="confirm-row"><span className="lbl">登録費用</span><span className="val" style={{ color: "var(--green)" }}>完全無料</span></div>
              </div>

              <div className="form-card" style={{ padding: "18px 24px" }}>
                <div className="agree-row">
                  <input type="checkbox" className="agree-cb" id="agree1" checked={agree1} onChange={(e) => setAgree1(e.target.checked)} />
                  <label htmlFor="agree1"><Link href="/terms">利用規約</Link>および<Link href="/privacy">プライバシーポリシー</Link>に同意します</label>
                </div>
                <div className="agree-row">
                  <input type="checkbox" className="agree-cb" id="agree2" checked={agree2} onChange={(e) => setAgree2(e.target.checked)} />
                  <label htmlFor="agree2">入札情報・サービスに関するメール通知を受け取ることに同意します（任意）</label>
                </div>
              </div>

              <div className="hint-banner">
                <Ic name="lock" className="hint-ic" />
                <span>登録後、すぐに出品をはじめられます。アカウントはこのブラウザでログイン状態になります。</span>
              </div>
            </div>
          )}

          {/* STEP 4 */}
          {step === 4 && (
            <div className="done-screen">
              <div className="done-circle"><Ic name="check-circle" /></div>
              <h2>登録が完了しました。</h2>
              <p>カタヅケへようこそ。<br />さっそく不用品を撮って、<br />業者からの見積もりを受け取りましょう。</p>
              <p style={{ fontSize: 12.5, color: "var(--body-soft)" }}>対応エリアは東京・千葉・埼玉・神奈川です。</p>
              <div className="done-actions">
                <Link href="/create" className="btn btn-primary btn-lg">
                  さっそく出品してみる<Ic name="arrow" />
                </Link>
                <Link href="/" className="btn btn-ghost btn-lg">トップへ戻る</Link>
              </div>
            </div>
          )}
        </div>
      </main>

      {/* フッターボタン（完了画面では非表示） */}
      {step < 4 && (
        <div className="flow-footer">
          <div className="inner">
            {step > 1 && (
              <button type="button" className="btn-flow-back" onClick={() => goTo(step - 1)}>戻る</button>
            )}
            <button type="button" className="btn-flow-next" onClick={onNext} disabled={busy}>
              {busy ? (
                <><span className="spinning">↻</span> 登録中…</>
              ) : step === 3 ? (
                <>登録する<Ic name="arrow" /></>
              ) : (
                <>次へ<Ic name="arrow" /></>
              )}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
