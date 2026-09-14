"use client";

import "./vendors.css";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useSession } from "next-auth/react";
import { AppHeader } from "@/components/kdz/AppHeader";
import { SiteHeader } from "@/components/kdz/SiteHeader";
import { SiteFooter } from "@/components/kdz/chrome";
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
 *  /faq・/terms の既存記載の範囲内に限り、実在業者の件数・社名・評価・写真は一切出さない。
 *  r5 #1/#19: 「掲載時に表示する項目」は取得成功で0件のときだけ描く（showSample）。
 *  取得失敗中は一覧に何が並ぶかを説明しても「読み込めなかった表」に見えるため、
 *  審査の3点だけを残し、次の一手はエラーカードのボタンに集約する。 */
function VendorStaticInfo({ showSample }: { showSample: boolean }) {
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
      {showSample ? (
        <>
          <h3>掲載時に表示する項目</h3>
          <p className="model-note">審査を通過した業者は、次の項目とともにこの一覧に掲載されます。</p>
          {/* r5 #1/#5/#11/#17/#23/#28: 3列グリッド＋各行のヘアラインが「データの抜けた表」に
              見えていた（4項目のため PC で「評価」が孤立し、最終行に中身のない罫線が残った）。
              R4 C.3 の指定どおり素の箇条書き（中黒・1行1項目）に戻し、罫線は一切持たせない。 */}
          <ul className="vd-sample-list">
            <li>
              <b>店舗名</b>（屋号）
            </li>
            <li>
              <b>エリア</b>（訪問できる都県）
            </li>
            <li>
              <b>取扱カテゴリ</b>（得意な品目）
            </li>
            <li>
              <b>評価</b>（成約したユーザーの5段階評価と口コミ件数）
            </li>
          </ul>
          {/* r5 #33: 掲載0件の説明を読み終えた業者の次の一手を、ページ末尾の小さな
              テキストリンクからこの位置の通常ボタンへ移す（末尾の .vd-join は削除）。 */}
          <p className="vd-sample-cta">
            <Link href="/business" className="btn btn-primary">
              業者登録の詳細を見る
            </Link>
          </p>
        </>
      ) : null}
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
      {/* r5 #20: 公開ページなのにアプリ用ヘッダー（ベル・マイページ・ログアウト）が出ていた。
          未ログインは他の公開ルートと同じ SiteHeader、ログイン済みだけ AppHeader に切り替える
          （/vendors 専用のクロムは新設しない）。session が読込中は公開側を描く。 */}
      {signedIn ? <AppHeader /> : <SiteHeader />}
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
            height={1088}
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
          {/* r5 #24: 掲載0件・取得失敗のどちらでも「買い手が1社も見えない」状態になるため、
              帯の直下に出品できることを常設する（審査の通過順に入札が入る、という既存方針の再掲）。 */}
          {error || isEmpty ? (
            <p className="vd-notice">
              掲載前でも出品はできます。審査を通過した業者から順に入札します。
            </p>
          ) : null}
          {/* r3 是正: 戻るリンクは末尾（.vd-join の下）へ移した。ページ先頭の最初の導線が
              「戻る」になっていたため、本文はリード文から始める。 */}
          <p className="vendors-lead">
            {/* r2 M3 是正: 稼働直前で実投稿が0件のため、現在形の断定（そのまま公開します）は
                既に投稿が集まっているかのような誤認を招く。/company VALUES と同じ「〜します／
                〜にします」の方針表明に直す（CONSTRAINTS §3）。
                1文目「古物商許可番号を確認し…」は r2 M5 で帯のリードへ移した。 */}
            評価と口コミは、成約したユーザーの投稿をそのまま掲載する方針です。
            入札の選択は案件詳細から行えます。
            {/* r5 #30: 掲載される側（業者）から見て、事実と異なる投稿の扱いが読めなかった。
                削除の断定（運営が削除します）は実装済みの運用として確認できていないため、
                受付窓口（/contact）があることだけを書く。 */}
            事実と異なる投稿についてのご相談は、
            <Link href="/contact">お問い合わせ</Link>
            から受け付けます。
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
              {/* r6 #10: 主導線（出品する／業者登録）はこの枠の外（.vd-next）へ出した。
                  エラー文と同じ白枠に入れていたため、エラー復帰用の操作に見えていた。
                  枠の中に残すのは、エラーそのものに対する操作（再読み込み）と参照先だけ。 */}
              <p className="vd-state-sub">
                <button type="button" className="vd-state-link" onClick={() => window.location.reload()}>
                  再読み込み
                </button>
                <Link href="/faq" className="vd-state-link">
                  よくある質問（業者について）
                </Link>
                {signedIn ? (
                  <Link href="/mypage" className="vd-state-link">
                    マイ案件一覧へ
                  </Link>
                ) : null}
              </p>
            </div>
          ) : null}

          {/* r6 #10: 出品・業者登録は「一覧が読めたかどうか」に関係なく成り立つ次の一手なので、
              エラーの器（白面＋--danger のヘアライン）から出し、枠を持たない淡青面
              （ページの地 --pale-2）に置く。ボタンの見た目・文言・行き先は変えない。
              r5 #14 の「主導線はボタン・再読み込みはテキスト」という序列は維持する。 */}
          {error ? (
            <div className="vd-next">
              <Link href="/create" className="btn btn-primary">
                出品する
              </Link>
              <Link href="/business" className="btn btn-ghost">
                業者登録（審査制）について
              </Link>
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
                {/* r5 #1/#24: 同じ文が帯の直下（.vd-notice）に出るため、ここでは繰り返さない。
                    業者向けの導線は「掲載時に表示する項目」の末尾（.vd-sample-cta）に1本だけ置く。 */}
                <div className="vd-empty-cta">
                  <Link href="/create" className="btn btn-primary btn-lg">
                    出品する
                  </Link>
                </div>
              </section>
            </>
          ) : null}

          {/* 審査の基準と「掲載時に表示する項目」は、エラー時・空のときの両方で描く（R4 r4 #1）。
              架空の店舗名・エリア・数値・星・許可タグ・画像は出さない。VENDOR_CASES の店名も
              このページでは使わない（ページをまたいで実在の登録業者と読まれるため）。 */}
          {error || isEmpty ? <VendorStaticInfo showSample={isEmpty} /> : null}

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

          {/* ============ 末尾: 業者登録導線 ============
              r5 #14/#33: 「業者として掲載を希望される方は…」＋テキストリンクは、
              エラーカードのボタン（業者登録（審査制）について）と「掲載時に表示する項目」末尾の
              ボタン（業者登録の詳細を見る）と重複していたため削除した。
              一覧が1件以上あるときの業者導線はヘッダー・フッターが持つ。 */}

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

      {/* ============ フッター ============
          r5 #20: 未ログインでは他の公開14ルートと同じ4カラムの共通フッターを描く。
          ログイン済み（アプリの文脈）では従来の最小フッター（規約・法務3本＋運営者表記）を残す
          — r2 M6 の「本文が短い状態でもページの底を作る」目的はどちらでも満たされる。 */}
      {signedIn ? (
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
      ) : (
        <SiteFooter />
      )}
    </div>
  );
}
