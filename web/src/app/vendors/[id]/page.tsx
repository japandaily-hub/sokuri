"use client";

import "./vendor.css";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Ic, type IcName } from "@/components/kdz/Icons";
import { AppHeader } from "@/components/kdz/AppHeader";

/* ============================================================
   業者詳細ページ（カタヅケ）
   動的ルート /vendors/[id]。表示内容はデモ用モックデータ。
   バックエンド未配線：「この業者に決める」「質問する」等は実処理せず
   UI 挙動（トースト表示／ページ内リンク遷移）のみ。
   ============================================================ */

/** 評価分布バー（5→1）。pct は track 幅、count は件数。 */
type RatingBar = { star: 5 | 4 | 3 | 2 | 1; pct: number; count: number };
const RATING_BARS: RatingBar[] = [
  { star: 5, pct: 78, count: 121 },
  { star: 4, pct: 15, count: 23 },
  { star: 3, pct: 5, count: 8 },
  { star: 2, pct: 2, count: 3 },
  { star: 1, pct: 1, count: 1 },
];

/** 統計グリッド（登録年数・成約実績・リピート率）。 */
const STATS: { val: string; unit: string; label: string }[] = [
  { val: "3.2", unit: "年", label: "登録年数" },
  { val: "482", unit: "件", label: "成約実績" },
  { val: "98", unit: "%", label: "リピート率" },
];

/** 専門カテゴリ（emoji は使わず文字ラベルのみ）。 */
const CATEGORIES = ["家電", "ブランド品", "時計・ジュエリー", "カメラ", "ゲーム機"];

/** サービスの特徴（業者の約束）。 */
const PROMISES: { icon: IcName; title: string; body: string }[] = [
  {
    icon: "truck",
    title: "搬出費用完全無料",
    body: "大型家電や家具も追加費用なしで搬出します。エレベーターなしの建物も対応可。",
  },
  {
    icon: "clock",
    title: "最短即日訪問",
    body: "午前中のご連絡で、当日午後の訪問が可能です。急ぎの引越し・遺品整理にも対応。",
  },
  {
    icon: "check-circle",
    title: "査定後キャンセル無料",
    body: "訪問後に査定額に納得できなければ、キャンセルは無料です。プレッシャーなしで査定を受けられます。",
  },
];

/** 口コミ（デモ）。avatar はイニシャル円＋背景色。stars は塗り星数。 */
type Review = { initial: string; color: string; name: string; stars: number; date: string; text: string; tags: string[] };
const REVIEWS: Review[] = [
  {
    initial: "田",
    color: "#4a90d9",
    name: "田中 美香",
    stars: 5,
    date: "2026年6月",
    text: "引越し前日にお願いしたのに、当日午後に来てくれて本当に助かりました。家電5点と服をまとめて買い取っていただき、¥62,000になりました。スタッフの方もとても丁寧で、また利用したいと思います。",
    tags: ["即日対応", "スタッフ丁寧", "高額査定"],
  },
  {
    initial: "山",
    color: "#e06b6b",
    name: "山本 健太",
    stars: 5,
    date: "2026年5月",
    text: "遺品整理でお世話になりました。デリケートな状況を理解していただき、丁寧な対応でした。値段の説明も明確で納得感があり、安心してお任せできました。",
    tags: ["遺品整理", "説明明確"],
  },
  {
    initial: "佐",
    color: "#5cb85c",
    name: "佐藤 由美",
    stars: 4,
    date: "2026年4月",
    text: "思っていたより査定額が高くて驚きました。テレビ・冷蔵庫・洗濯機の3点で¥28,000。搬出も丁寧にやっていただきました。",
    tags: ["家電", "搬出丁寧"],
  },
];

/** 対応エリア（デモ）。 */
const AREAS = ["東京都", "神奈川県", "埼玉県", "千葉県（一部）"];

/** 星文字列（塗り★ + 空☆）を生成。 */
function starString(filled: number): string {
  return "★".repeat(filled) + "☆".repeat(Math.max(0, 5 - filled));
}

