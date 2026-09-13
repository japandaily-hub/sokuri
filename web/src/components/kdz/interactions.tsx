"use client";

import {
  useEffect,
  useRef,
  useState,
  type ElementType,
  type ReactNode,
  type Ref,
} from "react";
import { Ic, type IcName } from "./Icons";

/**
 * スクロール進捗バー（デザイン .scroll-progress）。
 * ページ最上部に固定し、読了率を可視化する。
 */
export function ScrollProgress() {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onScroll = () => {
      const el = ref.current;
      if (!el) return;
      const h = document.documentElement;
      const max = h.scrollHeight - h.clientHeight;
      const pct = max > 0 ? (h.scrollTop / max) * 100 : 0;
      el.style.width = `${pct}%`;
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, []);
  return <div ref={ref} className="scroll-progress" aria-hidden="true" />;
}

/**
 * スクロール到達でフェードイン（デザイン .rv → .in）。
 * 非表示（opacity:0）になるのは layout.tsx が <html> に js-rv を付けた時だけ（IO あり・reduced-motion でない）。
 * IO が発火しないケース（レイアウト前の 0 高さ・古い WebView 等）の保険として、マウント後 1200ms で .in を強制付与する。
 */
export function Reveal({
  children,
  className = "",
  delay,
  as: Tag = "div",
}: {
  children: ReactNode;
  className?: string;
  delay?: 1 | 2 | 3;
  as?: "div" | "article" | "li" | "section" | "figure";
}) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const show = () => el.classList.add("in");
    const fallback = window.setTimeout(show, 1200);
    if (!("IntersectionObserver" in window)) {
      show();
      return () => window.clearTimeout(fallback);
    }
    const io = new IntersectionObserver(
      (entries) => {
        // QA M2 是正: IO は observe 直後に必ず1回コールバックを返す（交差していなくても）。
        // その初回で保険を解除すれば「IO が生きている証明」になり、1200ms の強制表示は
        // IO が発火しない環境だけで効く（従来は IO が正常でも 1.2 秒で全 .rv が出ていた）。
        window.clearTimeout(fallback);
        entries.forEach((e) => {
          if (e.isIntersecting) {
            e.target.classList.add("in");
            io.unobserve(e.target);
          }
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -8% 0px" }
    );
    io.observe(el);
    return () => {
      window.clearTimeout(fallback);
      io.disconnect();
    };
  }, []);
  const Component = Tag as ElementType;
  return (
    <Component ref={ref as Ref<HTMLElement>} className={`rv ${className}`.trim()} data-d={delay}>
      {children}
    </Component>
  );
}

/** 面としてのフォールバック（--pale-2 の枠地・濃紺の帯地）を自前で持つ入れ物の中の画像。
 *  ここは alt の有無に関わらず視覚的に隠してよい（壊れアイコン＋alt 文字より枠の地の方が読める）。 */
const FRAMED_IMG_SELECTOR = ".img-frame img, .hero-band > img, .auth-side > img";

/**
 * 画像が取得できなかったとき、Chrome が左上に描く壊れ画像アイコン（と alt 文字）を消す保険。
 * CSS の color:transparent / font-size:0 では alt 文字しか消えずアイコンは残る（実測）。
 * 対象は ① alt=""（装飾画像）と ② 枠・帯の中の画像（alt の有無を問わない）。
 * ② を足したのはラウンド2 の実測による: 意味を持つ alt を付けた未生成画像（ex-lot-*・biz-hero・pg-hero）で
 * 枠内に alt 文字と壊れアイコンが並び、枠がエラー表示に見えていた。alt 属性は DOM に残すので読み上げは不変で、
 * 品目名を出したい枠は .img-frame[data-label]::before が受ける。
 * eager + fetchPriority の画像はマウント前に失敗して error が再発火しないため、走査は load 後にも行う。
 */
export function BrokenImageGuard() {
  useEffect(() => {
    const covered = (img: HTMLImageElement) =>
      img.getAttribute("alt") === "" || img.matches(FRAMED_IMG_SELECTOR);
    // 証跡系の画像（古物商許可証・本人確認書類）は取得失敗を可視化したままにする（審査判断を誤らせない）
    const EVIDENCE_PATH = /^\/(admin|mypage\/identity)(\/|$)/;
    const hide = (img: HTMLImageElement) => {
      if (EVIDENCE_PATH.test(window.location.pathname)) return;
      if (covered(img)) img.style.visibility = "hidden";
    };
    // error はバブルしないのでキャプチャ段で拾う（lazy で後から失敗する分もここに来る）
    const onError = (e: Event) => {
      if (e.target instanceof HTMLImageElement) hide(e.target);
    };
    document.addEventListener("error", onError, true);
    // マウント前に失敗済みの分は error が再発火しないため走査で拾う
    const sweep = () => {
      document
        .querySelectorAll<HTMLImageElement>(`img[alt=""], ${FRAMED_IMG_SELECTOR}`)
        .forEach((img) => {
          if (img.complete && img.naturalWidth === 0) hide(img);
        });
    };
    sweep();
    // load 前にマウントした場合（eager 画像の失敗がまだ確定していない場合）の取りこぼしを拾う
    const pending = document.readyState !== "complete";
    if (pending) window.addEventListener("load", sweep);
    const later = window.setTimeout(sweep, 1500);
    return () => {
      document.removeEventListener("error", onError, true);
      if (pending) window.removeEventListener("load", sweep);
      window.clearTimeout(later);
    };
  }, []);
  return null;
}

/**
 * 画像 + 失敗時プレースホルダ（デザイン .ph-wrap > img + .imgph）。
 * 親要素に ph-wrap クラスを付与して使う。実アセット未投入でも崩れない。
 */
export function PhImg({
  src,
  alt,
  label,
  icon = "camera",
  className,
  imgStyle,
}: {
  src: string;
  alt: string;
  label?: string;
  icon?: IcName;
  className?: string;
  imgStyle?: React.CSSProperties;
}) {
  const [err, setErr] = useState(false);
  return (
    <>
      {!err && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={src}
          alt={alt}
          loading="lazy"
          className={className}
          style={imgStyle}
          onError={() => setErr(true)}
        />
      )}
      {err && (
        <div className="imgph" style={{ display: "flex" }}>
          <Ic name={icon} />
          {label ? <small>{label}</small> : null}
        </div>
      )}
    </>
  );
}

/** FAQ アコーディオン（デザイン .faq-item / .open 開閉）。 */
export function FaqAccordion({
  items,
  defaultOpen = 0,
}: {
  items: { q: string; a: ReactNode }[];
  defaultOpen?: number | null;
}) {
  const [open, setOpen] = useState<number | null>(defaultOpen);
  return (
    <div className="faq-list">
      {items.map((it, i) => {
        const isOpen = open === i;
        return (
          <div key={i} className={`faq-item${isOpen ? " open" : ""}`}>
            <button
              type="button"
              className="faq-q"
              aria-expanded={isOpen}
              onClick={() => setOpen(isOpen ? null : i)}
            >
              <span className="qmark">Q</span>
              <span style={{ flex: 1 }}>{it.q}</span>
              <Ic name="chev" className="chev" />
            </button>
            <div className="faq-a" style={{ maxHeight: isOpen ? 600 : 0 }}>
              <div className="faq-a-inner">{it.a}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
