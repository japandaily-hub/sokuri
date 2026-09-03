/** パスワード再設定（/password-reset）。
 *  バックエンドのパスワード再設定API（送信/確認/更新）は未配線のため、
 *  虚偽の成功表示（メール送信済み・パスワード変更完了）は行わず、
 *  「準備中」である旨を正直に伝える単一パネルのみを表示する。
 *  ログインできない利用者には /contact への導線を主CTAとして提供する。 */

import Link from "next/link";
import { KdzLogo } from "@/components/kdz/Logo";
import "./password-reset.css";

export default function PasswordResetPage() {
  return (
    <div className="reset-page">
      <Link href="/" className="reset-logo" aria-label="カタヅケ トップへ">
        <KdzLogo size={22} />
      </Link>

      <div className="reset-card">
        <div className="reset-panel-title">パスワード再設定は準備中です</div>
        <p className="reset-panel-sub">
          パスワード再設定は現在準備中です。
          <br />
          ログインできない場合は、お問い合わせフォームからご連絡ください（登録メールアドレスを添えてください）。
        </p>
        <Link href="/contact" className="btn btn-primary btn-block btn-lg">
          お問い合わせフォームへ
        </Link>
        <div className="reset-back">
          <Link href="/login">ログインに戻る</Link>
        </div>
      </div>
    </div>
  );
}
