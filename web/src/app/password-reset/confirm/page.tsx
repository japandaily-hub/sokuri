"use client";

/** 新しいパスワードの設定（/password-reset/confirm?token=...&type=user|operator）。
 *  再設定メールのリンク先。token は最初の描画後に読み取ってメモリにだけ持ち、アドレスバーと履歴からは
 *  すぐに消す（共有・画面の写り込み・戻る操作での再表示を防ぐ）。Referrer を送らない・検索に載せない指定は
 *  layout.tsx のメタデータで行う。成功後はログインへ案内する（自動ログインはしない）。 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { KdzLogo } from "@/components/kdz/Logo";
import { Field, PasswordField } from "@/components/kdz/auth";
import { KdzApiError } from "@/lib/katadzuke-api";
import {
  RESET_PASSWORD_MAX_LENGTH,
  RESET_PASSWORD_MIN_LENGTH,
  confirmPasswordReset,
  toResetAccountType,
  type ResetAccountType,
} from "../reset-api";
import "../password-reset.css";

const TOKEN_RE = /^[A-Za-z0-9_-]{32,128}$/;
const CONFIRM_PATH = "/password-reset/confirm";

type LinkState =
  | { status: "loading" }
  | { status: "missing" }
  | { status: "ready"; token: string; accountType: ResetAccountType };

/** 新しいパスワードの入力を検証し、問題があれば利用者向けの文言を返す（問題なければ null）。 */
function validateNewPassword(password: string, confirmation: string): { pw?: string; pw2?: string } | null {
  if (password.length < RESET_PASSWORD_MIN_LENGTH) {
    return { pw: `${RESET_PASSWORD_MIN_LENGTH}文字以上で入力してください` };
  }
  if (password.length > RESET_PASSWORD_MAX_LENGTH) {
    return { pw: `${RESET_PASSWORD_MAX_LENGTH}文字以内で入力してください` };
  }
  if (password !== confirmation) {
    return { pw2: "確認用のパスワードが一致しません" };
  }
  return null;
}

export default function PasswordResetConfirmPage() {
  const [link, setLink] = useState<LinkState>({ status: "loading" });
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [fieldErr, setFieldErr] = useState<{ pw?: string; pw2?: string }>({});
  const [error, setError] = useState<string | null>(null);
  const [linkInvalid, setLinkInvalid] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    // useSearchParams ではなく location から1回だけ読む（読んだ直後に URL から token を消すため）。
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token") ?? "";
    const accountType = toResetAccountType(params.get("type"));
    window.history.replaceState(window.history.state, "", CONFIRM_PATH);
    setLink(TOKEN_RE.test(token) ? { status: "ready", token, accountType } : { status: "missing" });
  }, []);

  const accountType = link.status === "ready" ? link.accountType : "user";
  const loginHref = accountType === "operator" ? "/operator/login" : "/login";
  const restartHref = accountType === "operator" ? "/password-reset?type=operator" : "/password-reset";

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (busy || link.status !== "ready") return;
    const invalid = validateNewPassword(password, confirmation);
    setFieldErr(invalid ?? {});
    if (invalid) return;
    setError(null);
    setBusy(true);
    try {
      await confirmPasswordReset(link.token, link.accountType, password);
      setPassword("");
      setConfirmation("");
      setDone(true);
    } catch (err) {
      if (err instanceof KdzApiError) {
        setError(err.message);
        // 無効・期限切れ・使用済み（1回限り）は同じリンクでは再試行できないため、手続きのやり直しへ案内する。
        if (err.code === "password_reset_invalid") setLinkInvalid(true);
      } else {
        setError("通信に失敗しました。電波の状況を確かめて、もう一度お試しください。");
      }
    } finally {
      setBusy(false);
    }
  }

  let body: React.ReactNode;
  if (link.status === "loading") {
    body = null;
  } else if (done) {
    body = (
      <div className="reset-card" role="status">
        <div className="done-ic" aria-hidden="true">
          <svg viewBox="0 0 24 24">
            <path d="M5 12.5l4.5 4.5L19 7.5" />
          </svg>
        </div>
        <div className="reset-panel-title">パスワードを再設定しました</div>
        <p className="reset-panel-sub">
          新しいパスワードでログインしてください。安全のため、ほかの端末のログイン状態は解除しています。
        </p>
        <Link href={loginHref} className="btn btn-primary btn-block btn-lg">
          ログインへ進む
        </Link>
      </div>
    );
  } else if (link.status === "missing" || linkInvalid) {
    body = (
      <div className="reset-card">
        <div className="reset-panel-title">このリンクは使えません</div>
        <p className="reset-panel-sub">
          {error ??
            "再設定のリンクが無効か、有効期限が切れています。お手数ですが、もう一度パスワード再設定の手続きをしてください。"}
        </p>
        <Link href={restartHref} className="btn btn-primary btn-block btn-lg">
          再設定の手続きをやり直す
        </Link>
        <div className="reset-back">
          <Link href={loginHref}>ログインに戻る</Link>
        </div>
      </div>
    );
  } else {
    body = (
      <div className="reset-card reset-wrap">
        <div className="reset-panel-title">新しいパスワードの設定</div>
        <p className="reset-panel-sub">
          {accountType === "operator" ? "業者アカウント" : "ご依頼の方のアカウント"}
          の新しいパスワードを入力してください。
        </p>

        {error ? (
          <div className="auth-error" role="alert">
            {error}
          </div>
        ) : null}

        <form onSubmit={onSubmit} noValidate>
          <Field label="新しいパスワード" htmlFor="reset-new-pw" error={fieldErr.pw ?? null}>
            <PasswordField
              id="reset-new-pw"
              value={password}
              onChange={setPassword}
              placeholder={`${RESET_PASSWORD_MIN_LENGTH}文字以上`}
              autoComplete="new-password"
              minLength={RESET_PASSWORD_MIN_LENGTH}
            />
            <p className="reset-hint">
              {RESET_PASSWORD_MIN_LENGTH}文字以上{RESET_PASSWORD_MAX_LENGTH}文字以内で設定してください。
            </p>
          </Field>
          <Field label="新しいパスワード（確認）" htmlFor="reset-new-pw2" error={fieldErr.pw2 ?? null}>
            <PasswordField
              id="reset-new-pw2"
              value={confirmation}
              onChange={setConfirmation}
              placeholder="もう一度入力"
              autoComplete="new-password"
              minLength={RESET_PASSWORD_MIN_LENGTH}
            />
          </Field>

          <button type="submit" className="btn btn-primary btn-block btn-lg" disabled={busy}>
            {busy ? "設定中…" : "パスワードを再設定する"}
          </button>
        </form>

        <div className="reset-back">
          <Link href={loginHref}>ログインに戻る</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="reset-page">
      <Link href="/" className="reset-logo" aria-label="カタヅケ トップへ">
        <KdzLogo size={22} />
      </Link>
      {body}
    </div>
  );
}
