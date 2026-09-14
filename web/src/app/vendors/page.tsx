"use client";

import "./vendors.css";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { AppHeader } from "@/components/kdz/AppHeader";
import { Spinner } from "@/components/Icon";
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

/** 取得状態に依存しない静的ブロック（R4 r4 #1/#9/#16）。
 *  取得失敗時と「取得成功で0件」の両方で描く。ここに書く3点は /business の登録要件・
 *  /faq・/terms の既存記載の範囲内に限り、実在業者の件数・社名・評価・写真は一切出さない。 */
function VendorStaticInfo() {
  return (
    <section className="vd-sample" aria-labelledby="vd-static-h">
      <h2 id="vd-static-h">掲載している業者の審査</h2>
      <ul className="vd-criteria">
        <li>
          <b>古物商許可の確認</b>
          古物営業法に基づく古物商許可証を、運営が確認した事業者のみを掲載します。
        </li>
        <li>
          <b>一斉架電なし</b>
          連絡できるのは、ユーザーが選んだ1社だけです。選ばれなかった業者に連絡先は渡りません。
        </li>
        <li>
          <b>特定商取引法の遵守</b>
          訪問買取における法定書面の交付など、特定商取引法の遵守を審査時に確認します。
        </li>
      </ul>
      <h3>掲載時に表示する項目</h3>
      <p className="model-note">審査を通過した業者は、次の項目とともにこの一覧に掲載されます。</p>
      <ul className="vd-sample-list">
        <li>店舗名</li>
        <li>エリア</li>
        <li>取扱カテゴリ</li>
        <li>評価</li>
      </ul>
    </section>
  );
}

