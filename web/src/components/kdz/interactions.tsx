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
 * prefers-reduced-motion は CSS 側で尊重済み。
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
    const io = new IntersectionObserver(
      (entries) => {
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
    return () => io.disconnect();
  }, []);
  const Component = Tag as ElementType;
  return (
    <Component ref={ref as Ref<HTMLElement>} className={`rv ${className}`.trim()} data-d={delay}>
      {children}
    </Component>
  );
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