export default function VendorDetailPage() {
  /* 動的ルート [id]：チャット導線（/chat/[id]）に使用。client component なので useParams で取得。 */
  const params = useParams<{ id: string }>();
  const vendorId = params?.id ?? "1";

  /* ---- トースト（デモ用。実処理なし） ---- */
  const [toast, setToast] = useState<string | null>(null);
  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), 2400);
    return () => window.clearTimeout(id);
  }, [toast]);

  return (
    <div className="vendor-page">
      <AppHeader unread />

      <main>
        <div className="vendor-wrap">
          {/* 査定結果に戻る */}
          <Link href="/result" className="vendor-back">
            <svg viewBox="0 0 24 24">
              <path d="M19 12H5M11 6l-6 6 6 6" />
            </svg>
            査定結果に戻る
          </Link>

          {/* ヒーロー */}
          <div className="biz-hero">
            <div className="biz-hero-head">
              <div className="biz-big-avatar" style={{ background: "#1f54de" }}>
                バ
              </div>
              <div className="biz-hero-info">
                <div className="biz-hero-name">株式会社バリュー東京</div>
                <div className="biz-hero-area">
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" />
                    <circle cx="12" cy="10" r="3" />
                  </svg>
                  東京都・神奈川県・埼玉県
                </div>
                <div className="biz-hero-badges">
                  <span className="biz-tag biz-tag-green">古物商許可済</span>
                  <span className="biz-tag biz-tag-green">個人情報保護</span>
                  <span className="biz-tag biz-tag-blue">即日対応可</span>
                  <span className="biz-tag biz-tag-blue">家電特化</span>
                </div>
              </div>
            </div>

            {/* 評価 */}
            <div className="biz-rating-row">
              <div className="stars-big">{starString(5)}</div>
              <div className="rating-num">4.8</div>
              <div className="rating-count">（口コミ156件）</div>
            </div>

            {/* 評価バー */}
            <div className="rating-bars">
              {RATING_BARS.map((r) => (
                <div className="rating-bar-row" key={r.star}>
                  <span className="rating-bar-lbl">{r.star}</span>
                  <div className="rating-bar-track">
                    <div className="rating-bar-fill" style={{ width: `${r.pct}%` }} />
                  </div>
                  <span className="rating-bar-num">{r.count}</span>
                </div>
              ))}
            </div>

            {/* 統計グリッド */}
            <div className="biz-stats">
              {STATS.map((s) => (
                <div className="biz-stat" key={s.label}>
                  <div className="biz-stat-val">
                    {s.val}
                    <small>{s.unit}</small>
                  </div>
                  <div className="biz-stat-lbl">{s.label}</div>
                </div>
              ))}
            </div>

            {/* 専門カテゴリ */}
            <div className="cat-heading">専門カテゴリ</div>
            <div className="cat-grid">
              {CATEGORIES.map((c) => (
                <div className="cat-chip" key={c}>
                  {c}
                </div>
              ))}
            </div>
          </div>

          {/* 入札ハイライト */}
          <div className="bid-highlight">
            <div className="bid-highlight-top">
              <span className="bid-label-badge">
                <Ic name="crown" style={{ width: 13, height: 13 }} />
                あなたへの最高額入札
              </span>
            </div>
            <div className="bid-amount-big">
              <small>¥</small>54,000
            </div>
            <div className="bid-amount-note">5点まとめ買取・搬出費用込み</div>
            <div className="bid-message">
              「家電・ブランド品を専門スタッフが丁寧に査定します。まとめてお持ちの方が有利です。即日訪問も対応可能ですのでお気軽にご相談ください。お見積もり後のキャンセルも無料です。」
            </div>
            <div className="bid-cta-row">
              <button
                type="button"
                className="btn btn-primary btn-lg"
                style={{ flex: 1.5 }}
                onClick={() => setToast("この業者を選択しました（デモ）")}
              >
                <svg viewBox="0 0 24 24" width={17} height={17} style={{ stroke: "#fff" }}>
                  <path d="M5 12.5l4.5 4.5L19 7" />
                </svg>
                この業者に決める
              </button>
              <Link href={`/chat/${vendorId}`} className="btn btn-ghost btn-lg" style={{ flex: 1 }}>
                <svg viewBox="0 0 24 24" width={16} height={16} style={{ stroke: "currentColor" }}>
                  <path d="M5 5h14a2 2 0 012 2v8a2 2 0 01-2 2H9l-4 4V7a2 2 0 012-2z" />
                </svg>
                質問する
              </Link>
            </div>
          </div>

          {/* サービスの特徴 */}
          <div className="detail-card">
            <div className="detail-card-title">
              <svg viewBox="0 0 24 24">
                <path d="M12 3l7 3v6c0 4.7-3 7.9-7 9-4-1.1-7-4.3-7-9V6z" />
                <path d="M9 12l2 2 4-4" />
              </svg>
              サービスの特徴
            </div>
            <div className="promise-list">
              {PROMISES.map((p) => (
                <div className="promise-item" key={p.title}>
                  <div className="promise-ic">
                    <PromiseIcon icon={p.icon} />
                  </div>
                  <div className="promise-body">
                    <strong>{p.title}</strong>
                    <span>{p.body}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* 口コミ */}
          <div className="detail-card">
            <div className="detail-card-title">
              <svg viewBox="0 0 24 24">
                <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
              </svg>
              口コミ（156件）
            </div>

            {REVIEWS.map((rv) => (
              <div className="review-item" key={rv.name}>
                <div className="review-head">
                  <div className="reviewer-avatar" style={{ background: rv.color }}>
                    {rv.initial}
                  </div>
                  <div className="reviewer-info">
                    <div className="reviewer-name">{rv.name}</div>
                    <div className="review-meta">
                      <span className="review-stars">{starString(rv.stars)}</span>
                      {"　"}
                      {rv.date}
                    </div>
                  </div>
                </div>
                <div className="review-text">{rv.text}</div>
                <div className="review-tags">
                  {rv.tags.map((t) => (
                    <span className="review-tag" key={t}>
                      {t}
                    </span>
                  ))}
                </div>
              </div>
            ))}

            <div className="review-more">
              <button
                type="button"
                className="review-more-btn"
                onClick={() => setToast("口コミ一覧は準備中です（デモ）")}
              >
                すべての口コミを見る（156件）
              </button>
            </div>
          </div>

          {/* 対応エリア */}
          <div className="detail-card">
            <div className="detail-card-title">
              <svg viewBox="0 0 24 24">
                <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" />
                <circle cx="12" cy="10" r="3" />
              </svg>
              対応エリア
            </div>
            <div className="area-tags">
              {AREAS.map((a) => (
                <div className="area-tag" key={a}>
                  {a}
                </div>
              ))}
            </div>
          </div>
        </div>
      </main>

      {/* 固定フッターCTA */}
      <div className="biz-footer-cta">
        <div className="biz-footer-inner">
          <div className="biz-footer-info">
            <strong>¥54,000 で入札中</strong>
            <span>株式会社バリュー東京 · 最高額</span>
          </div>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setToast("この業者を選択しました（デモ）")}
          >
            <svg viewBox="0 0 24 24" width={16} height={16} style={{ stroke: "#fff" }}>
              <path d="M5 12.5l4.5 4.5L19 7" />
            </svg>
            決める
          </button>
          <Link href={`/chat/${vendorId}`} className="btn btn-ghost">
            質問
          </Link>
        </div>
      </div>

      {/* トースト（デモ通知。実処理なし） */}
      {toast ? (
        <div className="kdz-toast" role="status">
          {toast}
        </div>
      ) : null}
    </div>
  );
}

/** サービスの特徴アイコン（emoji 不使用。Icons スプライト or inline SVG）。 */
function PromiseIcon({ icon }: { icon: IcName }) {
  if (icon === "truck") {
    return (
      <svg viewBox="0 0 24 24">
        <rect x="1" y="3" width="15" height="13" rx="1" />
        <path d="M16 8h4l3 4v4h-7V8z" />
        <circle cx="5.5" cy="18.5" r="2.5" />
        <circle cx="18.5" cy="18.5" r="2.5" />
      </svg>
    );
  }
  if (icon === "clock") {
    return (
      <svg viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 3" />
      </svg>
    );
  }
  // check-circle → デザインの「査定後キャンセル無料」はチェックマーク
  return (
    <svg viewBox="0 0 24 24">
      <path d="M5 12.5l4.5 4.5L19 7" />
    </svg>
  );
}
