"use client";

import "./result.css";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Ic } from "@/components/kdz/Icons";
import { AppHeader } from "@/components/kdz/AppHeader";

/* ============================================================
   査定結果ページ（カタヅケ）
   バックエンド未配線：入札データはモック定数。
   「決める」→確認モーダル→デモトースト→選択完了状態。
   3状態: 'waiting'(査定中) / 'revealed'(入札あり) / 'selected'(選択完了)
   デモ切替バーで手動切替可能。
   ============================================================ */

type DemoState = "waiting" | "revealed" | "selected";

/** 入札業者データ（デモ用モック） */
type BidVendor = {
  id: number;
  rank: 1 | 2 | 3;
  initial: string;
  name: string;
  color: string;
  rating: number;
  reviewCount: number;
  amount: number;
  tags: string[];
  comment: string;
};

const BIDS: BidVendor[] = [
  {
    id: 1,
    rank: 1,
    initial: "バ",
    name: "株式会社バリュー東京",
    color: "#1f54de",
    rating: 4.8,
    reviewCount: 156,
    amount: 54000,
    tags: ["即日対応", "家電特化", "搬出無料"],
    comment:
      "家電・ブランド品を専門スタッフが丁寧に査定します。まとめてお持ちの方が有利です。即日訪問も対応可能ですのでお気軽にご相談ください。",
  },
  {
    id: 2,
    rank: 2,
    initial: "サ",
    name: "リサイクル侍",
    color: "#1f8a5b",
    rating: 4.6,
    reviewCount: 89,
    amount: 47500,
    tags: ["ブランド特化", "丁寧査定"],
    comment:
      "ブランド品・時計を中心に高額査定中。分かりやすい見積もりと丁寧な説明で安心してお任せいただけます。",
  },
  {
    id: 3,
    rank: 3,
    initial: "ハ",
    name: "ハウスクリア関東",
    color: "#7c5cbf",
    rating: 4.4,
    reviewCount: 204,
    amount: 41000,
    tags: ["遺品整理", "搬出無料", "実績多数"],
    comment:
      "家まるごと片付けが得意です。処分費用ゼロを目指して1点1点丁寧に査定いたします。",
  },
];

const RANK_LABELS: Record<number, string> = { 1: "最高額", 2: "2位", 3: "3位" };
const RANK_CLASSES: Record<number, string> = {
  1: "bid-rank-1",
  2: "bid-rank-2",
  3: "bid-rank-3",
};

/** 星文字列（塗り★ + 空☆） */
function starString(filled: number): string {
  return "★".repeat(Math.round(filled)) + "☆".repeat(Math.max(0, 5 - Math.round(filled)));
}

const pad2 = (n: number) => String(n).padStart(2, "0");

/** 選択済み業者の情報 */
type SelectedVendor = { initial: string; name: string; color: string; amount: number };

