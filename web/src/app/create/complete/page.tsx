"use client";

/**
 * 出品完了（/create/complete）。
 * デザイン正典: docs/design_handoff_katazuke/出品完了.html をピクセル忠実に再現。
 * このルートは SiteChrome の BARE_PREFIXES（/create）対象で共通クロムが付かないため、
 * ページ自身が最小ヘッダー・背景・完了カードを描く。
 *
 * クライアント化の理由（純表示では不可）:
 *  - 受付番号のランダム生成（マウント後に確定 → SSR/CSR ハイドレーション差異を避ける）
 *  - 入札締切までのカウントダウン（localStorage に開始時刻を保持）
 *  - LINE連携ボタン（バックエンド未配線のため準備中トースト表示）
 */

import "./complete.css";

import { useEffect, useState } from "react";
import Link from "next/link";
import { KdzLogo } from "@/components/kdz/Logo";

const COUNTDOWN_KEY = "katazuke_done_start";
const TOTAL_MS = 3 * 24 * 3600 * 1000; // 入札期間 3日間

function pad(n: number): string {
  return n < 10 ? `0${n}` : String(n);
}

function formatRemaining(remainingMs: number): string {
  if (remainingMs <= 0) return "終了";
  const totalSec = Math.floor(remainingMs / 1000);
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  return `${pad(h)}:${pad(m)}:${pad(s)}`;
}

export default function CreateCompletePage() {
  // SSR と CSR で同一マークアップを保つため初期値はプレースホルダにし、マウント後に確定する。
  const [lotId, setLotId] = useState("KTZ-2026-00001");
  const [timer, setTimer] = useState("72:00:00");
  const [lineToast, setLineToast] = useState(false);

  // 受付番号の動的生成（デモ。実際の lot 番号はバックエンド発番に差し替える）
  useEffect(() => {
    const suffix = String(Math.floor(Math.random() * 90000) + 10000);
    setLotId(`KTZ-2026-${suffix}`);
  }, []);

  // 入札締切カウントダウン
  useEffect(() => {
    let start = Number(window.localStorage.getItem(COUNTDOWN_KEY));
    if (!start || Number.isNaN(start)) {
      start = Date.now();
      window.localStorage.setItem(COUNTDOWN_KEY, String(start));
    }

    let frame: number | undefined;
    const tick = () => {
      const remaining = Math.max(0, TOTAL_MS - (Date.now() - start));
      setTimer(formatRemaining(remaining));
      if (remaining > 0) {
        frame = window.setTimeout(tick, 1000);
      }
    };
    tick();

    return () => {
      if (frame !== undefined) window.clearTimeout(frame);
    };
  }, []);

  // LINE連携（バックエンド未配線）: 虚偽の遷移はせず準備中トーストのみ
  function onLineLink() {
    setLineToast(true);
    window.setTimeout(() => setLineToast(false), 3000);
  }

  return (
    <div className="done-page">
      {/* 最小ヘッダー（ロゴのみ） */}
      <header className="done-header">
        <Link href="/" aria-label="カタヅケ トップへ">
          <KdzLogo size={20} />
        </Link>
      </header>

      <main className="done-main">
        <div className="done-card">
          {/* 完了アイコン（描画アニメ） */}
          <div className="done-circle">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M4 12.5l5.5 5.5L20 7" />
            </svg>
          </div>

          <h1 className="done-title">出品が完了しました！</h1>
          <p className="done-sub">
            写真と品目を業者に公開しました。
            <br />
            入札期間の<strong>3日間</strong>、業者が競い合います。
          </p>

          {/* 受付番号 */}
          <div className="lot-id-box">
            <div className="lot-id-label">受付番号</div>
            <div className="lot-id-num">{lotId}</div>
            <div className="lot-id-note">入札状況はこの番号で確認できます</div>
          </div>

          {/* カウントダウン */}
          <div className="bid-timer">
            <span className="live-dot" aria-hidden="true" />
            <span>入札受付中　残り</span>
            <span className="timer-num">{timer}</span>
          </div>

          {/* 次のステップ */}
          <div className="next-steps">
            <div className="next-steps-title">この後の流れ</div>
            <div className="next-step">
              <div className="step-num">1</div>
              <div className="step-body">
                <div className="step-title">業者が入札</div>
                <div className="step-desc">
                  複数の業者がまとめ買取額を提示します。入札が届くとLINEに通知が届きます。
                </div>
                <span className="step-tag days">〜3日間</span>
              </div>
            </div>
            <div className="next-step">
              <div className="step-num">2</div>
              <div className="step-body">
                <div className="step-title">上位3社から連絡</div>
                <div className="step-desc">
                  入札上位3社のみがチャットで連絡します。それ以外は自動でお断り済みです。
                </div>
                <span className="step-tag line">LINEで通知</span>
              </div>
            </div>
            <div className="next-step">
              <div className="step-num">3</div>
              <div className="step-body">
                <div className="step-title">気に入った業者と交渉・成約</div>
                <div className="step-desc">
                  チャットで日程・条件を確認してから成約。成約後も費用はかかりません。
                </div>
              </div>
            </div>
          </div>

          {/* LINE連携 */}
          <div className="line-box">
            <div className="line-icon">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M20 10.2c0-4.5-4.5-8.2-10-8.2S0 5.7 0 10.2c0 4 3.6 7.5 8.5 8.1.3.1.7.3.8.6.1.3.1.7 0 1l-.1.7c0 .3-.2 1.2 1.1.6C12.1 20 18.9 16.1 21 13c.5-1 .9-2.2.9-3.4l.1-.4z" />
              </svg>
            </div>
            <div className="line-info">
              <div className="line-title">LINE通知を受け取りましょう</div>
              <div className="line-desc">
                入札・メッセージの通知が届きます。見逃し防止のため設定をおすすめします。
              </div>
            </div>
            <button type="button" className="line-btn" onClick={onLineLink}>
              LINE連携
            </button>
          </div>

          {/* ボタン */}
          <div className="done-btns">
            <Link href="/cases" className="btn btn-primary btn-lg">
              <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M9 6h11M9 12h11M9 18h11" />
                <circle cx="4" cy="6" r="1.5" fill="currentColor" />
                <circle cx="4" cy="12" r="1.5" fill="currentColor" />
                <circle cx="4" cy="18" r="1.5" fill="currentColor" />
              </svg>
              入札状況を確認する
            </Link>
            <Link href="/" className="btn btn-ghost">
              <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M3 12l9-9 9 9" />
                <path d="M5 10v9a1 1 0 001 1h4v-5h4v5h4a1 1 0 001-1v-9" />
              </svg>
              トップページへ戻る
            </Link>
          </div>
        </div>
      </main>

      {lineToast ? (
        <div className="kdz-toast" role="status">
          LINE連携は現在準備中です（デモ）
        </div>
      ) : null}
    </div>
  );
}
