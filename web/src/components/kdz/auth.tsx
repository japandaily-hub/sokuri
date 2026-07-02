"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import { signIn } from "next-auth/react";
import { KdzLogo } from "./Logo";

/** 認証画面の上部バー（ロゴ + 右リンク）。 */
export function AuthBar({ rightHref, rightLabel }: { rightHref: string; rightLabel: string }) {
  return (
    <header className="auth-bar">
      <Link href="/" aria-label="カタヅケ トップへ">
        <KdzLogo size={20} />
      </Link>
      <Link href={rightHref} className="auth-bar-link">
        {rightLabel}
      </Link>
    </header>
  );
}

/** ラベル + 任意の右上リンク + 子（input等） + エラー。 */
export function Field({
  label,
  htmlFor,
  rightSlot,
  error,
  children,
}: {
  label: string;
  htmlFor?: string;
  rightSlot?: ReactNode;
  error?: string | null;
  children: ReactNode;
}) {
  return (
    <div className={`field${error ? " has-error" : ""}`}>
      {rightSlot ? (
        <div className="field-top">
          <label className="field-lbl" htmlFor={htmlFor}>
            {label}
          </label>
          {rightSlot}
        </div>
      ) : (
        <label htmlFor={htmlFor}>{label}</label>
      )}
      {children}
      {error ? <div className="field-error">{error}</div> : null}
    </div>
  );
}

const EYE = (
  <path d="M1 12S5 5 12 5s11 7 11 7-4 7-11 7S1 12 1 12z M12 9a3 3 0 100 6 3 3 0 000-6z" />
);
const EYE_OFF = (
  <>
    <path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-7-11-7a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 7 11 7a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24" />
    <line x1="1" y1="1" x2="23" y2="23" />
  </>
);

/** パスワード入力（表示/非表示トグル付き）。値は親が制御。 */
export function PasswordField({
  id,
  value,
  onChange,
  placeholder = "8文字以上",
  autoComplete = "current-password",
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  autoComplete?: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <div className="pw-wrap">
      <input
        type={show ? "text" : "password"}
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete={autoComplete}
      />
      <button
        type="button"
        className="pw-toggle"
        aria-label="パスワードを表示/非表示"
        onClick={() => setShow((s) => !s)}
      >
        <svg viewBox="0 0 24 24">{show ? EYE_OFF : EYE}</svg>
      </button>
    </div>
  );
}

/**
 * LINE 認証ボタン。
 * signIn("line", { callbackUrl }) を呼び出し、NextAuth の LINE OAuth フローへ遷移する。
 * サーバー側で LINE プロバイダが未登録（環境変数未設定）の場合は NextAuth が
 * エラーページへ遷移する（事前の利用可否チェックはあえて行わない設計）。
 */
export function LineAuthButton({
  label = "LINEで続ける",
  callbackUrl,
}: {
  label?: string;
  /** ログイン成功後の遷移先。呼び出し元の既存ログインフローの遷移先と揃えること。 */
  callbackUrl: string;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <button
      type="button"
      className="btn-line-auth"
      disabled={busy}
      onClick={() => {
        setBusy(true);
        void signIn("line", { callbackUrl });
      }}
    >
      <svg viewBox="0 0 24 24">
        <path d="M12 2C6.48 2 2 6.1 2 11.1c0 4.5 3.6 8.3 8.5 9-.3.8-.4 2-.4 2s-.1.7.4.9c.5.2 1-.2 1-.2s2.7-1.8 3.8-2.5c.4.1.9.1 1.3.1C17.7 20.4 22 16.4 22 11.1 22 6.1 17.5 2 12 2z" />
      </svg>
      {label}
    </button>
  );
}

/** 信頼行（SSL / プライバシー / 無料）。 */
export function TrustRow() {
  return (
    <div className="trust-row">
      <div className="trust-item">
        <svg viewBox="0 0 24 24">
          <path d="M12 2L3 7v5c0 5.25 3.75 10.15 9 11.35C17.25 22.15 21 17.25 21 12V7L12 2z" />
          <path d="M9 12l2 2 4-4" />
        </svg>
        SSL暗号化通信
      </div>
      <div className="trust-item">
        <svg viewBox="0 0 24 24">
          <rect x="5" y="11" width="14" height="10" rx="2" />
          <path d="M8 11V7a4 4 0 018 0v4" />
        </svg>
        プライバシー保護
      </div>
      <div className="trust-item">
        <svg viewBox="0 0 24 24">
          <circle cx="12" cy="12" r="9" />
          <path d="M9 12l2 2 4-4" />
        </svg>
        無料ログイン
      </div>
    </div>
  );
}
