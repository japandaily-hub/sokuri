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
import { PasswordField, LineAuthButton, TrustRow } from "@/components/kdz/auth";
import { Reveal } from "@/components/kdz/interactions";
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
  /* お知らせメール（入札の通知・リマインド）の受け取り。取引の進行に必要な通知なので既定はオン
     （オフのままだと入札が届いても気づけない）。値は signupUser で保存し、/notifications で変更できる。 */
  const [agree2, setAgree2] = useState(true);

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
      if (!agree1) { setAuthErr("利用規約およびプライバシーポリシーへの同意が必要です"); return; }
      setBusy(true);
      setAuthErr(null);
      try {
        await signupUser({ email, password, name: name || undefined, email_notify_opt_in: agree2 });
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
    <div className="signup-page flow-bg auth-page auth-page--split">
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
        <Reveal as="aside" variant="zoom" className="auth-side">
          {/* eslint-disable @next/next/no-img-element */}
          <img src="/img/v2/su-side.webp" width={900} height={1350} alt="" loading="lazy" decoding="async" />
          <p className="auth-side__line">撮って、あとは待つだけ。</p>
        </Reveal>
        <div className="flow-wrap">
          {/* STEP 1 */}
          {step === 1 && (
            <div>
              {/* ラウンド3 指摘（a11y）: このページには h1 が 1 つも無く、見出しナビゲーションで
                  ページの主題に到達できなかった。ステップは同時に 1 つしか描画されないので、
                  表示中のステップ見出しを h1 にすれば常に h1 はページに 1 つだけになる。
                  .step-title はクラス指定（katazuke-pages.css:154）なので見えは変わらない。 */}
              <h1 className="step-title">アカウントを作成する</h1>
              <p className="step-desc">メールアドレスとパスワードを設定してください。LINEで続けることもできます。</p>

              {/* 登録＝業者への通知ではないこと（実装事実）を、入力を始める前に置く */}
              <p className="signup-lead-note">
                登録しただけでは業者に何も伝わりません。連絡が来るのは、あなたが1社を選んだ後だけです。
              </p>

              {/* R4 ラウンド4 指摘（3/14）: 緑ピルが版面で唯一の巨大な単色面になり「主役」に見える。
                  ボタンの形状・色・角丸99px・幅（コア .btn-line-auth の max-width:360px・中央寄せ）は
                  変えず、置き方＝上下の余白だけで「選択肢の一つ」に見せる。
                  余白の値は signup.css（.signup-line-slot）。
                  ラウンド4 では「ボタンの外に補足1行を足すと縦が 26px 伸び、『すでにアカウントをお持ちの方は…』の
                  行が固定バーの境界をまたいで水平に切れる」ためラベル内で言い切っていたが、
                  コアが列を align-self:center → start に変え、内容が行より高いときはページが伸びて
                  スクロールするようになったため、その制約は外れた（下のラウンド5 指摘を参照）。 */}
              {/* ラウンド5 指摘（4/7/12・3視点が同一指摘）: 角丸ゼロの版面で唯一の角丸 99px のピルが
                  「主動線」に見えてしまう。ボタン本体（コア .btn-line-auth・幅 360px 中央寄せ）の寸法は
                  変えず、上に 12px の説明 1 行を添え、前後に 24px 以上の余白を取って
                  「並んだ別の入口」として独立させる（余白は signup.css の .signup-line-slot）。
                  指摘16 の文言「トップのLINEボタンと同じ入口です」は採らない: トップの .btn-line は
                  /login?callbackUrl=%2Fcreate へのリンク（app/page.tsx:101/207/539）で、
                  ここの LINE ログイン（signIn("line")）と遷移が同じではないため。 */}
              <div className="signup-line-slot">
                <p className="signup-line-note">お使いのLINEアカウントでそのまま登録できます。パスワードの設定は不要です。</p>
                <LineAuthButton label="LINEアカウントで無料登録" callbackUrl="/create" />
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
                  <PasswordField id="inp-pw" value={password} onChange={setPassword} placeholder="8文字以上" autoComplete="new-password" minLength={8} />
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
              <h1 className="step-title">プロフィールを設定する</h1>
              <p className="step-desc">マイページなどの表示に使うお名前を入力してください。業者に渡ることはありません。</p>

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
              <h1 className="step-title">内容を確認して<br />登録を完了してください</h1>
              <p className="step-desc">以下の内容で登録します。よろしければ同意のうえ、登録ボタンを押してください。</p>

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
                  <label htmlFor="agree2">入札が届いたときなどのお知らせメールを受け取る（任意・あとから通知設定で変更できます）</label>
                </div>
              </div>

              <div className="hint-banner">
                <Ic name="lock" className="hint-ic" />
                <span>登録後、すぐに出品をはじめられます。登録が完了すると、このブラウザではログインした状態になります。</span>
              </div>
            </div>
          )}

          {/* STEP 4 */}
          {step === 4 && (
            <div className="done-screen">
              <div className="done-circle"><Ic name="check-circle" /></div>
              <h1>登録が完了しました</h1>
              <p>カタヅケへようこそ。<br />さっそく不用品を撮って、<br />業者からの入札を受け取りましょう。</p>
              <p style={{ fontSize: 12.5, color: "var(--body-soft)" }}>対応エリアは東京・千葉・埼玉・神奈川です。</p>
              <div className="done-actions">
                <Link href="/create" className="btn btn-primary btn-lg">
                  さっそく出品してみる<Ic name="arrow" />
                </Link>
                <Link href="/" className="btn btn-ghost btn-lg btn-swipe">トップへ戻る</Link>
              </div>
            </div>
          )}

          {step < 4 && <TrustRow />}

          {/* R6 指摘 11（a11y・法務）: 左（モバイルは上部の帯）の人物は生成画像（3Dレンダー）で、
              実在の利用者ではない。/vendors が帯直下に置いている 1 行（.vd-photo-note）と
              同じ文言で揃える。画像は装飾（alt=""）なので読み上げには出ず、この 1 行が
              音声利用者にとっての唯一の手掛かりになる。新しい約束・条件は足さない。
              帯の上に重ねない（§1.2「帯上の文字は 24px 以上の見出しのみ」）ためフォーム列の末尾に置く。 */}
          <p className="photo-note">※ 写真はイメージです。</p>
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
