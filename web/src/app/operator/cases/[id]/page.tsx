"use client";

/**
 * 業者: 案件詳細 + 入札フォーム（/operator/cases/[id]）。
 *
 * デザインレビュー B-1 対応: 旧 Tailwind/slate 実装を廃し、ダッシュボード・共通フォーム
 * （katazuke-pages.css の .form-card/.field/.btn）と同じ視覚言語に統一。
 * .listing-card/.op-card/.my-bid-card 等は operator-shared.css に定義済み。
 * OperatorHeader を追加しナビ不能だった問題も解消。
 * 機能ロジック（getCaseMasked・createBid）は変更していない。住所詳細はマスク済み。
 */

import "../../operator-shared.css";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { Spinner } from "@/components/Icon";
import { OperatorHeader } from "@/components/kdz/OperatorHeader";
import { Ic } from "@/components/kdz/Icons";
import { useToken } from "@/components/kdz/Ui";
import { DisclosureNotice } from "@/components/kdz/DisclosureNotice";
import {
  CASE_STATUS_LABEL,
  createBid,
  formatYen,
  getCaseMasked,
  getOperatorProfile,
  photoSrc,
  toDisplayMessage,
  type CaseMasked,
} from "@/lib/katadzuke-api";

const MY_BID_STATUS_LABEL: Record<string, string> = {
  pending: "選定待ち",
  selected: "落札",
  rejected: "未選定",
};

