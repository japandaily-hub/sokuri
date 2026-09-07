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
import { ApprovalPendingNotice } from "@/components/kdz/ApprovalPendingNotice";
import { ConfirmModal } from "@/components/kdz/ConfirmModal";
import { Ic } from "@/components/kdz/Icons";
import { useToken } from "@/components/kdz/Ui";
import { formatPurposeLabel } from "@/lib/case-labels";
import { DisclosureNotice } from "@/components/kdz/DisclosureNotice";
import {
  BID_STATUS_LABEL,
  CASE_ITEM_CONDITION_LABEL,
  CASE_STATUS_LABEL,
  KdzApiError,
  createBid,
  formatYen,
  getCaseMasked,
  getOperatorProfile,
  listBids,
  photoSrc,
  toAlbums,
  toDisplayMessage,
  updateMyBid,
  type BidOut,
  type BidStatus,
  type CaseMasked,
} from "@/lib/katadzuke-api";

/**
 * 入札額の許容範囲・刻み。ダッシュボード（operator/page.tsx）と同一値・同一文言に揃える
 * （r10 M1: 詳細画面だけ「0円より大きい」しか検証しておらず、1,000円未満や刻み違反が
 *  backend の 422 で初めて弾かれていた）。backend は le=100_000_000。
 */
const BID_MIN = 1000;
const BID_MAX = 100_000_000;
const BID_STEP = 1000;
const BID_RANGE_HINT = "入札額は1,000円〜1億円の範囲で1,000円単位で入力してください";

/** 自社入札ステータスのチップCSSクラス（operator-shared.css の .status-chip バリアント）。 */
const BID_STATUS_CHIP_CLASS: Record<BidStatus, string> = {
  selected: "bidding",
  rejected: "done",
  withdrawn: "done",
  pending: "negotiating",
};

