"use client";

import "./vendors.css";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { AppHeader } from "@/components/kdz/AppHeader";
import { Spinner } from "@/components/Icon";
import { Notice } from "@/components/kdz/Ui";
import { vendorCategoryName } from "@/lib/categories";
import { getVendors, toDisplayMessage, type VendorListItem } from "@/lib/katadzuke-api";

/* ============================================================
   登録業者一覧（/vendors）
   評価・口コミは常時公開（2026-09-04 決定）。GET /vendors は承認済み・停止中でない
   業者のみを「評価あり→評価の高い順→口コミ件数順」で返す。個人情報は含まない。
   ビジュアル再構築（BRIEF §2.7）: 最上部の写真帯は一覧の取得状態に依存しない静的要素
   として useEffect の外に置き、読込中・エラー・空を視覚的に区別する。業者行には画像を
   付けない（実在業者に生成画像を添えないため）。
   ============================================================ */

/** 星文字列（塗り★ + 空☆）。rating が小数の場合は四捨五入して塗る。 */
function starString(rating: number): string {
  const filled = Math.round(rating);
  return "★".repeat(filled) + "☆".repeat(Math.max(0, 5 - filled));
}

export default function VendorListPage() {
  const [vendors, setVendors] = useState<VendorListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { status: sessionStatus } = useSession();
  const signedIn = sessionStatus === "authenticated";

  useEffect(() => {
    getVendors()
      .then(setVendors)
      .catch((e) => setError(toDisplayMessage(e, "業者一覧の取得に失敗しました")));
  }, []);

  return (
    <div className="vendors-page bare-scope">
      <AppHeader />
      <main id="main">
        {/* ============ 写真帯（静的。取得状態に依存しない） ============ */}
        <section className="hero-band hero-band--slim hero-band--headline vd-band">
          {/* eslint-disable @next/next/no-img-element */}
          <img
            src="/img/v2/vd-band.webp"
            width={1920}
            height={1080}
            alt=""
            loading="eager"
            fetchPriority="high"
            decoding="async"
          />
          {/* eslint-enable @next/next/no-img-element */}
          <div className="hero-band__veil" aria-hidden="true" />
          {/* veil .55 は見出し（24px 以上・600）のみ。注記・本文は帯の下の白面に置く */}
          <div className="container hero-band__copy">
            <h1>登録業者一覧</h1>
          </div>
        </section>

        <div className="vendors-wrap">
          {signedIn ? (
            <Link href="/mypage" className="vendors-back">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M19 12H5M11 6l-6 6 6 6" />
              </svg>
              マイ案件一覧に戻る
            </Link>
          ) : (
            <Link href="/" className="vendors-back">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M19 12H5M11 6l-6 6 6 6" />
              </svg>
              トップページに戻る
            </Link>
          )}

          <p className="vendors-lead">
            古物商許可番号を確認し、運営が承認した業者です。
            評価と口コミは、成約したユーザーの投稿をそのまま公開しています。
            入札の選択は案件詳細から行えます。
          </p>

          {/* エラー: 注意色の枠 + 再読み込み導線 */}
          {error ? (
            <div className="vd-state vd-state--error">
              <Notice tone="error">{error}</Notice>
              <div className="vd-state-actions">
                <button type="button" className="btn btn-ghost" onClick={() => window.location.reload()}>
                  再読み込み
                </button>
                <Link href="/mypage" className="vd-state-link">
                  マイ案件一覧へ
                </Link>
              </div>
            </div>
          ) : null}

          {/* 読込中: 罫線なしの静かな面 + 状態テキスト */}
          {vendors === null && !error ? (
            <div className="vd-state vd-state--loading" role="status" aria-live="polite">
              <Spinner className="h-6 w-6 text-brand-600" />
              <p className="vd-state-text">業者一覧を読み込んでいます…</p>
            </div>
          ) : null}

          {/* 空: 画像付きの独立ブロック（上下 1px 罫線・白面） */}
          {vendors !== null && vendors.length === 0 ? (
            <section className="vd-empty" aria-label="掲載中の業者">
              <div className="img-frame img-frame--1x1 img-frame--pale vd-empty-fig">
                {/* eslint-disable @next/next/no-img-element */}
                <img
                  src="/img/v2/vd-empty.webp"
                  width={800}
                  height={800}
                  alt=""
                  loading="lazy"
                  decoding="async"
                />
                {/* eslint-enable @next/next/no-img-element */}
              </div>
              <h2 className="vd-empty-title">審査を通過した業者から順に掲載します</h2>
              <p className="vd-empty-note">
                掲載前でも出品はできます。審査を通過した業者から順にここへ掲載します。
              </p>
              <div className="vd-empty-cta">
                <Link href="/create" className="btn btn-primary btn-lg">
                  出品する
                </Link>
                <Link href="/business" className="btn btn-ghost btn-lg">
                  業者の方はこちら
                </Link>
              </div>
            </section>
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
                          <span className="vendor-stars" aria-hidden="true">{starString(v.rating)}</span>
                          <span className="vd-sr">5段階中 {v.rating.toFixed(1)}</span>
                          <span className="vendor-rating-num" aria-hidden="true">{v.rating.toFixed(1)}</span>
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

          {/* ============ 末尾: 業者登録導線 ============ */}
          <aside className="vd-join" aria-label="業者登録のご案内">
            <p className="vd-join-text">
              業者として掲載を希望される方は、業者登録（審査制）からお申し込みください。
            </p>
            <Link href="/business" className="vd-join-link">
              業者登録（審査制）について
            </Link>
          </aside>
        </div>
      </main>
    </div>
  );
}
