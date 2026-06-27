"use client";

/** メールアドレス確認完了（bareルート / 共通ヘッダー・フッターなし）。
 *  全画面中央寄せカード + confettiアニメ + 3ステップ説明。
 *  メールは URLパラメータ ?email= から取得（デモ表示用）。
 *  実際の確認処理はバックエンド未配線のため、本ページは「確認完了」表示のみを担う。 */

import "./verify-email.css";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Ic } from "@/components/kdz/Icons";
import { KdzLogo } from "@/components/kdz/Logo";

const CONFETTI_COLORS = ["#1f54de", "#6fa3ff", "#f0a030", "#1f8a5b", "#e05c5c", "#9b59b6"];

type ConfettiDot = {
  background: string;
  left: string;
  top: string;
  animationDelay: string;
  animationDuration: string;
};

function VerifyEmailContent() {
  const params = useSearchParams();
  const email = params.get("email") || "example@email.com";

  /* confetti は Math.random を使うため、ハイドレーション不一致回避にマウント後に生成 */
  const [dots, setDots] = useState<ConfettiDot[]>([]);
  useEffect(() => {
    const next: ConfettiDot[] = [];
    for (let i = 0; i < 12; i++) {
      next.push({
        background: CONFETTI_COLORS[i % CONFETTI_COLORS.length],
        left: `${Math.random() * 100 - 10}%`,
        top: `${Math.random() * 20 - 10}%`,
        animationDelay: `${i * 0.07}s`,
        animationDuration: `${0.9 + Math.random() * 0.6}s`,
      });
    }
    setDots(next);
  }, []);

  return (
    <div className="verify-page">
      <Link href="/" className="confirm-logo" aria-label="カタヅケ トップへ">
        <KdzLogo size={22} />
      </Link>

      <div className="confirm-card">
        {/* アイコン（confetti はマウント後に重ねる） */}
        <div className="confirm-ic-wrap">
          <div className="confirm-circle">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M22 13V6a2 2 0 00-2-2H4a2 2 0 00-2 2v12a2 2 0 002 2h9" />
              <path d="M22 6l-10 7L2 6" />
              <path d="M16 19l2 2 4-4" />
            </svg>
          </div>
          {dots.map((d, i) => (
            <span
              key={i}
              className="confetti-dot"
              style={{
                background: d.background,
                left: d.left,
                top: d.top,
                animationDelay: d.animationDelay,
                animationDuration: d.animationDuration,
              }}
            />
          ))}
        </div>

        <h1 className="confirm-title">
          メールアドレスを
          <br />
          確認しました！
        </h1>
        <p className="confirm-sub">
          以下のアドレスの確認が完了しました。
          <br />
          カタヅケのすべての機能がご利用いただけます。
        </p>
        <div className="confirm-email">{email}</div>

        {/* ステップ */}
        <div className="welcome-steps">
          <div className="welcome-step">
            <div className="ws-num">1</div>
            <div className="ws-body">
              <strong>出品する</strong>
              <span>写真を撮って不用品を出品。5分で完了します。</span>
            </div>
          </div>
          <div className="welcome-step">
            <div className="ws-num">2</div>
            <div className="ws-body">
              <strong>入札を待つ</strong>
              <span>登録業者が競い合って入札。自動的にお知らせが届きます。</span>
            </div>
          </div>
          <div className="welcome-step">
            <div className="ws-num">3</div>
            <div className="ws-body">
              <strong>業者を選んで現金受け取り</strong>
              <span>気に入った業者を選べばOK。自宅で即日現金を受け取れます。</span>
            </div>
          </div>
        </div>

        <Link href="/create" className="btn btn-primary btn-block btn-lg">
          さっそく出品してみる
          <Ic name="arrow" className="arw" />
        </Link>
        <Link href="/" className="btn btn-ghost btn-block" style={{ marginTop: 10 }}>
          トップページへ
        </Link>
      </div>

      <div className="confirm-bottom">
        <Link href="/login">ログイン</Link>
        {"　·　"}
        <Link href="/faq">よくある質問</Link>
        {"　·　"}
        <Link href="/contact">お問い合わせ</Link>
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense>
      <VerifyEmailContent />
    </Suspense>
  );
}
