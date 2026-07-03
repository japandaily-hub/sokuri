"use client";

import "./vendor.css";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { AppHeader } from "@/components/kdz/AppHeader";
import { Spinner } from "@/components/Icon";
import { Notice } from "@/components/kdz/Ui";
import {
  getVendorPublicProfile,
  toDisplayMessage,
  type OperatorPublicProfile,
} from "@/lib/katadzuke-api";

/* ============================================================
   業者詳細ページ（カタヅケ）
   動的ルート /vendors/[id]。getVendorPublicProfile で実データ配線（2026-07-03）。
   APIに無い項目（成約実績・リピート率・登録年数・評価分布バー・
   「あなたへの最高額入札」ブロック・PROMISES・決定/質問CTA）は削除し、
   案件文脈が無いページのため「入札の選択は案件詳細から行えます」の案内に置換した。
   ============================================================ */

/** 星文字列（塗り★ + 空☆）を生成。rating が小数の場合は四捨五入して塗る。 */
function starString(rating: number): string {
  const filled = Math.round(rating);
  return "★".repeat(filled) + "☆".repeat(Math.max(0, 5 - filled));
}

export default function VendorDetailPage() {
  const params = useParams<{ id: string }>();
  const vendorId = params?.id ?? "";

  const [profile, setProfile] = useState<OperatorPublicProfile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!vendorId) return;
    setLoading(true);
    getVendorPublicProfile(vendorId)
      .then(setProfile)
      .catch((e) => setError(toDisplayMessage(e, "業者情報の取得に失敗しました")))
      .finally(() => setLoading(false));
  }, [vendorId]);

  if (loading) {
    return (
      <div className="vendor-page">
        <AppHeader unread />
        <div className="flex min-h-[50vh] items-center justify-center">
          <Spinner className="h-6 w-6 text-brand-600" />
        </div>
      </div>
    );
  }

  if (!profile) {
    return (
      <div className="vendor-page">
        <AppHeader unread />
        <main>
          <div className="vendor-wrap">
            <Notice tone="error">{error ?? "業者情報が見つかりません。"}</Notice>
            <Link href="/cases" className="vendor-back" style={{ marginTop: 16 }}>
              <svg viewBox="0 0 24 24">
                <path d="M19 12H5M11 6l-6 6 6 6" />
              </svg>
              マイ案件一覧に戻る
            </Link>
          </div>
        </main>
      </div>
    );
  }

  const initial = profile.company_name.slice(0, 1);
  const reviews = profile.reviews ?? [];

  return (
    <div className="vendor-page">
      <AppHeader unread />

      <main>
        <div className="vendor-wrap">
          {/* 案件一覧に戻る */}
          <Link href="/cases" className="vendor-back">
            <svg viewBox="0 0 24 24">
              <path d="M19 12H5M11 6l-6 6 6 6" />
            </svg>
            マイ案件一覧に戻る
          </Link>

          {/* ヒーロー */}
          <div className="biz-hero">
            <div className="biz-hero-head">
              <div className="biz-big-avatar" style={{ background: "#1f54de" }}>
                {initial}
              </div>
              <div className="biz-hero-info">
                <div className="biz-hero-name">{profile.company_name}</div>
                {profile.areas.length > 0 ? (
                  <div className="biz-hero-area">
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" />
                      <circle cx="12" cy="10" r="3" />
                    </svg>
                    {profile.areas.join("・")}
                  </div>
                ) : null}
                <div className="biz-hero-badges">
                  {profile.verified_at ? (
                    <span className="biz-tag biz-tag-green">古物商許可済</span>
                  ) : null}
                  {profile.accept_unsellable ? (
                    <span className="biz-tag biz-tag-blue">値がつかない物もOK</span>
                  ) : null}
                </div>
              </div>
            </div>

            {/* 評価（無い場合は非表示） */}
            {profile.rating != null ? (
              <div className="biz-rating-row">
                <div className="stars-big">{starString(profile.rating)}</div>
                <div className="rating-num">{profile.rating.toFixed(1)}</div>
                <div className="rating-count">（口コミ{reviews.length}件）</div>
              </div>
            ) : null}

            {/* 専門カテゴリ */}
            {profile.categories.length > 0 ? (
              <>
                <div className="cat-heading">専門カテゴリ</div>
                <div className="cat-grid">
                  {profile.categories.map((c) => (
                    <div
                      className="cat-chip"
                      key={c}
                      style={
                        profile.strong_categories.includes(c)
                          ? { fontWeight: 700 }
                          : undefined
                      }
                    >
                      {c}
                      {profile.strong_categories.includes(c) ? " ★" : ""}
                    </div>
                  ))}
                </div>
              </>
            ) : null}
          </div>

          {/* 案内文（案件文脈が無いため決定/質問CTAの代替） */}
          <div className="bid-highlight">
            <div className="bid-message">
              {profile.intro_message ?? "この業者からの紹介文はまだ登録されていません。"}
            </div>
            <p style={{ marginTop: 12, fontSize: 13, color: "var(--body-soft)" }}>
              入札の選択は案件詳細から行えます。
            </p>
          </div>

          {/* 口コミ */}
          <div className="detail-card">
            <div className="detail-card-title">
              <svg viewBox="0 0 24 24">
                <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
              </svg>
              口コミ（{reviews.length}件）
            </div>

            {reviews.length > 0 ? (
              reviews.map((rv) => (
                <div className="review-item" key={rv.id}>
                  <div className="review-head">
                    <div className="reviewer-avatar" style={{ background: "#4a90d9" }}>
                      口
                    </div>
                    <div className="reviewer-info">
                      <div className="review-meta">
                        <span className="review-stars">{starString(rv.rating)}</span>
                        {"　"}
                        {new Date(rv.created_at).toLocaleDateString("ja-JP")}
                      </div>
                    </div>
                  </div>
                  {rv.comment ? <div className="review-text">{rv.comment}</div> : null}
                </div>
              ))
            ) : (
              <p style={{ fontSize: 13, color: "var(--body-soft)", padding: "8px 0" }}>
                口コミはまだありません。
              </p>
            )}
          </div>

          {/* 対応エリア */}
          {profile.areas.length > 0 ? (
            <div className="detail-card">
              <div className="detail-card-title">
                <svg viewBox="0 0 24 24">
                  <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z" />
                  <circle cx="12" cy="10" r="3" />
                </svg>
                対応エリア
              </div>
              <div className="area-tags">
                {profile.areas.map((a) => (
                  <div className="area-tag" key={a}>
                    {a}
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </main>
    </div>
  );
}
