"use client";

import Link from "next/link";
import { useId, useState, type ReactNode } from "react";
import { signIn } from "next-auth/react";
import { canStartLineAuth, lineConsentHint } from "@/lib/line-consent";
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

/** パスワード入力（表示/非表示トグル付き）。値は親が制御。
 *  QA H2 是正: 素の `<input type="password" required minLength={8}>` から本部品へ移した際に
 *  required / minLength が落ちていた。required は既定 true（パスワード欄は全画面で必須）、
 *  minLength は新規作成の画面だけが渡す（ログインは既存の短いパスワードを弾かないため既定なし）。 */
export function PasswordField({
  id,
  value,
  onChange,
  placeholder = "8文字以上",
  autoComplete = "current-password",
  required = true,
  minLength,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  autoComplete?: string;
  required?: boolean;
  minLength?: number;
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
        required={required}
        minLength={minLength}
      />
      <button
        type="button"
        className="pw-toggle"
        aria-label={show ? "パスワードを非表示にする" : "パスワードを表示する"}
        aria-pressed={show}
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
 *
 * R4 レビュー（legal High）是正: 以前はここに LINE の吹き出しマークを模した自作の SVG path を
 * 置いていた。緑地＋白い吹き出しは LINE アプリアイコンの構成要素であり、独自ロゴ・類似物の作成に
 * 当たるため削除し、暫定でテキストのみのボタンにした。このボタンは LINE ヤフー提供の公式ボタンでは
 * ないため、マークを出す場合は同社が配布する公式ボタン画像／指定ロゴに差し替えること（自作の
 * 再描画はしない）。「公式仕様」という記述も本ファイル・CSS・呼び出し側のコメントから外した。
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
      {label}
    </button>
  );
}

/**
 * 利用規約・プライバシーポリシーへの明示の同意（必須チェック）＋ LINE 認証ボタン。
 *
 * 2周目監査 N-2（/signup）・N-9（/login）: LINE ログインは未登録の LINE アカウントならその場で
 * 依頼者アカウントを新規作成する（web/src/auth.ts の line プロバイダ → backend /auth/line/exchange）。
 * /login の LINE ボタンも新規登録を兼ねるため、両画面とも「同意したものとみなします」のみなし同意をやめ、
 * メール登録フォーム（/signup 手順3）と同じ必須チェックをボタンの上に置き、同意前はボタンを無効にする。
 * 押せるかどうかの判定は lib/line-consent.ts の純関数（単体テストあり）に寄せ、ここは描画だけを持つ。
 *
 * 無効化したボタンには、理由（同意が必要なこと）を aria-describedby で結ぶ。
 * ボタンの色（LINE のブランドカラー）は変えない（コントラストの扱いは運営判断の待ち・M-11）。
 */
export function LineConsentAuth({
  label = "LINEで続ける",
  callbackUrl,
}: {
  label?: string;
  /** ログイン成功後の遷移先。呼び出し元の既存ログインフローの遷移先と揃えること。 */
  callbackUrl: string;
}) {
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);
  const baseId = useId();
  const checkboxId = `${baseId}-line-agree`;
  const hintId = `${baseId}-line-hint`;
  const enabled = canStartLineAuth({ agreed, busy });
  const hint = lineConsentHint({ agreed, busy });
  return (
    <div className="line-consent">
      <div className="line-consent__agree">
        <input
          type="checkbox"
          className="line-consent__cb"
          id={checkboxId}
          checked={agreed}
          required
          aria-required="true"
          onChange={(e) => setAgreed(e.target.checked)}
        />
        <label htmlFor={checkboxId}>
          <Link href="/terms">利用規約</Link>および<Link href="/privacy">プライバシーポリシー</Link>に同意します
          <span className="req">必須</span>
        </label>
      </div>
      <button
        type="button"
        className="btn-line-auth"
        disabled={!enabled}
        aria-describedby={hint ? hintId : undefined}
        onClick={() => {
          // disabled の取りこぼし（古いブラウザ・支援技術の操作）に備え、押下時にも判定し直す。
          if (!canStartLineAuth({ agreed, busy })) return;
          setBusy(true);
          void signIn("line", { callbackUrl });
        }}
      >
        {label}
      </button>
      {hint ? (
        <p id={hintId} className="line-consent__hint">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

/** 信頼行（暗号化通信 / プライバシー / 無料）。認証4画面で共用する。
 *  N-15（2周目監査・低）: 「SSL暗号化通信」は実態（TLS）と合わないため「TLS（HTTPS）による暗号化通信」にした。
 *  QA M1 是正: 3項目めは「無料ログイン」だったが、無料なのはログインではなく登録・利用そのもの
 *  （BRIEF §2.5）。/login・/signup にあった同内容のローカル複製はこの共通部品に統合した。 */
export function TrustRow() {
  return (
    <div className="trust-row">
      <div className="trust-item">
        <svg viewBox="0 0 24 24">
          <path d="M12 2L3 7v5c0 5.25 3.75 10.15 9 11.35C17.25 22.15 21 17.25 21 12V7L12 2z" />
          <path d="M9 12l2 2 4-4" />
        </svg>
        TLS（HTTPS）による暗号化通信
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
        登録・利用は無料
      </div>
    </div>
  );
}