export default function OperatorCaseDetailPage() {
  const params = useParams<{ id: string }>();
  const caseId = params.id;
  const { token, loading } = useToken();

  const [caseData, setCaseData] = useState<CaseMasked | null>(null);
  const [error, setError] = useState<string | null>(null);
  /**
   * 入札状況（2026-09-07 方針転換: 他社の入札額を匿名で開示する）。
   * GET /cases/{id}/bids は自社分は全フィールド、他社分は operator/message/transaction_id
   * を null にして返す（is_mine で判別）。取得失敗時は null のままにし、
   * caseData.top_bid_amount / is_top_bidder（backend 未対応時は undefined）へ
   * フォールバック表示する。
   */
  const [bids, setBids] = useState<BidOut[] | null>(null);
  /** backend detail.code。approval_required の場合は raw エラー文言の代わりに ApprovalPendingNotice を出す（決定1）。 */
  const [errorCode, setErrorCode] = useState<string | undefined>(undefined);
  const [amount, setAmount] = useState("");
  const [bidDone, setBidDone] = useState(false);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [vendorStatus, setVendorStatus] = useState<string | null>(null);
  const [hasLicense, setHasLicense] = useState<boolean | null>(null);
  /** 入札額の引き上げフォーム（自社入札が既にある場合に表示）。 */
  const [raiseAmount, setRaiseAmount] = useState("");
  const [raiseError, setRaiseError] = useState<string | null>(null);
  const [raiseBusy, setRaiseBusy] = useState(false);
  const [raiseDone, setRaiseDone] = useState(false);
  const [raiseMessage, setRaiseMessage] = useState("");
  /**
   * raiseMessage を自社の現在のコメントでプリフィルした対象の bid id。
   * 同じ bid の間は reload() のたびに再プリフィルしない（入力中の値を消さないため）。
   */
  const [raiseMessagePrefilledFor, setRaiseMessagePrefilledFor] = useState<string | null>(null);
  /** ConfirmModal 表示中の引き上げ先金額（null の間は非表示）。 */
  const [raiseConfirmAmount, setRaiseConfirmAmount] = useState<number | null>(null);

  const reload = useCallback(async () => {
    if (!token) return;
    try {
      setCaseData(await getCaseMasked(caseId, token));
      setErrorCode(undefined);
    } catch (e) {
      setError(toDisplayMessage(e, "取得に失敗しました"));
      setErrorCode(e instanceof KdzApiError ? e.code : undefined);
    }
    // 入札状況カードの表示用。案件取得の403（審査中）とは独立して失敗しうるため、
    // 別途 catch して null のまま（＝caseData.top_bid_amount へのフォールバック表示）にする。
    try {
      setBids(await listBids(caseId, token));
    } catch {
      setBids(null);
    }
  }, [caseId, token]);

  // 承認状態（vendor_status）を取得して入札フォームの表示を出し分ける。
  // null=取得中（フォームを出さずチラつきを防ぐ）。取得失敗時は "unknown" として
  // フォームを表示し、サーバー側ゲート（get_verified_operator の403）に委ねる。
  useEffect(() => {
    if (!token) return;
    getOperatorProfile(token)
      .then((p) => {
        setVendorStatus(p.vendor_status);
        setHasLicense(p.license_image_uploaded_at != null);
      })
      .catch(() => setVendorStatus("unknown"));
  }, [token]);

  useEffect(() => {
    void reload();
  }, [reload]);

  // 引き上げフォームのメッセージ欄に現在の自社コメントをプリフィルする。
  // 同一 bid の間は一度だけ（ユーザーの入力を reload 後に上書きしないため）。
  useEffect(() => {
    const bid = caseData?.my_bid;
    if (bid && raiseMessagePrefilledFor !== bid.id) {
      setRaiseMessage(bid.message ?? "");
      setRaiseMessagePrefilledFor(bid.id);
    }
  }, [caseData?.my_bid, raiseMessagePrefilledFor]);

  async function submitBid(e: React.FormEvent) {
    e.preventDefault();
    if (!token || busy) return;
    const value = Number(amount);
    if (
      !Number.isFinite(value) ||
      !Number.isInteger(value) ||
      value < BID_MIN ||
      value > BID_MAX ||
      value % BID_STEP !== 0
    ) {
      setError(BID_RANGE_HINT);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await createBid(caseId, { amount: value, message: message.trim() || undefined }, token);
      setBidDone(true);
      await reload();
    } catch (err) {
      setError(toDisplayMessage(err, "入札に失敗しました"));
      // 409（他社落札・出品取り下げ等で入札を受け付けられない状態）の場合、フォームに
      // 古い案件状態が残ったままだと再送信を誘発する。案件データを再取得し、
      // canBid の判定材料（status・my_bid）を最新化して古いフォームを消す。
      if (err instanceof KdzApiError && err.status === 409) {
        await reload();
      }
    } finally {
      setBusy(false);
    }
  }

  /**
   * 引き上げフォームの入力を検証し、問題なければ ConfirmModal を開く（送信自体は
   * confirmRaise で行う）。現在額と同じ検証範囲（BID_MIN/MAX/STEP）に加え、
   * 「現在額より高い」ことをフロント側でも先に弾く（backend の 409 を待たず案内する）。
   */
  function requestRaise() {
    if (!caseData?.my_bid) return;
    const current = caseData.my_bid.amount;
    const value = Number(raiseAmount);
    if (
      !Number.isFinite(value) ||
      !Number.isInteger(value) ||
      value < BID_MIN ||
      value > BID_MAX ||
      value % BID_STEP !== 0
    ) {
      setRaiseError(BID_RANGE_HINT);
      return;
    }
    if (value <= current) {
      setRaiseError("新しい金額は現在の入札額より高い金額にしてください（下げることはできません）");
      return;
    }
    setRaiseError(null);
    setRaiseConfirmAmount(value);
  }

  async function confirmRaise() {
    if (!token || raiseBusy || raiseConfirmAmount == null || !caseData?.my_bid) return;
    setRaiseBusy(true);
    setRaiseError(null);
    try {
      // message は「変更があった場合だけ」body に含める（未変更なら省略して現状維持、
      // 空にした場合は null を送って明示的にクリアする）。backend は body に message
      // キーが無ければ更新しない仕様のため、undefined を送るのではなくキー自体を省く。
      const originalMessage = (caseData.my_bid.message ?? "").trim();
      const nextMessage = raiseMessage.trim();
      const payload: { amount: number; message?: string | null } = { amount: raiseConfirmAmount };
      if (nextMessage !== originalMessage) {
        payload.message = nextMessage === "" ? null : nextMessage;
      }
      await updateMyBid(caseId, payload, token);
      setRaiseConfirmAmount(null);
      setRaiseAmount("");
      setRaiseDone(true);
      await reload();
    } catch (err) {
      setRaiseConfirmAmount(null);
      setRaiseError(toDisplayMessage(err, "入札額の引き上げに失敗しました"));
      // 409（案件が受付外・入札が pending 以外・amount が現在額以下）の場合は
      // 最新の案件状態を取り直してフォームの前提（現在額・ステータス）を合わせる。
      if (err instanceof KdzApiError && err.status === 409) {
        await reload();
      }
    } finally {
      setRaiseBusy(false);
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
          {errorCode === "approval_required" ? (
            // 決定1: 審査中（pending/rejected）業者への 403 は raw エラーの代わりにこの案内を出す。
            <ApprovalPendingNotice hasLicenseImage={hasLicense} vendorStatus={vendorStatus} />
          ) : (
            <div className="op-alert error">{error ?? "案件が見つかりません。"}</div>
          )}
        </div>
      </div>
    );
  }

  const canBid = (caseData.status === "open" || caseData.status === "bidding") && !caseData.my_bid;
  // 自社入札が pending かつ案件が受付中（open/bidding）の間は、金額を現在額より
  // 高い方向にのみ何度でも引き上げられる（下げ不可・成約後は不可）。
  const canRaise =
    caseData.my_bid != null &&
    caseData.my_bid.status === "pending" &&
    (caseData.status === "open" || caseData.status === "bidding");
  // 承認前（pending/limited）はサーバーが入札を403で拒否するため、フォームの代わりに案内を出す。
  const statusLoading = vendorStatus === null;
  const awaitingApproval = !statusLoading && vendorStatus !== "active" && vendorStatus !== "unknown";

  // ===== 入札状況（他社の入札額を匿名で開示。社名・コメントは非開示） =====
  // bids（GET /cases/{id}/bids）が取得できていればそれを正とし、is_mine で自社/他社を
  // 判別する。is_mine === true を第一判定とし、undefined（backend 未対応）の場合のみ
  // my_bid.id との一致にフォールバックする。false を自社扱いにはしない。
  const myBidId = caseData.my_bid?.id;
  const isMineBid = (b: BidOut) => (b.is_mine === undefined ? b.id === myBidId : b.is_mine === true);
  const otherBids = (bids ?? []).filter((b) => !isMineBid(b));
  // 案件が open/bidding 以外（成約後等）は backend が他社分を返さず top_bid_amount/
  // is_top_bidder も null になる仕様。bids に自社分しか含まれていない状態で
  // reduce すると「自社額＝最高額」に見えてしまうため、open/bidding 以外では
  // 一覧からの最高額算出自体を行わない。
  const bidsUsableForTop = caseData.status === "open" || caseData.status === "bidding";
  const topBidFromList =
    bidsUsableForTop && (bids ?? []).length > 0
      ? bids!.reduce((a, b) => (b.amount > a.amount ? b : a))
      : null;
  const topBidAmount = bidsUsableForTop ? (topBidFromList?.amount ?? caseData.top_bid_amount ?? null) : null;
  // 入札社数は bids（他社分を条件付きでしか返さない＝limited業者・受付終了後は自社分のみ、
  // 停止中/退会業者は除外）の配列長では正しく数えられないため、常に backend 集計値
  // （取り下げ以外の全入札数）である caseData.bid_count を用いる。
  const bidderCount = caseData.bid_count;
  // 首位判定は backend の is_top_bidder を第一に使う（同額は首位扱い）。undefined
  // （backend 未対応）の場合のみ my_bid.amount >= topBidAmount にフォールバックする。
  // 配列先頭要素の id 一致による判定は、同額時に自社が首位でも false になり
  // 「あと¥0で首位」と誤表示する不具合があったため廃止。
  const isTopBidder = !bidsUsableForTop || !caseData.my_bid
    ? null
    : caseData.is_top_bidder !== undefined
      ? caseData.is_top_bidder
      : topBidAmount != null
        ? caseData.my_bid.amount >= topBidAmount
        : null;
  const gapAmount =
    caseData.my_bid && topBidAmount != null && topBidAmount > caseData.my_bid.amount
      ? topBidAmount - caseData.my_bid.amount
      : null;

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
                  <img
                    src={photoSrc(p.url)}
                    alt=""
                    onError={(e) => {
                      // 決定1: 写真取得が403等で失敗した場合は壊れた画像アイコンを出さず空表示にする。
                      e.currentTarget.style.display = "none";
                    }}
                  />
                </div>
              ))}
              {caseData.photos.length > 2 ? (
                <div className="listing-more">+{caseData.photos.length - 2}</div>
              ) : null}
            </div>
            <div className="listing-info">
              <div className="listing-title">{formatPurposeLabel(caseData.purpose)}</div>
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

          {toAlbums(caseData).map((album) => (
            <div className="op-card" key={album.id ?? "unassigned"}>
              {album.title ? (
                <div className="op-album-head">
                  <h2>{album.title}</h2>
                  {album.condition ? (
                    <span className="status-chip negotiating">
                      {CASE_ITEM_CONDITION_LABEL[album.condition] ?? album.condition}
                    </span>
                  ) : null}
                </div>
              ) : (
                <h2>お預かりしている写真</h2>
              )}
              {album.description ? <p className="op-album-summary">{album.description}</p> : null}
              <div className="op-photo-grid">
                {album.photos.map((p) => (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={photoSrc(p.url)}
                    alt=""
                    key={p.id}
                    onError={(e) => {
                      // 決定1: 写真取得が403等で失敗した場合は壊れた画像アイコンを出さず空表示にする。
                      e.currentTarget.style.display = "none";
                    }}
                  />
                ))}
              </div>
            </div>
          ))}

          {caseData.ai_summary ? (
            <div className="op-card">
              <p className="op-ai-summary">AI要約</p>
              <p>{caseData.ai_summary}</p>
            </div>
          ) : null}

          {/* ===== 入札フォーム / 自社入札状況 ===== */}
          {bidDone ? (
            <div className="op-alert success" role="status">
              {/* r10 M5 是正: 業者アカウントに LINE 連携は無い（LINE通知は依頼者側の機能）。
                  実際の通知経路は登録メールアドレスのみ。 */}
              入札を受け付けました。お客様が業者を選ぶまでお待ちください（結果は登録メールアドレスにお知らせします）。
            </div>
          ) : null}
          {topBidAmount != null || bidderCount > 0 ? (
            <div className="op-card">
              <h2 style={{ marginBottom: 8 }}>入札状況</h2>
              {topBidAmount == null ? (
                // 案件が成約等で open/bidding 以外に移った場合、backend は他社分の
                // 開示を止める（top_bid_amount/is_top_bidder が null）。自社分のみの
                // 一覧から「最高額」を計算すると誤表示になるため、その旨を案内する。
                <p style={{ fontSize: 14, color: "var(--body-soft)" }}>入札状況は成約後は表示されません</p>
              ) : (
                <>
                  <p style={{ fontSize: 14, color: "var(--body)", marginBottom: caseData.my_bid ? 8 : 4 }}>
                    現在の最高額 <strong>¥{formatYen(topBidAmount).replace("円", "")}</strong>
                    （{bidderCount}社）
                  </p>
                  {caseData.my_bid ? (
                    isTopBidder === true ? (
                      <span className="status-chip live">自社が最高額です</span>
                    ) : isTopBidder === false ? (
                      <span className="status-chip negotiating">
                        他社が上回っています{gapAmount != null ? `（差額 ¥${formatYen(gapAmount).replace("円", "")}）` : ""}
                      </span>
                    ) : null
                  ) : null}
                  {otherBids.length > 0 ? (
                    <ul className="op-other-bids" style={{ marginTop: 12, paddingLeft: 18, fontSize: 13, color: "var(--body-soft)", lineHeight: 1.9 }}>
                      {otherBids.map((b) => (
                        <li key={b.id}>
                          他社 ¥{formatYen(b.amount).replace("円", "")}
                          {b.revision_count > 0 ? `（引き上げ ${b.revision_count} 回）` : ""}
                          ・更新 {new Date(b.updated_at).toLocaleString("ja-JP")}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  <p style={{ fontSize: 12, color: "var(--body-soft)", marginTop: 10, lineHeight: 1.8 }}>
                    他社の入札額は匿名で表示されます（社名・コメントは非開示）
                  </p>
                </>
              )}
            </div>
          ) : null}

          {caseData.my_bid ? (
            <div className="op-card my-bid-card">
              <h2 style={{ marginBottom: 0 }}>自社の入札</h2>
              <div className="amount">
                <span>¥</span>
                {formatYen(caseData.my_bid.amount).replace("円", "")}
              </div>
              <span className={`status-chip ${BID_STATUS_CHIP_CLASS[caseData.my_bid.status]}`}>
                {BID_STATUS_LABEL[caseData.my_bid.status]}
              </span>
              {caseData.my_bid.revision_count > 0 ? (
                <span className="status-chip negotiating" style={{ marginLeft: 6 }}>
                  引き上げ {caseData.my_bid.revision_count} 回
                </span>
              ) : null}
              {caseData.my_bid.message ? <p className="comment">{caseData.my_bid.message}</p> : null}
              {caseData.my_bid.status === "selected" && caseData.my_bid.transaction_id ? (
                <Link
                  href={`/operator/transactions/${caseData.my_bid.transaction_id}`}
                  className="btn btn-primary"
                  style={{ marginTop: 16, display: "inline-flex" }}
                >
                  取引詳細へ（住所詳細を確認）
                  <Ic name="arrow" />
                </Link>
              ) : null}
            </div>
          ) : null}

          {raiseDone ? (
            <div className="op-alert success" role="status">
              入札額を引き上げました。
            </div>
          ) : null}
          {canRaise && caseData.my_bid ? (
            <form
              className="form-card"
              onSubmit={(e) => {
                e.preventDefault();
                requestRaise();
              }}
            >
              <h2
                style={{
                  fontFamily: "var(--head)",
                  fontSize: 15,
                  fontWeight: 400,
                  color: isTopBidder === false ? "var(--danger)" : "var(--navy)",
                  marginBottom: 4,
                  borderLeft: `2px solid ${isTopBidder === false ? "var(--danger)" : "var(--primary)"}`,
                  paddingLeft: 12,
                }}
              >
                入札額を引き上げる
                {isTopBidder === false && gapAmount != null
                  ? `（あと¥${formatYen(gapAmount).replace("円", "")}で最高額に並びます）`
                  : ""}
              </h2>
              <p style={{ fontSize: 13, color: "var(--body-soft)", marginBottom: 18, lineHeight: 1.8 }}>
                現在の入札額は<strong>¥{formatYen(caseData.my_bid.amount).replace("円", "")}</strong>です。金額は成約が決まるまで何度でも引き上げられます（下げることはできません）。他社の入札額は匿名で表示されます（社名・コメントは非開示）。
              </p>
              {raiseError ? <div className="op-alert error" style={{ marginBottom: 12 }}>{raiseError}</div> : null}
              <div className="field">
                <label htmlFor="raiseAmount">
                  新しい提示額（円） <span className="req">必須</span>
                </label>
                <div className="yen-input-wrap">
                  <span className="yen-prefix">¥</span>
                  <input
                    id="raiseAmount"
                    type="number"
                    required
                    min={caseData.my_bid.amount + BID_STEP}
                    max={BID_MAX}
                    step={BID_STEP}
                    value={raiseAmount}
                    onChange={(e) => setRaiseAmount(e.target.value)}
                    placeholder={String(caseData.my_bid.amount + BID_STEP)}
                    aria-describedby="raiseAmountHint"
                  />
                </div>
                <p id="raiseAmountHint" style={{ fontSize: 12, color: "var(--body-soft)", marginTop: 6, lineHeight: 1.8 }}>
                  現在額より高い金額のみ入力できます（1,000円単位）
                  <br />
                  <span style={{ fontSize: 11.5 }}>{BID_RANGE_HINT}</span>
                </p>
              </div>
              <div className="field">
                <label htmlFor="raiseMessage">
                  メッセージ <span className="opt">任意・お客様に表示されます</span>
                </label>
                <textarea
                  id="raiseMessage"
                  value={raiseMessage}
                  onChange={(e) => setRaiseMessage(e.target.value)}
                  rows={3}
                  placeholder="金額を見直しました。ぜひご検討ください。"
                />
              </div>
              <button type="submit" disabled={raiseBusy} className="btn btn-primary btn-block">
                {raiseBusy ? "送信中…" : "この金額に引き上げる"}
              </button>
              <p style={{ fontSize: 11.5, color: "var(--body-soft)", marginTop: 8, lineHeight: 1.8 }}>
                引き上げは1,000円以上・1入札につき最大20回まで
              </p>
            </form>
          ) : null}

          {raiseConfirmAmount != null && caseData.my_bid ? (
            <ConfirmModal
              title="入札額を引き上げますか？"
              message={`¥${formatYen(caseData.my_bid.amount).replace("円", "")} → ¥${formatYen(raiseConfirmAmount).replace("円", "")} に引き上げます。この操作は取り消せません。`}
              confirmLabel="引き上げる"
              busy={raiseBusy}
              error={raiseError}
              onCancel={() => setRaiseConfirmAmount(null)}
              onConfirm={() => void confirmRaise()}
            />
          ) : null}

          {!caseData.my_bid && canBid && statusLoading ? (
            <div className="op-card" style={{ display: "flex", justifyContent: "center", padding: 24 }}>
              <Spinner className="h-5 w-5 text-brand-600" />
            </div>
          ) : canBid && awaitingApproval ? (
            <ApprovalPendingNotice hasLicenseImage={hasLicense} vendorStatus={vendorStatus} />
          ) : canBid ? (
            <form className="form-card" onSubmit={submitBid}>
              <h2 style={{ fontFamily: "var(--head)", fontSize: 15, fontWeight: 400, color: "var(--navy)", marginBottom: 4, borderLeft: "2px solid var(--primary)", paddingLeft: 12 }}>
                入札する
              </h2>
              <p style={{ fontSize: 13, color: "var(--body-soft)", marginBottom: 18, lineHeight: 1.8 }}>
                買取額と回収費用を踏まえた「お客様への提示額」を入力してください。金額は成約が決まるまで何度でも引き上げられます（下げることはできません）。他社の入札額は匿名で表示されます（社名・コメントは非開示）。
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
                    min={BID_MIN}
                    max={BID_MAX}
                    step={BID_STEP}
                    value={amount}
                    onChange={(e) => setAmount(e.target.value)}
                    placeholder="50000"
                    aria-describedby="bidAmountHint"
                  />
                </div>
                {/* r10 M1 是正: ダッシュボードの入札フォームにだけあった手数料注記・範囲ヒントを
                    詳細画面にも同文言で置く（同じ操作なのに条件の説明が片方に無かった）。 */}
                <p id="bidAmountHint" style={{ fontSize: 12, color: "var(--body-soft)", marginTop: 6, lineHeight: 1.8 }}>
                  他社の入札額は匿名で表示されます（社名・コメントは非開示）
                  <br />
                  成約時のみ買取額の8%（税別・消費税を別途加算）が手数料
                  <br />
                  ※サービス開始当初（β期間）は手数料を請求しません。請求開始の際は事前にメールでお知らせします。
                  <br />
                  <span style={{ fontSize: 11.5 }}>{BID_RANGE_HINT}</span>
                </p>
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

          <Link href="/operator/cases" style={{ display: "inline-block", marginTop: 8, fontSize: 13.5, fontWeight: 600, color: "var(--blue)" }}>
            ← 案件一覧へ
          </Link>
        </div>
      </main>
    </div>
  );
}
