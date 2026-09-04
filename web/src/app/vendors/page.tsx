"use client";

import "./vendors.css";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AppHeader } from "@/components/kdz/AppHeader";
import { Spinner } from "@/components/Icon";
import { Notice } from "@/components/kdz/Ui";
import { vendorCategoryName } from "@/lib/categories";
import { getVendors, toDisplayMessage, type VendorListItem } from "@/lib/katadzuke-api";

/* ============================================================
   登録業者一覧（/vendors）
   評価・口コミは常時公開（2026-09-04 決定）。GET /vendors は承認済み・停止中でない
   業者のみを「評価あり→評価の高い順→口コミ件数順」で返す。個人情報は含まない。
   ============================================================ */

/** 星文字列（塗り★ + 空☆）。rating が小数の場合は四捨五入して塗る。 */
function starString(rating: number): string {
  const filled = Math.round(rating);
  return "★".repeat(filled) + "☆".repeat(Math.max(0, 5 - filled));
}

export default function VendorListPage() {
  const [vendors, setVendors] = useState<VendorListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getVendors()
      .then(setVendors)
      .catch((e) => setError(toDisplayMessage(e, "業者一覧の取得に失敗しました")));
  }, []);

  return (
    <div className="vendors-page">
      <AppHeader />
      <main id="main">
        <div className="vendors-wrap">
          <Link href="/mypage" className="vendors-back">
            <svg viewBox="0 0 24 24">
              <path d="M19 12H5M11 6l-6 6 6 6" />
            </svg>
            マイ案件一覧に戻る
          </Link>

          <h1 className="vendors-title">登録業者一覧</h1>
          <p className="vendors-lead">
            運営審査を通過した業者です。評価と口コミは、成約したユーザーの投稿をそのまま公開しています。
            入札の選択は案件詳細から行えます。
          </p>

          {error ? <Notice tone="error">{error}</Notice> : null}

          {vendors === null && !error ? (
            <div className="vendors-loading">
              <Spinner className="h-6 w-6 text-brand-600" />
            </div>
          ) : null}

          {vendors !== null && vendors.length === 0 ? (
            <p className="vendors-empty">掲載中の業者はまだありません。</p>
          ) : null}

          {vendors !== null && vendors.length > 0 ? (
            <ul className="vendors-list">
              {vendors.map((v) => (
                <li key={v.operator_id} className="vendor-row">
                  <div className="vendor-row-main">
                    <div className="vendor-row-head">
                      <Link href={`/vendors/${v.operator_id}`} className="vendor-row-name">
                        {v.company_name}
                      </Link>
                      <span className="vendor-tag">運営審査済み</span>
                      {v.accept_unsellable ? (
                        <span className="vendor-tag vendor-tag-blue">値がつかない物もOK</span>
                      ) : null}
                    </div>
                    <div className="vendor-row-rating">
                      {v.rating != null ? (
                        <>
                          <span className="vendor-stars">{starString(v.rating)}</span>
                          <span className="vendor-rating-num">{v.rating.toFixed(1)}</span>
                          <span className="vendor-rating-count">（口コミ{v.review_count}件）</span>
                        </>
                      ) : (
                        <span className="vendor-rating-count">口コミはまだありません</span>
                      )}
                    </div>
                    {v.latest_review_comment ? (
                      <p className="vendor-row-quote">「{v.latest_review_comment}」</p>
                    ) : null}
                    {v.areas.length > 0 || v.strong_categories.length > 0 ? (
                      <p className="vendor-row-meta">
                        {v.areas.length > 0 ? <span>対応エリア: {v.areas.join("・")}</span> : null}
                        {v.strong_categories.length > 0 ? (
                          <span>得意: {v.strong_categories.map(vendorCategoryName).join("・")}</span>
                        ) : null}
                      </p>
                    ) : null}
                  </div>
                  <Link href={`/vendors/${v.operator_id}`} className="vendor-row-link">
                    口コミを見る
                  </Link>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      </main>
    </div>
  );
}
