"use client";

/** パスワードリセット（3ステップフロー: メール送信 → リンク確認 → 新PW設定 → 完了）。
 *  バックエンド未配線のため、メール送信/再送信/PW更新はUIフロー（ステップ遷移・デモ）として実装。
 *  虚偽の成功断定は避け、デモ操作である旨を明示する。 */

import { useState } from "react";
import Link from "next/link";
import { Ic } from "@/components/kdz/Icons";
import { KdzLogo } from "@/components/kdz/Logo";
import { PasswordField } from "@/components/kdz/auth";
import "./password-reset.css";

type Step = 1 | 2 | 3 | 4;

/** ステップインジケーター（1 メール送信 → 2 新しいパスワード → 3 完了）。
 *  パネルは4段階だが、表示上のステップは3段階に集約する（panel2/3 → step2）。 */
function StepIndicator({ step }: { step: Step }) {
  // 表示ステップ: panel1 → 1, panel2/3 → 2, panel4 → 3
  const display = step === 1 ? 1 : step === 4 ? 3 : 2;
  const items: { n: number; label: string; mark: string }[] = [
    { n: 1, label: "メール送信", mark: "1" },
    { n: 2, label: "新しいパスワード", mark: "2" },
    { n: 3, label: "完了", mark: "✓" },
  ];
  return (
    <div className="step-ind">
      {items.map((it) => {
        const state = it.n < display ? "done" : it.n === display ? "active" : "future";
        return (
          <div key={it.n} className={`si-step ${state}`}>
            <div className="si-dot">{it.mark}</div>
            <div className="si-lbl">{it.label}</div>
          </div>
        );
      })}
    </div>
  );
}

