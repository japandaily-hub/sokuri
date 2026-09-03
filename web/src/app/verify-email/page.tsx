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

const CONFETTI_COLORS = ["#1447e0", "#8fb4ff", "#e5a323", "#6f93f2", "#f3981d", "#d7e6ff"];

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
          ご登録
          <br />
          ありがとうございます。
        </h1>
        <p className="confirm-sub">
          登録いただいたメールアドレスはこちらです。
          <br />
          さっそく出品を始めましょう。
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
              <strong>業者を選んで引き取り</strong>
              <span>気に入った業者を選べばOK。支払方法や日程は業者ごとに異なるため、チャットでご確認ください。</span>
            </div>
          </div>
        </div>

        <Link href="/create" className="btn btn-primary btn-block btn-lg">
          さっそく出品してみる
          <Ic name="arrow" />
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
