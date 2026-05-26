"use client";

/**
 * /album/submitted — 一括査定依頼完了画面（Phase 2 Wizard of Oz）
 *
 * Phase 1 では業者連携は手動運用。ここでユーザーのメール / LINE 連絡先を取得し、
 * 管理者が提携業者へ手動転送 → 入札結果をメールで返す。
 *
 * Phase 3 以降: バックエンドに albums テーブル + 業者通知 API を実装し
 * このページを「入札状況待ち」リアルタイム画面へ進化させる。
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { Icon } from "@/components/Icon";

const SESSION_KEY_ALBUM = "aw_album_v1";

interface AlbumSummary {
  total: number;
  count: number;
}

const yen = (n: number) =>
  new Intl.NumberFormat("ja-JP", {
    style: "currency",
    currency: "JPY",
    maximumFractionDigits: 0,
  }).format(n);

export default function AlbumSubmittedPage() {
  const [summary, setSummary] = useState<AlbumSummary | null>(null);
  const [email, setEmail] = useState("");
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    const raw = sessionStorage.getItem(SESSION_KEY_ALBUM);
    if (!raw) return;
    try {
      const parsed = JSON.parse(raw) as AlbumSummary;
      setSummary({ total: parsed.total, count: parsed.count });
    } catch {
      // ignore
    }
  }, []);

  /**
   * メール送信ハンドラ。
   * Phase 1 では実バックエンドへの送信はせず、localStorage に控えるのみ
   * （管理者が手動でアルバム内容と紐づける運用）。
   * Phase 2 で /api/v1/albums エンドポイント実装後にここを差し替え。
   */
  const handleSubscribe = (e: React.FormEvent) => {
    e.preventDefault();
    if (!email) return;
    // [推測] バックエンド未実装。localStorage に控えるだけ。
    try {
      localStorage.setItem("aw_album_lead_email", email);
    } catch {
      /* ignore quota errors */
    }
    setSubmitted(true);
  };

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-slate-50 py-10 sm:py-16">
      <div className="container-aw max-w-2xl">
        {/* 成功アイコン */}
        <div className="flex justify-center">
          <span className="flex h-16 w-16 items-center justify-center rounded-full bg-accent-100 text-accent-600 ring-4 ring-accent-50">
            <Icon name="check-circle" className="h-8 w-8" strokeWidth={2} />
          </span>
        </div>

        <h1 className="mt-6 text-center text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
          アルバムを受け付けました
        </h1>
        <p className="mt-3 text-center text-sm leading-relaxed text-slate-600">
          提携業者へ匿名で査定依頼を送信します。あなたの連絡先は
          <strong className="font-semibold text-slate-900">成約決定までは業者へ伝わりません</strong>
          。営業電話は一切ありません。
        </p>

        {/* アルバムサマリ */}
        {summary && (
          <div className="mt-8 rounded-2xl border border-slate-200 bg-white p-6 shadow-card">
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              送信内容
            </p>
            <div className="mt-3 flex items-baseline justify-between">
              <span className="text-sm text-slate-700">アルバム内アイテム数</span>
              <span className="text-lg font-bold tracking-tight text-slate-900">
                {summary.count} 点
              </span>
            </div>
            <div className="mt-2 flex items-baseline justify-between">
              <span className="text-sm text-slate-700">AI 試算 合計</span>
              <span className="text-xl font-bold tracking-tight text-brand-700">
                {yen(summary.total)}
              </span>
            </div>
            <p className="mt-3 text-[11px] leading-relaxed text-slate-500">
              ※ 業者の最終入札額は AI 試算と異なる場合があります（一般に出張回収費を差し引いた金額になります）。
            </p>
          </div>
        )}

        {/* 連絡先取得（Phase 1: ローカル保存のみ） */}
        <div className="mt-8 rounded-2xl border border-slate-200 bg-white p-6 shadow-card">
          <h2 className="text-base font-bold text-slate-900">入札結果の通知先</h2>
          <p className="mt-1.5 text-sm leading-relaxed text-slate-600">
            業者の入札が出揃いましたら、こちらのメールへ
            <strong className="font-semibold text-slate-900">最高額の業者名と金額のみ</strong>
            をお知らせします（営業電話は一切ありません）。
          </p>

          {submitted ? (
            <div
              role="status"
              className="mt-4 flex items-center gap-2 rounded-xl border border-accent-200 bg-accent-50 px-3.5 py-3 text-sm text-accent-700"
            >
              <Icon name="check" className="h-4 w-4" strokeWidth={2.5} />
              通知先を受け付けました。入札結果は通常 24〜48 時間以内にお届けします。
            </div>
          ) : (
            <form className="mt-4 flex flex-col gap-2 sm:flex-row" onSubmit={handleSubscribe}>
              <label htmlFor="email" className="sr-only">
                メールアドレス
              </label>
              <input
                id="email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="example@mail.com"
                className="flex-1 rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm shadow-xs focus-visible:border-brand-500 focus-visible:ring-2 focus-visible:ring-brand-200"
              />
              <button
                type="submit"
                className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white shadow-cta transition-colors hover:bg-brand-700 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:ring-offset-2"
              >
                通知先を登録
                <Icon name="arrow-right" className="h-4 w-4" strokeWidth={2.25} />
              </button>
            </form>
          )}
        </div>

        {/* 次のアクション */}
        <div className="mt-8 flex flex-col items-center gap-3">
          <Link
            href="/album"
            className="text-sm font-semibold text-brand-700 hover:underline"
          >
            別のアルバムを作る
          </Link>
          <Link href="/" className="text-sm text-slate-500 hover:text-slate-700">
            トップへ戻る
          </Link>
        </div>
      </div>
    </div>
  );
}