export default function VendorListPage() {
  const [vendors, setVendors] = useState<VendorListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { status: sessionStatus } = useSession();
  const signedIn = sessionStatus === "authenticated";
  /* 取得が成功して 0 件だった状態（＝意図された空）。読込中（vendors === null）とエラーは含まない。
     「現在、掲載中の業者はありません」の断定はこの状態のときだけ書く（R4 r4 #1）。 */
  const isEmpty = vendors !== null && vendors.length === 0;

  useEffect(() => {
    getVendors()
      .then(setVendors)
      .catch((e) =>
        setError(
          /* R4 r4 #24: 共通の通信エラー文（lib/katadzuke-api.ts）が「電波状況を確認し」で、
             PC で見ている人には的外れ。共通文言はコア管理のため、ページ側で表記だけ正規化する
             （共通側が直れば置換が不発になるだけで害はない）。 */
          toDisplayMessage(e, "業者一覧の取得に失敗しました").replace(
            "電波状況を確認し、",
            "通信環境を確認のうえ、",
          ),
        ),
      );
  }, []);

  return (
    <div className="vendors-page bare-scope">
      <AppHeader />
      <main id="main">
        {/* ============ 写真帯（静的。取得状態に依存しない） ============ */}
        {/* r2 M5 是正: 見出し1語だけでは帯の濃紺面が空に見えたため、/photo-guide の帯と同じ
            eyebrow ＋ h1 ＋ 1行リードの構成に揃える。小さい文字を載せるので veil は
            --headline（.55）をやめ既定の .65 に戻す（白 13〜16px で AA を確保するため）。
            R4 D.2 #7: 素材に遠景の作業者が入るため縦位置修飾子 .hero-band--face を足す。
            --headline は付けない（3要素が載る帯なので veil を .65 のまま維持する）。
            R4 C.3-4 / R4 r4 #1: 承認済みの実在業者がいる断定文（「〜業者です」）は、掲載0件でも
            取得失敗中でも優良誤認になるため出さない。0件では「…のみを掲載します／現在、掲載中の
            業者はありません。」、取得失敗では「…のみを掲載します。」（0件の断定は足さない）。
            1社以上あるときだけ現行文のまま。 */}
        <section className="hero-band hero-band--slim hero-band--face vd-band">
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
          <div className="container hero-band__copy">
            <span className="eyebrow">審査制</span>
            <h1>登録業者一覧</h1>
            <p>
              {isEmpty
                ? "古物商許可番号を確認し、運営が承認した業者のみを掲載します。現在、掲載中の業者はありません。"
                : error
                  ? /* R4 r4 #1: 取得できていない状態で「承認した業者です」と断定すると、
                       掲載0件でも「承認済みの業者が並んでいる」と読める。ただし取得失敗時は
                       0件かどうかも不明なので、0件の断定（空状態の文）は足さない。 */
                    "古物商許可番号を確認し、運営が承認した業者のみを掲載します。"
                  : "古物商許可番号を確認し、運営が承認した業者です。"}
            </p>
          </div>
        </section>

        <div className="vendors-wrap">
          {/* R4 r4 #14: 帯の人物は生成画像。直下に「古物商許可番号を確認し…」が並ぶため、
              実在の登録業者の写真と誤読されないよう可視の打消しを置く（alt="" は a11y 上の
              措置で、可視の否認にはならない）。書式は共有部品 .model-note に合わせる。 */}
          <p className="model-note vd-photo-note">※ 写真はイメージです。</p>
          {/* r3 是正: 戻るリンクは末尾（.vd-join の下）へ移した。ページ先頭の最初の導線が
              「戻る」になっていたため、本文はリード文から始める。 */}
          <p className="vendors-lead">
            {/* r2 M3 是正: 稼働直前で実投稿が0件のため、現在形の断定（そのまま公開します）は
                既に投稿が集まっているかのような誤認を招く。/company VALUES と同じ「〜します／
                〜にします」の方針表明に直す（CONSTRAINTS §3）。
                1文目「古物商許可番号を確認し…」は r2 M5 で帯のリードへ移した。 */}
            評価と口コミは、成約したユーザーの投稿をそのまま掲載する方針です。
            入札の選択は案件詳細から行えます。
          </p>

          {/* エラー: 1行の控えめな注記 ＋ 再読み込み/FAQ（R4 r4 #1/#9/#16）
              赤枠の Notice だけが面に浮き「壊れている」と読まれていたため、注意の表示は
              1行（--danger のヘアライン）に落とし、直後に取得状態に依存しない静的ブロック
              <VendorStaticInfo /> を必ず描く。
              r2 M10（行き止まりを作らない）は維持するが、「出品する」は主導線の .btn から
              テキストリンクに降格する（一覧を確かめに来た人の次の一手は再読み込みと FAQ）。 */}
          {error ? (
            <div className="vd-state vd-state--error">
              <p className="vd-state-err" role="alert">
                {error}
              </p>
              <div className="vd-state-actions">
                <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>
                  再読み込み
                </button>
                <Link href="/faq" className="btn btn-ghost">
                  よくある質問（業者について）
                </Link>
              </div>
              <p className="vd-state-sub">
                <Link href="/create" className="vd-state-link">
                  出品する
                </Link>
                <Link href="/business" className="vd-state-link">
                  業者の方はこちら
                </Link>
                <Link href="/mypage" className="vd-state-link">
                  マイ案件一覧へ
                </Link>
              </p>
            </div>
          ) : null}

          {/* 読込中: 罫線なしの静かな面 + 状態テキスト */}
          {vendors === null && !error ? (
            <div className="vd-state vd-state--loading" role="status" aria-live="polite">
              <Spinner className="h-6 w-6 text-brand-600" />
              <p className="vd-state-text">業者一覧を読み込んでいます…</p>
            </div>
          ) : null}

          {/* 空: 画像付きの独立ブロック（上下 1px 罫線・白面）
              R4 C.3: 架空の業者カードは作らない。.vendor-row の骨格を流用した架空店は、
              チップや注記を付けても見た目が実在の掲載と同じで「登録業者がいるかのような表示」に
              なり得るため。代わりに、正直な空状態メッセージを先に読ませたうえで、
              カードの形をとらない説明ブロック（掲載時に表示する項目）を直後に置く。
              社名・エリア・星・許可タグ・画像は一切出さない。 */}
          {isEmpty ? (
            <>
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
            </>
          ) : null}

          {/* 審査の基準と「掲載時に表示する項目」は、エラー時・空のときの両方で描く（R4 r4 #1）。
              架空の店舗名・エリア・数値・星・許可タグ・画像は出さない。VENDOR_CASES の店名も
              このページでは使わない（ページをまたいで実在の登録業者と読まれるため）。 */}
          {error || isEmpty ? <VendorStaticInfo /> : null}

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

          {/* 戻る導線はページ末尾（r3 是正） */}
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
        </div>
      </main>

      {/* ============ 最小フッター ============
          r2 M6 是正: BARE ページで共通 .footer を持たず、取得エラー・空のときに
          ページが途中で切れて見えた。規約・法務3本と運営者表記だけで底を作る。 */}
      <footer className="vd-foot">
        <div className="vd-foot-inner">
          <nav className="vd-foot-links" aria-label="規約・法務">
            <Link href="/terms">利用規約</Link>
            <Link href="/privacy">プライバシーポリシー</Link>
            <Link href="/legal">特定商取引法に基づく表記</Link>
          </nav>
          <span>© 2026 カタヅケ</span>
        </div>
      </footer>
    </div>
  );
}