export default function OperatorCaseDetailPage() {
  const params = useParams<{ id: string }>();
  const caseId = params.id;
  const { token, loading } = useToken();

  const [caseData, setCaseData] = useState<CaseMasked | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [amount, setAmount] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [vendorStatus, setVendorStatus] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!token) return;
    try {
      setCaseData(await getCaseMasked(caseId, token));
    } catch (e) {
      setError(toDisplayMessage(e, "取得に失敗しました"));
    }
  }, [caseId, token]);

  // 承認状態（vendor_status）を取得して入札フォームの表示を出し分ける。
  // null=取得中（フォームを出さずチラつきを防ぐ）。取得失敗時は "unknown" として
  // フォームを表示し、サーバー側ゲート（get_verified_operator の403）に委ねる。
  useEffect(() => {
    if (!token) return;
    getOperatorProfile(token)
      .then((p) => setVendorStatus(p.vendor_status))
      .catch(() => setVendorStatus("unknown"));
  }, [token]);

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
      <div className="case-detail-page">
        <OperatorHeader active="cases" />
        <div style={{ display: "flex", minHeight: "50vh", alignItems: "center", justifyContent: "center" }}>
          <Spinner className="h-6 w-6 text-brand-600" />
        </div>
      </div>
    );
  }

  if (!caseData) {
    return (
      <div className="case-detail-page">
        <OperatorHeader active="cases" />
        <div className="op-wrap narrow">
          <div className="op-alert error">{error ?? "案件が見つかりません。"}</div>
        </div>
      </div>
    );
  }

  const canBid = (caseData.status === "open" || caseData.status === "bidding") && !caseData.my_bid;
  // 承認前（pending/limited）はサーバーが入札を403で拒否するため、フォームの代わりに案内を出す。
  const statusLoading = vendorStatus === null;
  const awaitingApproval = !statusLoading && vendorStatus !== "active" && vendorStatus !== "unknown";

  return (
    <div className="case-detail-page">
      <OperatorHeader active="cases" />
      <main id="main">
        <div className="op-wrap narrow">
          {error ? <div className="op-alert error">{error}</div> : null}

          {/* ===== 案件サマリー ===== */}
          <div className="listing-card">
            <div className="listing-thumbs">
              {caseData.photos.slice(0, 2).map((p) => (
                <div className="listing-thumb" key={p.id}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={photoSrc(p.url)} alt="" />
                </div>
              ))}
              {caseData.photos.length > 2 ? (
                <div className="listing-more">+{caseData.photos.length - 2}</div>
              ) : null}
            </div>
            <div className="listing-info">
              <div className="listing-title">{caseData.purpose}</div>
              <div className="listing-meta">
                {caseData.prefecture} {caseData.city}（詳細住所は落札後に開示）
              </div>
              <div className="listing-meta">
                {caseData.housing_type ?? "—"} / {caseData.floor_plan ?? "—"} /{" "}
                {caseData.floor_number != null ? `${caseData.floor_number}階` : "階数—"} / EV
                {caseData.has_elevator == null ? "—" : caseData.has_elevator ? "あり" : "なし"}
              </div>
            </div>
            <div
              className={`listing-status-badge ${
                caseData.status === "closed" ? "badge-done" : caseData.bid_count > 0 ? "badge-active" : "badge-waiting"
              }`}
            >
              {CASE_STATUS_LABEL[caseData.status]}
            </div>
          </div>

          <div className="op-card">
            <DisclosureNotice viewer="operator" disclosed={false} awaitingApproval={false} />
          </div>

          {caseData.photos.length > 0 ? (
            <div className="op-card">
              <h2>お預かりしている写真</h2>
              <div className="op-photo-grid">
                {caseData.photos.map((p) => (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={photoSrc(p.url)} alt="" key={p.id} />
                ))}
              </div>
            </div>
          ) : null}

          {caseData.ai_summary ? (
            <div className="op-card">
              <p className="op-ai-summary">AI要約</p>
              <p>{caseData.ai_summary}</p>
            </div>
          ) : null}

          {/* ===== 入札フォーム / 自社入札状況 ===== */}
          {caseData.my_bid ? (
            <div className="op-card my-bid-card">
              <h2 style={{ marginBottom: 0 }}>自社の入札</h2>
              <div className="amount">
                <span>¥</span>
                {formatYen(caseData.my_bid.amount).replace("円", "")}
              </div>
              <span className={`status-chip ${caseData.my_bid.status === "selected" ? "bidding" : caseData.my_bid.status === "rejected" ? "done" : "negotiating"}`}>
                {MY_BID_STATUS_LABEL[caseData.my_bid.status]}
              </span>
              {caseData.my_bid.message ? <p className="comment">{caseData.my_bid.message}</p> : null}
              {caseData.my_bid.status === "selected" && caseData.my_bid.transaction_id ? (
                <Link
                  href={`/operator/transactions/${caseData.my_bid.transaction_id}`}
                  className="btn btn-primary"
                  style={{ marginTop: 16, display: "inline-flex" }}
                >
                  落札管理へ（住所詳細を確認）
                  <Ic name="arrow" className="arw" />
                </Link>
              ) : null}
            </div>
          ) : canBid && statusLoading ? (
            <div className="op-card" style={{ display: "flex", justifyContent: "center", padding: 24 }}>
              <Spinner className="h-5 w-5 text-brand-600" />
            </div>
          ) : canBid && awaitingApproval ? (
            <div className="op-alert info">
              アカウントは承認待ちです。運営による審査完了後に入札できるようになります（案件の閲覧は承認前でも可能です）。
            </div>
          ) : canBid ? (
            <form className="form-card" onSubmit={submitBid}>
              <h2 style={{ fontFamily: "var(--head)", fontSize: 15, fontWeight: 700, color: "var(--navy)", marginBottom: 4 }}>
                入札する
              </h2>
              <p style={{ fontSize: 13, color: "var(--body-soft)", marginBottom: 18, lineHeight: 1.8 }}>
                買取額と回収費用を踏まえた「お客様への提示額」を入力してください。入札は1案件につき1回のみです。
              </p>
              <div className="field">
                <label htmlFor="bidAmount">
                  提示額（円） <span className="req">必須</span>
                </label>
                <div className="yen-input-wrap">
                  <span className="yen-prefix">¥</span>
                  <input
                    id="bidAmount"
                    type="number"
                    required
                    min={1}
                    step={1000}
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    placeholder="50000"
                  />
                </div>
              </div>
              <div className="field">
                <label htmlFor="bidMessage">
                  メッセージ <span className="opt">任意・お客様に表示されます</span>
                </label>
                <textarea
                  id="bidMessage"
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  rows={3}
                  placeholder="搬出経路の確認のため、当日は2名で伺います。"
                />
              </div>
              <button type="submit" disabled={busy} className="btn btn-primary btn-block">
                {busy ? "送信中…" : "この金額で入札する"}
              </button>
            </form>
          ) : (
            <div className="op-alert info">この案件は入札を受け付けていません。</div>
          )}

          <Link href="/operator/cases" style={{ display: "inline-block", marginTop: 8, fontSize: 13.5, fontWeight: 700, color: "var(--blue)" }}>
            ← 案件一覧へ
          </Link>
        </div>
      </main>
    </div>
  );
}
