"use client";

/** 業者: 案件詳細 + 入札フォーム。住所詳細はマスクされている。 */

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Spinner } from "@/components/Icon";
import {
  Card,
  Notice,
  StatusBadge,
  btnPrimary,
  inputBase,
  useToken,
} from "@/components/kdz/Ui";
import { DisclosureNotice } from "@/components/kdz/DisclosureNotice";
import {
  CASE_STATUS_LABEL,
  createBid,
  formatYen,
  getCaseMasked,
  photoSrc,
  toDisplayMessage,
  type CaseMasked,
} from "@/lib/katadzuke-api";

export default function OperatorCaseDetailPage() {
  const params = useParams<{ id: string }>();
  const caseId = params.id;
  const { token, loading } = useToken();

  const [caseData, setCaseData] = useState<CaseMasked | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [amount, setAmount] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const reload = useCallback(async () => {
    if (!token) return;
    try {
      setCaseData(await getCaseMasked(caseId, token));
    } catch (e) {
      setError(toDisplayMessage(e, "取得に失敗しました"));
    }
  }, [caseId, token]);

  useEffect(() => {
    void reload();
  }, [reload]);

  async function submitBid(e: React.FormEvent) {
    e.preventDefault();
    if (!token || busy) return;
    const value = Number(amount);
    if (!Number.isFinite(value) || value <= 0) {
      setError("有効な金額を入力してください。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await createBid(caseId, { amount: value, message: message.trim() || undefined }, token);
      await reload();
    } catch (err) {
      setError(toDisplayMessage(err, "入札に失敗しました"));
    } finally {
      setBusy(false);
    }
  }

  if (loading || (!caseData && !error)) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center">
        <Spinner className="h-6 w-6 text-brand-600" />
      </div>
    );
  }

  if (!caseData) {
    return (
      <div className="container-aw max-w-3xl py-10">
        <Notice tone="error">{error ?? "案件が見つかりません。"}</Notice>
      </div>
    );
  }

  const canBid =
    (caseData.status === "open" || caseData.status === "bidding") && !caseData.my_bid;

  return (
    <div className="container-aw max-w-3xl space-y-6 py-10">
      {error ? <Notice tone="error">{error}</Notice> : null}

      <Card>
        <div className="flex items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-bold text-slate-900">{caseData.purpose}</h1>
            <p className="mt-1 text-sm text-slate-500">
              {caseData.prefecture} {caseData.city}
              <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-400">
                詳細住所は落札後に開示
              </span>
            </p>
            <p className="mt-0.5 text-xs text-slate-400">
              {caseData.housing_type ?? "—"} / {caseData.floor_plan ?? "—"} /{" "}
              {caseData.floor_number != null ? `${caseData.floor_number}階` : "階数—"} / EV
              {caseData.has_elevator == null ? "—" : caseData.has_elevator ? "あり" : "なし"}
            </p>
          </div>
          <StatusBadge value={caseData.status} label={CASE_STATUS_LABEL[caseData.status]} />
        </div>

        <div className="mt-4">
          {/* 連絡先開示ルールの明記（実データ配線は今後対応。現状は成約前の文言で固定） */}
          <DisclosureNotice viewer="operator" disclosed={false} awaitingApproval={false} />
        </div>

        {caseData.photos.length > 0 && (
          <ul className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
            {caseData.photos.map((p) => (
              <li key={p.id}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={photoSrc(p.url)}
                  alt=""
                  className="aspect-square w-full rounded-xl border border-slate-200 object-cover"
                />
              </li>
            ))}
          </ul>
        )}

        {caseData.ai_summary ? (
          <div className="mt-4 rounded-xl bg-slate-50 p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">AI 要約</p>
            <p className="mt-1.5 text-sm leading-relaxed text-slate-700">{caseData.ai_summary}</p>
          </div>
        ) : null}
      </Card>

      {/* 入札フォーム / 自社入札状況 */}
      {caseData.my_bid ? (
        <Card>
          <h2 className="font-bold text-slate-900">自社の入札</h2>
          <p className="mt-2 text-lg font-bold text-brand-700">
            {formatYen(caseData.my_bid.amount)}
            <StatusBadge
              value={caseData.my_bid.status}
              label={
                { pending: "選定待ち", selected: "落札", rejected: "未選定" }[
                  caseData.my_bid.status
                ]
              }
            />
          </p>
          {caseData.my_bid.message ? (
            <p className="mt-2 text-sm text-slate-600">{caseData.my_bid.message}</p>
          ) : null}
          {caseData.my_bid.status === "selected" && caseData.my_bid.transaction_id ? (
            <a
              href={`/operator/transactions/${caseData.my_bid.transaction_id}`}
              className={`${btnPrimary} mt-4`}
            >
              落札管理へ（住所詳細を確認）
            </a>
          ) : null}
        </Card>
      ) : canBid ? (
        <Card>
          <h2 className="font-bold text-slate-900">入札する</h2>
          <p className="mt-1 text-sm text-slate-500">
            買取額と回収費用を踏まえた「お客様への提示額」を入力してください。
            入札は 1 案件につき 1 回のみです。
          </p>
          <form onSubmit={submitBid} className="mt-4 space-y-4">
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-700">
                提示額（円） <span className="text-red-500">*</span>
              </span>
              <input
                type="number"
                required
                min={1}
                step={1000}
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                className={inputBase}
                placeholder="50000"
              />
            </label>
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-700">
                メッセージ（任意・お客様に表示されます）
              </span>
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                rows={3}
                className={inputBase}
                placeholder="搬出経路の確認のため、当日は2名で伺います。"
              />
            </label>
            <button type="submit" disabled={busy} className={btnPrimary}>
              {busy ? "送信中…" : "この金額で入札する"}
            </button>
          </form>
        </Card>
      ) : (
        <Notice tone="info">この案件は入札を受け付けていません。</Notice>
      )}

      <a
        href="/operator/cases"
        className="inline-block text-sm font-semibold text-brand-700 hover:underline"
      >
        ← 案件一覧へ
      </a>
    </div>
  );
}
