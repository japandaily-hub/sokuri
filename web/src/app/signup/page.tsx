"use client";

/** ユーザー新規登録（新デザイン・3ステップ）。
 *  既存の配線を維持: signupUser() → signIn("user-credentials") → /create。
 *  エリア/利用目的は UI 収集のみ（バックエンド signupUser は email/password/name のみ受領＝将来拡張）。 */

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { signIn } from "next-auth/react";
import { signupUser, KdzApiError } from "@/lib/katadzuke-api";
import { Ic } from "@/components/kdz/Icons";
import { KdzLogo } from "@/components/kdz/Logo";
import { PasswordField, LineAuthButton } from "@/components/kdz/auth";
import "./signup.css";

const AREAS: { key: string; label: string }[] = [
  { key: "tokyo", label: "東京都" },
  { key: "kanagawa", label: "神奈川県" },
  { key: "saitama", label: "埼玉県" },
  { key: "chiba", label: "千葉県" },
  { key: "osaka", label: "大阪府" },
  { key: "aichi", label: "愛知県" },
  { key: "fukuoka", label: "福岡県" },
  { key: "other", label: "その他" },
];
const AREA_LABEL = Object.fromEntries(AREAS.map((a) => [a.key, a.label]));
const ROLE_LABEL: Record<string, string> = { seller: "売りたい・片付けたい", buyer: "業者として入札" };

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
  const colors = ["#e05c5c", "#f0a030", "#1f8a5b"];
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
  const router = useRouter();
  const [step, setStep] = useState(1);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [password2, setPassword2] = useState("");
  const [name, setName] = useState("");
  const [area, setArea] = useState("");
  const [role, setRole] = useState("");
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
    if (!area) { setErr("area", "エリアを選択してください"); ok = false; } else setErr("area", null);
    if (!role) { setErr("role", "利用目的を選択してください"); ok = false; } else setErr("role", null);
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
        // バックエンドは email/password/name のみ受領（area/role は将来拡張用にUI収集のみ）
        await signupUser({ email, password, name: name || undefined });
        const res = await signIn("user-credentials", { email, password, redirect: false });
        if (res?.error) throw new Error("登録後のログインに失敗しました。");
        goTo(4);
      } catch (err) {
        setAuthErr(err instanceof KdzApiError || err instanceof Error ? err.message : "登録に失敗しました。");
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
                <LineAuthButton label="LINEで無料登録" />
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
                すでにアカウントをお持ちの方は<Link href="/login" style={{ color: "var(--blue)", fontWeight: 700 }}>ログイン →</Link>
              </p>
            </div>
          )}

          {/* STEP 2 */}
          {step === 2 && (
            <div>
              <h2 className="step-title">プロフィールを設定する</h2>
              <p className="step-desc">あなたのエリアと利用目的を教えてください。適切な業者をマッチングするために使用します。</p>

              <div className="form-card">
                <div className={`field${errs.name ? " has-error" : ""}`}>
                  <label htmlFor="inp-name">お名前<span className="req">必須</span></label>
                  <input type="text" id="inp-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="山田 花子" autoComplete="name" />
                  {errs.name && <div className="field-error">{errs.name}</div>}
                </div>
                <div className="field" style={{ marginBottom: 0 }}>
                  <label>お住まいのエリア<span className="req">必須</span></label>
                  <div className="area-grid">
                    {AREAS.map((a) => (
                      <button type="button" key={a.key} className={`area-chip${area === a.key ? " selected" : ""}`} onClick={() => { setArea(a.key); setErr("area", null); }}>
                        {a.label}
                      </button>
                    ))}
                  </div>
                  {errs.area && <div className="field-error" style={{ marginTop: 8 }}>{errs.area}</div>}
                </div>
              </div>

              <div className="form-card">
                <div className="field" style={{ marginBottom: 0 }}>
                  <label>ご利用目的<span className="req">必須</span></label>
                  <div className="role-grid">
                    <button type="button" className={`role-card${role === "seller" ? " selected" : ""}`} onClick={() => { setRole("seller"); setErr("role", null); }}>
                      <span className="rc-ic"><Ic name="house" /></span>
                      <span className="rc-title">売りたい・片付けたい</span>
                      <span className="rc-sub">不用品や遺品の買取・整理をお願いしたい方</span>
                    </button>
                    <button type="button" className={`role-card${role === "buyer" ? " selected" : ""}`} onClick={() => { setRole("buyer"); setErr("role", null); }}>
                      <span className="rc-ic"><Ic name="bag" /></span>
                      <span className="rc-title">業者として入札したい</span>
                      <span className="rc-sub">出品された物件に入札・買取参加したい業者</span>
                    </button>
                  </div>
                  {errs.role && <div className="field-error" style={{ marginTop: 8 }}>{errs.role}</div>}
                  {role === "buyer" && (
                    <div className="hint-banner" style={{ marginTop: 12, marginBottom: 0 }}>
                      <Ic name="shield" className="hint-ic" />
                      <span>業者としての参加は<Link href="/business" style={{ color: "var(--blue)", fontWeight: 700 }}>業者登録（審査制）</Link>からも可能です。</span>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* STEP 3 */}
          {step === 3 && (
            <div>
              <h2 className="step-title">内容を確認して<br />登録を完了してください</h2>
              <p className="step-desc">以下の内容で登録します。よろしければ同意の上、登録ボタンを押してください。</p>

              {authErr && (
                <div className="auth-error" style={{ marginBottom: 16 }}>
                  <svg viewBox="0 0 24 24" style={{ width: 16, height: 16, fill: "none", stroke: "#cc3333", strokeWidth: 2, strokeLinecap: "round", flexShrink: 0 }}>
                    <circle cx="12" cy="12" r="9" /><path d="M12 8v4M12 16h.01" />
                  </svg>
                  {authErr}
                </div>
              )}

              <div className="form-card">
                <div className="confirm-row"><span className="lbl">メールアドレス</span><span className="val">{email}</span></div>
                <div className="confirm-row"><span className="lbl">お名前</span><span className="val">{name}</span></div>
                <div className="confirm-row"><span className="lbl">エリア</span><span className="val">{AREA_LABEL[area] || area}</span></div>
                <div className="confirm-row"><span className="lbl">利用目的</span><span className="val">{ROLE_LABEL[role] || role}</span></div>
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
              <h2>登録が完了しました！</h2>
              <p>カタヅケへようこそ。<br />さっそく不用品を撮って、<br />業者からの見積もりを受け取りましょう。</p>
              <div className="done-actions">
                <Link href="/create" className="btn btn-primary btn-lg">
                  さっそく出品してみる<Ic name="arrow" className="arw" />
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
