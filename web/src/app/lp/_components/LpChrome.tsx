"use client";

/**
 * /lp の独自クロム（参照LP `.l-header` / `.l-sitemap` / 浮遊CTA の移植）。
 * `/lp` は SiteChrome の BARE_PREFIXES 対象のため、共通ヘッダー・額装・Dock・共通フッターは付かない。
 * pagetop は参照どおり footer 内の absolute ブロックなので page.tsx 側が描く（r1 A-1）。
 *
 * 参照の実測値（reference-spec.md (b)）:
 * - MENU ボタンは `position:fixed` の主色ブロック（PC 164×141）。`aria-expanded` / `aria-controls` 付き。
 * - オーバーレイは `opacity`+`visibility` の 700ms フェード（スライド・拡大は伴わない）。
 * - 浮遊CTAは画面右上に常時浮遊（PC 220×150 / SP 129×94）。SP は下部に置く。
 *
 * カタヅケ側の作法に置換した点:
 * - 角丸・blob・clip-path のオーバル → すべて直角。
 * - 参照の黄 blob「たまごを購入する」→ 既存 `.btn.btn-line`（タイル＋ラベル＋sub＋矢印）のコンパクト版。
 *   LINE 単独導線にしないため、PC / SP とも直下にテキスト導線を併置する（r1 A-6）。
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Ic } from "@/components/kdz/Icons";
import { KdzLogo } from "@/components/kdz/Logo";

/** オーバーレイ内のページ内アンカー（区画の並び順と一致させる） */
const MENU_ANCHORS: { href: string; label: string }[] = [
  { href: "#top", label: "トップ" },
  { href: "#about", label: "カタヅケについて" },
  { href: "#point", label: "しくみと安心" },
  { href: "#daily", label: "出品から引き取りまで" },
  { href: "#fee", label: "料金" },
  { href: "#cases", label: "利用イメージ" },
  { href: "#biz", label: "業者の方へ" },
];

/** オーバーレイ内の外部リンク（参照の「公式サイト」2枚パネル相当は下段の2枚が担う） */
const MENU_LINKS: { href: string; label: string }[] = [
  { href: "/login?callbackUrl=%2Fmypage", label: "ログイン" },
  { href: "/mypage", label: "マイページ" },
  { href: "/faq", label: "よくある質問" },
  { href: "/business", label: "業者登録" },
];

/** オーバーレイを開いている間 `inert` にする背面要素（r1 A-4 / qa H1）。
 *  MENU ボタン自身（CLOSE 操作）は対象外にするため、ヘッダー内はロゴだけを個別に指定する。 */
const INERT_SELECTORS = ["#main", ".lp-footer"];

/** フォーカス可能要素（Tab 循環の両端を求める用） */
const FOCUSABLE = 'a[href],button:not([disabled]),input,select,textarea,[tabindex]:not([tabindex="-1"])';