export default function ResultPage() {
  /* ---- デモ状態 ---- */
  const [demoState, setDemoState] = useState<DemoState>("revealed");

  /* ---- カウントダウン（2日14時間33分から開始） ---- */
  const [cdDays, setCdDays] = useState(2);
  const [cdHours, setCdHours] = useState(14);
  const [cdMins, setCdMins] = useState(33);
  const [cdSecs, setCdSecs] = useState(22);

  useEffect(() => {
    const id = window.setInterval(() => {
      setCdSecs((s) => {
        if (s > 0) return s - 1;
        setCdMins((m) => {
          if (m > 0) return m - 1;
          setCdHours((h) => {
            if (h > 0) return h - 1;
            setCdDays((d) => (d > 0 ? d - 1 : 0));
            return h > 0 ? 23 : 0;
          });
          return m > 0 ? 59 : 0;
        });
        return 59;
      });
    }, 1000);
    return () => window.clearInterval(id);
  }, []);

  /* ---- 確認モーダル ---- */
  const [modalVendor, setModalVendor] = useState<BidVendor | null>(null);

  function openModal(vendor: BidVendor) {
    setModalVendor(vendor);
  }
  function closeModal() {
    setModalVendor(null);
  }

  /* ---- 選択完了 ---- */
  const [selectedVendor, setSelectedVendor] = useState<SelectedVendor | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const toastTimerRef = useRef<number | null>(null);

  function confirmSelect() {
    if (!modalVendor) return;
    const v = modalVendor;
    setSelectedVendor({ initial: v.initial, name: v.name, color: v.color, amount: v.amount });
    closeModal();
    /* デモトースト */
    setToast("業者を決定しました（デモ）");
    if (toastTimerRef.current) window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setToast(null), 2400);
    setDemoState("selected");
  }

  /* ステータスバッジ種別 */
  const badgeClass =
    demoState === "waiting"
      ? "listing-status-badge badge-waiting"
      : demoState === "revealed"
        ? "listing-status-badge badge-active"
        : "listing-status-badge badge-done";
  const badgeLabel =
    demoState === "waiting" ? "入札受付中" : demoState === "revealed" ? "入札あり" : "選択完了";

  /* モーダル外クリックで閉じる */
  function onOverlayClick(e: React.MouseEvent<HTMLDivElement>) {
    if (e.target === e.currentTarget) closeModal();
  }

  return (
    <div className="result-page">
      <AppHeader unread />

      {/* デモ切替バー */}
      <div className="rdemo-bar">
        <span className="rdemo-bar-label">デモ表示</span>
        <div className="rdemo-tabs">
          {(["waiting", "revealed", "selected"] as DemoState[]).map((s) => {
            const labels: Record<DemoState, string> = { waiting: "査定中", revealed: "入札あり", selected: "選択完了" };
            return (
              <button
                key={s}
                type="button"
                className={`rdemo-tab${demoState === s ? " active" : ""}`}
                onClick={() => setDemoState(s)}
              >
                {labels[s]}
              </button>
            );
          })}
        </div>
      </div>

      <main>
        <div className="result-wrap">

          {/* ── 出品サマリーカード ── */}
          <div className="listing-card">
            <div className="listing-thumbs">
              <div className="listing-thumb" style={{ background: "#e8f0ee" }}>家電</div>
              <div className="listing-thumb" style={{ background: "#f0e8f4" }}>ブランド</div>
              <div className="listing-more">+3</div>
            </div>
            <div className="listing-info">
              <div className="listing-title">家電・ブランド品まとめ　5点</div>
              <div className="listing-meta">出品日：2026年6月20日　入札期間：3日間</div>
            </div>
            <div className={badgeClass}>{badgeLabel}</div>
          </div>

          {/* ── 査定中ブロック ── */}
          {demoState === "waiting" && (
            <div>
              <div className="waiting-banner">
                <div className="waiting-icon">
                  <Ic name="clock" />
                </div>
                <h2 className="waiting-title">入札受付中です</h2>
                <p className="waiting-sub">
                  登録業者があなたの出品内容を確認しています。
                  <br />
                  入札が届き次第、LINEとメールでお知らせします。
                </p>
                <div className="countdown">
                  <div className="countdown-unit">
                    <div className="countdown-num">{pad2(cdDays)}</div>
                    <div className="countdown-lbl">日</div>
                  </div>
                  <div className="countdown-sep">:</div>
                  <div className="countdown-unit">
                    <div className="countdown-num">{pad2(cdHours)}</div>
                    <div className="countdown-lbl">時間</div>
                  </div>
                  <div className="countdown-sep">:</div>
                  <div className="countdown-unit">
                    <div className="countdown-num">{pad2(cdMins)}</div>
                    <div className="countdown-lbl">分</div>
                  </div>
                  <div className="countdown-sep">:</div>
                  <div className="countdown-unit">
                    <div className="countdown-num">{pad2(cdSecs)}</div>
                    <div className="countdown-lbl">秒</div>
                  </div>
                </div>
              </div>
              {/* スケルトン3枚 */}
              <div className="skeleton-wrap">
                <p className="skeleton-hint">入札が届くと、ここに業者が表示されます</p>
                {[
                  { w1: "60%", w2: "40%" },
                  { w1: "55%", w2: "35%" },
                  { w1: "50%", w2: "38%" },
                ].map((widths, i) => (
                  <div className="skeleton-card" key={i}>
                    <div className="skel skel-circle" />
                    <div className="skel-lines">
                      <div className="skel" style={{ height: 16, width: widths.w1 }} />
                      <div className="skel" style={{ height: 12, width: widths.w2 }} />
                    </div>
                    <div className="skel skel-amount" />
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ── 入札ありブロック ── */}
          {demoState === "revealed" && (
            <div>
              <div className="bids-banner">
                <div className="bids-banner-ic">
                  <Ic name="crown" />
                </div>
                <div className="bids-banner-text">
                  <strong>3社から入札が届きました！</strong>
                  <span>3日以内に1社を選んで交渉を開始してください</span>
                </div>
                <div className="bids-deadline">
                  <span>期限まで</span>
                  <strong>残り1日</strong>
                </div>
              </div>

              {BIDS.map((bid) => (
                <div key={bid.id} className={`bid-card${bid.rank === 1 ? " top" : ""}`}>
                  {/* 業者ヘッダー */}
                  <div className="bid-card-head">
                    <div className="biz-avatar" style={{ background: bid.color }}>
                      {bid.initial}
                    </div>
                    <div className="biz-info">
                      <div className="biz-name">{bid.name}</div>
                      <div className="biz-rating">
                        <span className="biz-stars">{starString(bid.rating)}</span>
                        <span className="biz-rating-num">{bid.rating}</span>
                        <span>（口コミ{bid.reviewCount}件）</span>
                      </div>
                      <div className="biz-badges">
                        <span className="biz-badge biz-badge-verified">古物商許可済</span>
                        {bid.tags.map((tag) => (
                          <span key={tag} className="biz-badge biz-badge-tag">
                            {tag}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>

                  {/* 金額エリア */}
                  <div className="bid-amount-area">
                    {bid.rank === 1 ? (
                      <div className="bid-badge-top">
                        <Ic name="crown" />
                        最高額
                      </div>
                    ) : (
                      <div className={`bid-rank ${RANK_CLASSES[bid.rank]}`}>
                        {RANK_LABELS[bid.rank]}
                      </div>
                    )}
                    <div className="bid-amount-right">
                      <div className="bid-amount">
                        <span className="bid-amount-yen">¥</span>
                        {bid.amount.toLocaleString("ja-JP")}
                      </div>
                      <div className="bid-note">5点まとめ・搬出込み</div>
                    </div>
                  </div>

                  {/* コメント */}
                  <p className="bid-comment">
                    <span className="bid-comment-ic" aria-hidden="true">
                      <Ic name="chat" />
                    </span>
                    {bid.comment}
                  </p>

                  {/* アクション */}
                  <div className="bid-actions">
                    <Link href="/vendors/1" className="btn-bid-detail">
                      詳細を見る
                    </Link>
                    <button
                      type="button"
                      className="btn-bid-select"
                      onClick={() => openModal(bid)}
                    >
                      この業者に決める
                      <svg viewBox="0 0 24 24" aria-hidden="true">
                        <path d="M5 12.5l4.5 4.5L19 7" />
                      </svg>
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* ── 選択完了ブロック ── */}
          {demoState === "selected" && selectedVendor && (
            <div>
              <div className="selected-banner">
                <div className="selected-banner-ic">
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M5 12.5l4.5 4.5L19 7" />
                  </svg>
                </div>
                <div className="selected-banner-text">
                  <strong>業者を選択しました！</strong>
                  <span>業者から連絡が届くまでしばらくお待ちください</span>
                </div>
              </div>

              {/* 決定済み業者カード */}
              <div className="decided-card">
                <div className="decided-label">
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M5 12.5l4.5 4.5L19 7" />
                  </svg>
                  決定済み
                </div>
                <div className="decided-biz-row">
                  <div className="decided-avatar" style={{ background: selectedVendor.color }}>
                    {selectedVendor.initial}
                  </div>
                  <div>
                    <div className="decided-biz-name">{selectedVendor.name}</div>
                    <div className="biz-rating">
                      <span className="biz-stars">★★★★★</span>
                      <span className="biz-rating-num">4.8</span>
                      <span>（口コミ156件）</span>
                    </div>
                  </div>
                </div>
                <div className="decided-amount">
                  <span className="decided-amount-yen">¥</span>
                  {selectedVendor.amount.toLocaleString("ja-JP")}
                </div>
                <div className="decided-sub">出品5点のまとめ買取金額（搬出費用込み）</div>
                <Link href="/chat/1" className="btn btn-primary btn-lg btn-block">
                  <Ic name="chat" />
                  チャットを開始する
                  <Ic name="arrow" className="arw" />
                </Link>
              </div>

              {/* 次のステップ */}
              <div className="next-steps-card">
                <p className="next-steps-heading">これからの流れ</p>
                <ul className="next-steps">
                  <li className="next-step">
                    <div className="ns-dot ns-dot-done">
                      <svg viewBox="0 0 24 24" aria-hidden="true">
                        <path d="M5 12.5l4.5 4.5L19 7" />
                      </svg>
                    </div>
                    <div className="ns-body">
                      <h4>業者を選択</h4>
                      <p>完了しました</p>
                    </div>
                  </li>
                  <li className="next-step">
                    <div className="ns-dot ns-dot-current">2</div>
                    <div className="ns-body">
                      <h4>業者から連絡が届く</h4>
                      <p>LINEまたはメールで日程の連絡が来ます（通常24時間以内）</p>
                    </div>
                  </li>
                  <li className="next-step">
                    <div className="ns-dot ns-dot-future">3</div>
                    <div className="ns-body">
                      <h4>自宅で回収・査定</h4>
                      <p>業者がご自宅へ訪問。品物を確認してその場で査定します</p>
                    </div>
                  </li>
                  <li className="next-step">
                    <div className="ns-dot ns-dot-future">4</div>
                    <div className="ns-body">
                      <h4>その場で現金受け取り</h4>
                      <p>査定額に合意したら、現金またはお好みの方法で即日お支払い</p>
                    </div>
                  </li>
                </ul>
              </div>
            </div>
          )}

          {/* 選択完了だがselectedVendorが未設定（デモバーで直接"選択完了"を選んだ場合） */}
          {demoState === "selected" && !selectedVendor && (
            <div>
              <div className="selected-banner">
                <div className="selected-banner-ic">
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M5 12.5l4.5 4.5L19 7" />
                  </svg>
                </div>
                <div className="selected-banner-text">
                  <strong>業者を選択しました！</strong>
                  <span>業者から連絡が届くまでしばらくお待ちください</span>
                </div>
              </div>
              <div className="decided-card">
                <div className="decided-label">
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M5 12.5l4.5 4.5L19 7" />
                  </svg>
                  決定済み
                </div>
                <div className="decided-biz-row">
                  <div className="decided-avatar" style={{ background: "#1f54de" }}>バ</div>
                  <div>
                    <div className="decided-biz-name">株式会社バリュー東京</div>
                    <div className="biz-rating">
                      <span className="biz-stars">★★★★★</span>
                      <span className="biz-rating-num">4.8</span>
                      <span>（口コミ156件）</span>
                    </div>
                  </div>
                </div>
                <div className="decided-amount">
                  <span className="decided-amount-yen">¥</span>54,000
                </div>
                <div className="decided-sub">出品5点のまとめ買取金額（搬出費用込み）</div>
                <Link href="/chat/1" className="btn btn-primary btn-lg btn-block">
                  <Ic name="chat" />
                  チャットを開始する
                  <Ic name="arrow" className="arw" />
                </Link>
              </div>
              <div className="next-steps-card">
                <p className="next-steps-heading">これからの流れ</p>
                <ul className="next-steps">
                  <li className="next-step">
                    <div className="ns-dot ns-dot-done">
                      <svg viewBox="0 0 24 24" aria-hidden="true">
                        <path d="M5 12.5l4.5 4.5L19 7" />
                      </svg>
                    </div>
                    <div className="ns-body">
                      <h4>業者を選択</h4>
                      <p>完了しました</p>
                    </div>
                  </li>
                  <li className="next-step">
                    <div className="ns-dot ns-dot-current">2</div>
                    <div className="ns-body">
                      <h4>業者から連絡が届く</h4>
                      <p>LINEまたはメールで日程の連絡が来ます（通常24時間以内）</p>
                    </div>
                  </li>
                  <li className="next-step">
                    <div className="ns-dot ns-dot-future">3</div>
                    <div className="ns-body">
                      <h4>自宅で回収・査定</h4>
                      <p>業者がご自宅へ訪問。品物を確認してその場で査定します</p>
                    </div>
                  </li>
                  <li className="next-step">
                    <div className="ns-dot ns-dot-future">4</div>
                    <div className="ns-body">
                      <h4>その場で現金受け取り</h4>
                      <p>査定額に合意したら、現金またはお好みの方法で即日お支払い</p>
                    </div>
                  </li>
                </ul>
              </div>
            </div>
          )}

        </div>
      </main>

      {/* ── 選択後フッターCTA ── */}
      {demoState === "selected" && (
        <div className="result-footer">
          <div className="result-footer-inner">
            <div className="result-footer-info">
              <strong>{selectedVendor?.name ?? "株式会社バリュー東京"}</strong>
              <span>チャットで日程調整を始めましょう</span>
            </div>
            <Link href="/chat/1" className="btn btn-primary">
              <Ic name="chat" />
              チャット開始
            </Link>
          </div>
        </div>
      )}

      {/* ── 確認モーダル ── */}
      {modalVendor && (
        <div className="kdz-overlay" role="dialog" aria-modal="true" aria-label="業者選択の確認" onClick={onOverlayClick}>
          <div className="kdz-modal">
            <h2>この業者に決めますか？</h2>
            <p className="modal-sub">
              一度決定すると変更できません。よろしければ確定ボタンを押してください。
            </p>
            <div className="modal-biz-box">
              <div
                className="modal-biz-avatar"
                style={{ background: modalVendor.color }}
                aria-hidden="true"
              >
                {modalVendor.initial}
              </div>
              <div>
                <div className="modal-biz-name">{modalVendor.name}</div>
                <div className="modal-biz-amount">
                  ¥{modalVendor.amount.toLocaleString("ja-JP")}
                </div>
              </div>
            </div>
            <div className="modal-actions">
              <button type="button" className="btn-modal-cancel" onClick={closeModal}>
                キャンセル
              </button>
              <button type="button" className="btn-modal-confirm" onClick={confirmSelect}>
                決定する
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── トースト（デモ用。実処理なし） ── */}
      {toast && (
        <div className="kdz-toast" role="status">
          {toast}
        </div>
      )}
    </div>
  );
}