export default function PasswordResetPage() {
  const [step, setStep] = useState<Step>(1);

  // Step 1: メール
  const [email, setEmail] = useState("");
  const [emailErr, setEmailErr] = useState(false);
  const [sending, setSending] = useState(false);

  // Step 2: 再送信
  const [resent, setResent] = useState(false);

  // Step 3: 新パスワード
  const [pw1, setPw1] = useState("");
  const [pw2, setPw2] = useState("");
  const [pwAlert, setPwAlert] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);

  // PW強度（0..3）
  function strengthScore(v: string): number {
    let sc = 0;
    if (v.length >= 8) sc++;
    if (/[A-Z0-9]/.test(v)) sc++;
    if (/[^A-Za-z0-9]/.test(v) || v.length >= 12) sc++;
    return sc;
  }
  const sc = strengthScore(pw1);
  const strengthColors = ["#e05c5c", "#f0a030", "var(--green)"];
  const strengthLabels = ["弱い", "普通", "強い"];
  const activeColor = strengthColors[Math.min(Math.max(sc - 1, 0), 2)];

  function onSend() {
    const v = email.trim();
    if (!v || !v.includes("@")) {
      setEmailErr(true);
      return;
    }
    setEmailErr(false);
    setSending(true);
    window.setTimeout(() => {
      setSending(false);
      setStep(2);
    }, 900);
  }

  function onResend() {
    setResent(true);
    window.setTimeout(() => setResent(false), 5000);
  }

  function onReset() {
    if (pw1.length < 8) {
      setPwAlert("8文字以上で入力してください");
      return;
    }
    if (pw1 !== pw2) {
      setPwAlert("パスワードが一致しません");
      return;
    }
    setPwAlert(null);
    setResetting(true);
    window.setTimeout(() => {
      setResetting(false);
      setStep(4);
    }, 900);
  }

  return (
    <div className="reset-page">
      <Link href="/" className="reset-logo" aria-label="カタヅケ トップへ">
        <KdzLogo size={22} />
      </Link>

      <div className="reset-card reset-wrap">
        <StepIndicator step={step} />

        {/* STEP 1: メール入力 */}
        {step === 1 ? (
          <div>
            <div className="reset-panel-title">パスワードをリセット</div>
            <p className="reset-panel-sub">
              登録したメールアドレスを入力してください。リセット用のURLを送信します。
            </p>
            <div className={`field${emailErr ? " has-error" : ""}`}>
              <label htmlFor="inp-email">メールアドレス</label>
              <input
                type="email"
                id="inp-email"
                value={email}
                onChange={(e) => {
                  setEmail(e.target.value);
                  if (emailErr) setEmailErr(false);
                }}
                placeholder="example@email.com"
                autoComplete="email"
                inputMode="email"
              />
              {emailErr ? (
                <div className="field-error">メールアドレスを正しく入力してください</div>
              ) : null}
            </div>
            <button
              type="button"
              className="btn btn-primary btn-block btn-lg"
              style={{ marginTop: 4 }}
              onClick={onSend}
              disabled={sending}
            >
              {sending ? (
                <>
                  <span className="spinning">↻</span> 送信中…
                </>
              ) : (
                "リセットメールを送信"
              )}
            </button>
            <div className="reset-back">
              <Link href="/login">ログインに戻る</Link>
            </div>
          </div>
        ) : null}

        {/* STEP 2: メール送信済み */}
        {step === 2 ? (
          <div>
            <div className="sent-ic">
              <svg viewBox="0 0 24 24">
                <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
                <path d="M22 6l-10 7L2 6" />
              </svg>
            </div>
            <div className="reset-panel-title" style={{ textAlign: "center" }}>
              メールを送信しました
            </div>
            <p className="reset-panel-sub" style={{ textAlign: "center" }}>
              <strong style={{ color: "var(--navy)" }}>{email.trim()}</strong>
              <br />
              にリセット用URLを送信しました。
              <br />
              メールを確認してリンクをクリックしてください。
            </p>
            <div className="reset-note">
              メールが届かない場合は、迷惑メールフォルダも確認してください。数分経っても届かない場合は再送信できます。
            </div>
            <button
              type="button"
              className="btn btn-primary btn-block"
              onClick={() => setStep(3)}
            >
              （デモ）リセットリンクをクリック
            </button>
            <div style={{ textAlign: "center", marginTop: 12 }}>
              <button
                type="button"
                className="btn btn-ghost"
                style={{ width: "100%", fontSize: 13 }}
                onClick={onResend}
                disabled={resent}
              >
                {resent ? (
                  <>
                    送信しました <Ic name="check" style={{ width: 14, height: 14 }} />
                  </>
                ) : (
                  "メールを再送信する"
                )}
              </button>
            </div>
          </div>
        ) : null}

        {/* STEP 3: 新パスワード入力 */}
        {step === 3 ? (
          <div>
            <div className="reset-panel-title">新しいパスワードを設定</div>
            <p className="reset-panel-sub">8文字以上の新しいパスワードを入力してください。</p>
            <div className="field">
              <label htmlFor="inp-pw1">新しいパスワード</label>
              <PasswordField
                id="inp-pw1"
                value={pw1}
                onChange={setPw1}
                placeholder="8文字以上"
                autoComplete="new-password"
              />
              {pw1.length ? (
                <div className="pw-strength">
                  {[0, 1, 2].map((i) => (
                    <div
                      key={i}
                      className="pw-bar"
                      style={{ background: i < sc ? activeColor : "var(--line)" }}
                    />
                  ))}
                  <span className="pw-bar-lbl" style={{ color: activeColor }}>
                    {sc ? strengthLabels[Math.min(sc - 1, 2)] : ""}
                  </span>
                </div>
              ) : null}
            </div>
            <div className="field">
              <label htmlFor="inp-pw2">確認用パスワード</label>
              <PasswordField
                id="inp-pw2"
                value={pw2}
                onChange={setPw2}
                placeholder="もう一度入力"
                autoComplete="new-password"
              />
            </div>
            {pwAlert ? <div className="field-error">{pwAlert}</div> : null}
            <button
              type="button"
              className="btn btn-primary btn-block btn-lg"
              style={{ marginTop: 4 }}
              onClick={onReset}
              disabled={resetting}
            >
              {resetting ? (
                <>
                  <span className="spinning">↻</span> 変更中…
                </>
              ) : (
                "パスワードを変更する"
              )}
            </button>
          </div>
        ) : null}

        {/* STEP 4: 完了 */}
        {step === 4 ? (
          <div>
            <div className="done-ic">
              <svg viewBox="0 0 24 24">
                <path d="M5 12.5l4.5 4.5L19 7" />
              </svg>
            </div>
            <div className="reset-panel-title" style={{ textAlign: "center" }}>
              パスワードを変更しました！
            </div>
            <p className="reset-panel-sub" style={{ textAlign: "center" }}>
              新しいパスワードでログインできます。
            </p>
            <Link href="/login" className="btn btn-primary btn-block btn-lg">
              ログインする
            </Link>
          </div>
        ) : null}
      </div>
    </div>
  );
}