export function LpChrome() {
  const [open, setOpen] = useState(false);
  /** フッターが見えている間は浮遊CTAを退避する（r3 A-5）。pagetop と操作要素が重なるのを根絶する。 */
  const [footerInView, setFooterInView] = useState(false);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLElement>(null);
  // MENU 開時とフッター表示時は同じ「退避状態」として扱う
  const ctaHidden = open || footerInView;

  const close = useCallback(() => {
    setOpen(false);
    buttonRef.current?.focus();
  }, []);

  /* qa r2 L-3: ページ内アンカーで閉じるときは MENU ボタンへ戻さず、移動先の区画へフォーカスを送る
     （戻すとキーボード利用者だけ画面が動いてもフォーカスがヘッダーに残る）。
     qa r3 H-4: 同期で focus() すると #main にまだ inert が付いており（解除は effect の
     クリーンアップ＝コミット後）、inert 部分木は仕様上フォーカス不能なので無言で失敗する。
     inert が外れた後のフレームまで 2 段の rAF で遅らせる。
     2026-09-18 バグ修正: 従来は <a href="#id"> のブラウザ既定動作（ハッシュ遷移＋スクロール）任せ
     だったが、メニュー表示中は下の useEffect が body.style.overflow="hidden" を立てており、
     クリックした瞬間はまだ（React の effect クリーンアップは非同期のため）overflow:hidden が
     外れておらず、既定のスクロールが丸ごと無効になっていた（実機再現：メニューからの遷移が
     一切スクロールしない）。既定動作を止め、overflow を同期的に戻したうえで自前でスクロールする。
     scroll-margin-top（lp.css）により固定ヘッダーの下に正しく着地する。 */
  const closeToAnchor = useCallback((e: React.MouseEvent<HTMLAnchorElement>, href: string) => {
    e.preventDefault();
    setOpen(false);
    document.body.style.overflow = "";
    if (!href.startsWith("#")) return;
    const id = href.slice(1);
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        const section = document.getElementById(id);
        if (!section) return;
        section.scrollIntoView({ block: "start" });
        history.pushState(null, "", `#${id}`);
        // 区画そのものはアクセシブル名を持たないので、区画の先頭見出しへ送る（無ければ区画）
        const target = section.querySelector<HTMLElement>("h1, h2, h3") ?? section;
        target.setAttribute("tabindex", "-1");
        target.focus({ preventScroll: true });
      })
    );
  }, []);

  // 開いている間は背面をスクロールさせない（参照と同じ挙動）。閉じたら必ず元に戻す。
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  /* qa H1: 開いている間は背面（main・footer）へ Tab が抜けないよう inert を付ける。
     main / footer はサーバーコンポーネント側の DOM なので、ここから属性で制御する
     （状態を持ち上げてページ全体を client 化しない）。 */
  useEffect(() => {
    if (!open) return;
    const targets = INERT_SELECTORS.flatMap((sel) => Array.from(document.querySelectorAll<HTMLElement>(sel)));
    targets.forEach((el) => el.setAttribute("inert", ""));
    return () => targets.forEach((el) => el.removeAttribute("inert"));
  }, [open]);

  // Esc で閉じる／Tab・Shift+Tab を nav の内側で循環させる
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        close();
        return;
      }
      if (e.key !== "Tab") return;
      const panel = panelRef.current;
      if (!panel) return;
      // 閉じる手段をキーボードから奪わないため、MENU(CLOSE) ボタンも循環の輪に含める
      const items = [buttonRef.current, ...Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE))].filter(
        (el): el is HTMLElement => el !== null
      );
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;
      const index = active instanceof HTMLElement ? items.indexOf(active) : -1;
      if (index === -1) {
        e.preventDefault();
        (e.shiftKey ? last : first).focus();
        return;
      }
      if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      } else if (e.shiftKey && active === first) {
        e.preventDefault();
        last.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, close]);

  // 開いた直後は先頭のリンクへフォーカスを移す（キーボード操作でオーバーレイに入れるように）
  useEffect(() => {
    if (!open) return;
    // is-open 直後の最初のフレームでは computed visibility がまだ hidden で focus() が空振りする
    // （実測: 1 段目の rAF で失敗・2 段目で成功）。描画が確定した 2 フレーム目で移す。
    let inner = 0;
    const outer = requestAnimationFrame(() => {
      inner = requestAnimationFrame(() => {
        const first = panelRef.current?.querySelector<HTMLAnchorElement>("a[href]");
        first?.focus();
      });
    });
    return () => {
      cancelAnimationFrame(outer);
      cancelAnimationFrame(inner);
    };
  }, [open]);

  /* r3 A-5: フッターがビューポートに入っている間は浮遊CTAを退避する。
     縦タブ／下部バーが `.lp-pagetop` と操作領域を奪い合う問題（r1・r2・r3 と 3 度再発）を、
     「フッターに着いたら CTA は要らない」という単純な規則で根絶する。reduced-motion に依らず動作。 */
  useEffect(() => {
    const footer = document.querySelector(".lp-footer");
    if (!footer) return;
    if (!("IntersectionObserver" in window)) return;
    const io = new IntersectionObserver((entries) => setFooterInView(entries.some((e) => e.isIntersecting)), {
      threshold: 0,
    });
    io.observe(footer);
    return () => io.disconnect();
  }, []);

  return (
    <>
      {/* qa M1: banner ランドマークにするため <header> で描く */}
      <header className="lp-header">
        <Link
          href="/"
          className="lp-header__logo"
          aria-label="カタヅケ トップページへ"
          inert={open ? true : undefined}
        >
          <KdzLogo size={22} />
        </Link>
        <button
          ref={buttonRef}
          type="button"
          className="lp-header__menu"
          aria-expanded={open}
          aria-controls="lp-sitemap"
          onClick={() => (open ? close() : setOpen(true))}
        >
          <span className="lp-header__menu-icon" aria-hidden="true">
            <span />
            <span />
          </span>
          <span className="lp-header__menu-label">
            MENU
            <span>{open ? "CLOSE" : "OPEN"}</span>
          </span>
        </button>
      </header>

      {/* 浮遊CTA（参照の黄 blob の位置）。PC / SP とも直下にテキスト導線を添え、LINE 単独導線にしない */}
      <div className="lp-float-cta" inert={ctaHidden ? true : undefined}>
        <Link href="/login?callbackUrl=%2Fmypage" className="btn btn-line lp-float-cta__btn">
          <span className="btn-line__tile" aria-hidden="true" />
          <span className="btn-line__body">
            <span className="btn-line__label">LINEではじめる</span>
            <span className="btn-line__sub">出品・査定・お断りまで無料</span>
          </span>
          <Ic name="arrow" className="btn-line__arr" />
        </Link>
        {/* r3 M-3: 縦書き 9 文字だとタブ全体が 358px まで伸びる。ラベルは「よくある質問」6 文字に */}
        <Link href="/faq" className="lp-float-cta__alt">
          よくある質問
        </Link>
      </div>

      <nav
        id="lp-sitemap"
        ref={panelRef}
        className={`lp-menu${open ? " is-open" : ""}`}
        aria-label="ページ内メニュー"
      >
        <div className="lp-menu__visual" aria-hidden="true">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/img/v2/top-cta-band.webp" width={1920} height={1088} alt="" loading="lazy" decoding="async" />
        </div>
        <div className="lp-menu__body">
          <ul className="lp-menu__list">
            {MENU_ANCHORS.map((a) => (
              <li key={a.href}>
                <a href={a.href} onClick={(e) => closeToAnchor(e, a.href)}>
                  <span className="lp-menu__mark" aria-hidden="true">
                    <Ic name="arrow" />
                  </span>
                  {a.label}
                </a>
              </li>
            ))}
            {MENU_LINKS.map((a) => (
              <li key={a.href}>
                <Link href={a.href} onClick={close}>
                  <span className="lp-menu__mark" aria-hidden="true">
                    <Ic name="arrow" />
                  </span>
                  {a.label}
                </Link>
              </li>
            ))}
          </ul>

          <Link href="/login?callbackUrl=%2Fmypage" className="btn btn-line lp-menu__cta" onClick={close}>
            <span className="btn-line__tile" aria-hidden="true" />
            <span className="btn-line__body">
              <span className="btn-line__label">LINEではじめる（無料）</span>
              <span className="btn-line__sub">LINEアカウントでログインできます</span>
            </span>
            <Ic name="arrow" className="btn-line__arr" />
          </Link>

          <div className="lp-menu__panels">
            <Link href="/examples" className="lp-menu__panel" onClick={close}>
              <span className="lp-menu__panel-title">利用イメージ</span>
              <span className="lp-menu__panel-link">
                6件のモデルケースを見る
                <Ic name="arrow" />
              </span>
            </Link>
            <Link href="/business" className="lp-menu__panel" onClick={close}>
              <span className="lp-menu__panel-title">買取業者の方へ</span>
              <span className="lp-menu__panel-link">
                業者登録の詳細を見る
                <Ic name="arrow" />
              </span>
            </Link>
          </div>

          <p className="lp-menu__foot">
            <KdzLogo size={18} />
            <span>対応エリア：東京都・千葉県・埼玉県・神奈川県（順次拡大）</span>
          </p>
        </div>
      </nav>
    </>
  );
}
