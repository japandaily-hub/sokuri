"use client";

/** メールアドレスの確認についての案内（bareルート / 共通ヘッダー・フッターなし）。
 *
 *  H-1: バックエンドにメールアドレス確認の API は無い（2026-10-06 時点で backend/app に
 *  verify_email 系の処理は 0 件）。確認していないのに「確認が完了しました」と出すと虚偽の表示に
 *  なるため、完了表示はしない。URL の ?email= は表示しない（任意の文字列を公式画面に出せる＝
 *  なりすましの文面に使えるため）。?token= が付いている場合は「この画面では確認していない」ことと、
 *  心当たりがない場合の連絡先を案内する（トークンの値は画面に出さない）。確認 API を実装したら、
 *  成功応答を受けたときだけ完了を出し、表示するアドレスはサーバーの応答の値を使うこと。
 *  noindex は layout.tsx で付けている。 */

import "./verify-email.css";

import { Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Ic } from "@/components/kdz/Icons";
import { KdzLogo } from "@/components/kdz/Logo";

function VerifyEmailContent() {
  const params = useSearchParams();
  // トークンは有無で案内を分けるだけに使う（値は検証も表示もしない）。
  const hasToken = (params.get("token") ?? "").trim().length > 0;

  return (
    <main id="main" className="verify-page">
      {/* N-10（2周目監査）: スキップリンク（#main）の飛び先を持たせる（h1 は下の確認カードにある）。 */}
      <Link href="/" className="confirm-logo" aria-label="カタヅケ トップへ">
        <KdzLogo size={22} />
      </Link>

      <div className="confirm-card">
        {/* アイコン（確認 API が無いため、完了を示す紙吹雪は出さない） */}
        <div className="confirm-ic-wrap">
          <div className="confirm-circle">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M22 13V6a2 2 0 00-2-2H4a2 2 0 00-2 2v12a2 2 0 002 2h9" />
              <path d="M22 6l-10 7L2 6" />
              <path d="M16 19l2 2 4-4" />
            </svg>
          </div>
        </div>

        <h1 className="confirm-title">
          メールアドレスの
          <br />
          確認について
        </h1>
        {hasToken ? (
          <p className="confirm-sub">
            この画面では、メールアドレスの確認の処理を行っていません。
            <br />
            心当たりのないメールのリンクからこの画面を開いた場合は、情報を入力せず、お問い合わせからご連絡ください。
          </p>
        ) : (
          <p className="confirm-sub">
            現在、カタヅケではメールアドレスの確認手続きを行っていません。
            <br />
            会員登録がお済みの方は、ログインしてそのままご利用いただけます。
          </p>
        )}

        {/* ステップ */}
        <div className="welcome-steps">
          <div className="welcome-step">
            <div className="ws-num">1</div>
            <div className="ws-body">
              <strong>出品する</strong>
              <span>品物を1点ずつ撮って出品します。</span>
            </div>
          </div>
          <div className="welcome-step">
            <div className="ws-num">2</div>
            <div className="ws-body">
              <strong>入札を待つ</strong>
              <span>登録業者が入札します。入札が届くとお知らせします。</span>
            </div>
          </div>
          <div className="welcome-step">
            <div className="ws-num">3</div>
            <div className="ws-body">
              <strong>業者を選んで引き取り</strong>
              <span>届いた入札から1社を選びます。お支払い方法は、成約後にご案内します。訪問の日程は、取引画面で業者が出す日時の候補から選んで決めます。</span>
            </div>
          </div>
        </div>

        <Link href="/login" className="btn btn-primary btn-block btn-lg">
          ログインする
          <Ic name="arrow" />
        </Link>
        <Link href="/" className="btn btn-ghost btn-block btn-swipe" style={{ marginTop: 10 }}>
          トップへ戻る
        </Link>
      </div>

      <div className="confirm-bottom">
        <Link href="/faq">よくある質問</Link>
        {"　·　"}
        <Link href="/contact">お問い合わせ</Link>
      </div>
    </main>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense>
      <VerifyEmailContent />
    </Suspense>
  );
}
