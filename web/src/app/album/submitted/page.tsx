"use client";

/**
 * /album/submitted — 一括査定依頼完了画面（Phase 2 Wizard of Oz）
 *
 * Phase 1: フロントのみで localStorage に控える
 * Phase 2: バックエンド /api/v1/albums へ POST して永続化 ← 現在こちら
 * Phase 3: 業者通知 / 入札ステータス確認 API と接続予定
 *
 * lead_email は業者には絶対開示しない（ADR-002 該当節）。
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, createAlbum } from "@/lib/api";
import { Icon } from "@/components/Icon";

const SESSION_KEY_ALBUM = "aw_album_v1";

interface AlbumSummary {
  total: number;
  count: number;
  items?: { item_id?: string; assessment_id?: string }[];
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
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string>("");

  useEffect(() => {
    const raw = sessionStorage.getItem(SESSION_KEY_ALBUM);
    if (!raw) return;
    try {
      const parsed = JSON.parse(raw) as AlbumSummary;
      setSummary({ total: parsed.total, count: parsed.count, items: parsed.items });
    } catch {
      // ignore
    }
  }, []);

  /**
   * メール + アルバム永続化ハンドラ（Phase 2: 実 API 接続）。
   *
   * 1. sessionStorage から assessment_id 一覧を取り出す
   * 2. POST /api/v1/albums で永続化（lead_email 込み）
   * 3. 成功時のみ完了ステート
   *
   * エラー時はメッセージを表示し再送可能にする。バックエンド未到達でも UX を壊さない。
   */
  const handleSubscribe = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || submitting) return;

    setSubmitting(true);
    setErrorMessage("");

    const assessmentIds = (summary?.items ?? [])
      .map((it) => it.assessment_id)
      .filter((v): v is string => typeof v === "string" && v.length > 0);

    if (assessmentIds.length === 0) {
      // assessment_id が無いケース（古い sessionStorage 等）はメールだけ保存して継続
      try {
        localStorage.setItem("aw_album_lead_email", email);
      } catch {
        /* ignore quota */
      }
      setSubmitted(true);
      setSubmitting(false);
      return;
    }

    try {
      await createAlbum({
        assessment_ids: assessmentIds,
        total_estimated_jpy: summary?.total ?? 0,
        lead_email: email,
      });
      setSubmitted(true);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? `送信に失敗しました (${err.status}): ${err.message}`
          : "送信に失敗しました。通信状態を確認してもう一度お試しください。";
      setErrorMessage(message);
    } finally {
      setSubmitting(false);
    }
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
            <>
              <form className="mt-4 flex flex-col gap-2 sm:flex-row" onSubmit={handleSubscribe}>
                <label htmlFor="email" className="sr-only">
                  メールアドレス
                </label>
                <input
                  id="email"
                  type="email"
                  required
                  disabled={submitting}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="example@mail.com"
                  className="flex-1 rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm shadow-xs focus-visible:border-brand-500 focus-visible:ring-2 focus-visible:ring-brand-200 disabled:bg-slate-50"
                />
                <button
                  type="submit"
                  disabled={submitting}
                  className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-brand-600 px-5 py-2.5 text-sm font-semibold text-white shadow-cta transition-colors hover:bg-brand-700 focus-visible:ring-2 focus-visible:ring-brand-600 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-slate-300 disabled:shadow-none"
                >
                  {submitting ? "送信中…" : "通知先を登録"}
                  {!submitting && (
                    <Icon name="arrow-right" className="h-4 w-4" strokeWidth={2.25} />
                  )}
                </button>
              </form>
              {errorMessage && (
                <p
                  role="alert"
                  aria-live="assertive"
                  className="mt-3 flex items-start gap-2 rounded-xl border border-red-200 bg-red-50 px-3.5 py-3 text-sm text-red-700"
                >
                  <Icon name="alert" className="mt-0.5 h-4 w-4 shrink-0" />
                  {errorMessage}
                </p>
              )}
            </>
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
