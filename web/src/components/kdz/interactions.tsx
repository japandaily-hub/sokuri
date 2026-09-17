"use client";

import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
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
 * スクロール到達判定（デザイン .rv → .in の共通ロジック）。Reveal / RevealLines から共用する。
 * 非表示（opacity:0）になるのは layout.tsx が <html> に js-rv を付けた時だけ（IO あり・reduced-motion でない）。
 * IO が発火しないケース（レイアウト前の 0 高さ・古い WebView 等）の保険として、マウント後 1200ms で .in を強制付与する。
 * ここのロジックは元の Reveal 実装から1文字も変えていない（IO の初回コールバックでフォールバックを
 * 解除する部分を含む）。
 */
function useInView<T extends HTMLElement>(): Ref<T> {
  const ref = useRef<T>(null);
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
  return ref as Ref<T>;
}

/**
 * スクロール到達でフェードイン（デザイン .rv → .in）。実体は useInView（薄いラッパー）。
 */
export function Reveal({
  children,
  className = "",
  delay,
  variant = "fade",
  stagger,
  as: Tag = "div",
  style: styleProp,
  ...rest
}: {
  children: ReactNode;
  className?: string;
  /** @deprecated 固定ディレイ（.08s/.16s/.24s）。新規実装は stagger を使う想定だが後方互換のため残す */
  delay?: 1 | 2 | 3;
  /** 演出の種類。既定 "fade" は現行挙動そのまま（opacity のみ）。"zoom" は .img-frame 直下の img でのみ使う契約 */
  variant?: "fade" | "up" | "up-sm" | "zoom";
  /** 順送りの遅延に使う index。指定時は CSS 変数 --i として出力し、katazuke-motion.css の
   *  transition-delay:calc(min(var(--i,0),5) * var(--rv-stagger)) が効く */
  stagger?: number;
  as?: "div" | "article" | "li" | "section" | "figure" | "aside";
  /** 呼び出し側の任意インラインstyle（--ill-top 等のCSS変数を渡す用途）。内部の --i(stagger) と合流する */
  style?: CSSProperties;
  /** data-label 等、ラップ先要素（.img-frame 等）が既存 CSS で要求する任意の HTML 属性の素通し用。
   *  値をプリミティブ型に絞り、将来オブジェクトのスプレッド渡しで dangerouslySetInnerHTML 等が
   *  紛れ込む経路を型レベルで塞ぐ（セキュリティレビュー対応） */
  [key: `data-${string}`]: string | number | boolean | undefined;
}) {
  const ref = useInView<HTMLElement>();
  const Component = Tag as ElementType;
  const variantClass = variant !== "fade" ? ` rv--${variant}` : "";
  // 数値以外・負値・非有限値が紛れ込んでも CSS 変数には安全な整数だけを渡す（0-5 にクランプ）
  const safeStagger =
    stagger !== undefined && Number.isFinite(stagger)
      ? Math.min(Math.max(Math.trunc(stagger), 0), 5)
      : undefined;
  const style: CSSProperties | undefined =
    safeStagger !== undefined || styleProp
      ? { ...(safeStagger !== undefined ? ({ "--i": safeStagger } as CSSProperties) : null), ...styleProp }
      : undefined;
  return (
    <Component
      ref={ref}
      className={`rv${variantClass} ${className}`.trim()}
      data-d={delay}
      style={style}
      {...rest}
    >
      {children}
    </Component>
  );
}

/**
 * 見出しを1行ずつフェード＋上スライドで見せる（デザイン .rvl / .rvl__line、参考: felissimo/gopeace 実測）。
 * lines は「1要素=1行」を書き手が明示的に分割する契約。DOM 測定による自動折返し検出は行わない
 * （幅に応じた自動改行と組み合わせると行アニメーションの単位が崩れるため）。
 */
export function RevealLines({
  lines,
  as: Tag = "h2",
  mark = "none",
  className = "",
  id,
}: {
  lines: ReactNode[];
  as?: "h1" | "h2" | "h3" | "p";
  mark?: "none" | "under";
  className?: string;
  /** 呼び出し側が既存のページ内アンカー（目次リンクの遷移先・aria-labelledby の参照先）を
   *  維持する用途。未指定時は従来どおり id なしで描画する（既存呼び出しの挙動は変えない） */
  id?: string;
}) {
  const ref = useInView<HTMLElement>();
  const Component = Tag as ElementType;
  const markClass = mark === "under" ? " rvl--mark" : "";
  return (
    <Component
      ref={ref}
      id={id}
      className={`rv rvl${markClass} ${className}`.trim()}
    >
      {lines.map((line, i) => (
        <span className="rvl__line" style={{ "--i": i } as CSSProperties} key={i}>
          {line}
        </span>
      ))}
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

/** ヒーロー カルーセルの1枚（/img/v2/<id>.webp）。 */
export type HeroSlide = {
  /** ファイル名（拡張子なし）。src は `/img/v2/${id}.webp` に固定。 */
  id: string;
  /** 意味のある alt（人物の年代・場面が分かる1文＋「（イメージ）」）。 */
  alt: string;
  width: number;
  height: number;
};

/**
 * トップ ヒーロー写真のペルソナ・カルーセル（.hero-photo > .img-frame の中身を担う）。
 * 依頼者の像を「若い女性→若い男性→30代夫婦と子ども→60代夫婦」の順に巡回させ、
 * 誰が使うサービスかを一人の像に固定しない（ユーザー指示 2026-09-14）。
 *
 * 実装方針:
 * - `.img-frame img` は共有 CSS（katazuke-pages.css）で `position:absolute;inset:0` 済みなので、
 *   同じ枠に複数の <img> を重ねて敷くだけで版面が揃う。切替は opacity のクロスフェードのみ
 *   （デザイン正典: fade 以外のモーションを使わない）。
 * - JS 未実行時は React の初期状態（1枚目のみ .is-active）がそのまま出るため、無JSでも崩れない
 *   （`.rv` の js-rv ゲートのような追加の保険は不要 — 初期状態自体が「意味のある1枚」だから）。
 * - 1枚目のみ LCP（eager + fetchPriority high）。残り3枚も eager だが fetchPriority low で
 *   先読みしつつ LCP を譲る（初回の巡回でちらつかないように事前に読み込んでおく）。
 * - `prefers-reduced-motion: reduce` では自動巡回しない（初期状態のまま静止）。ドットでの
 *   手動切替は動作するが、同メディアクエリで transition 自体を切るため瞬時に切り替わる
 *   （自動再生ではなく利用者の操作なので WCAG のアニメーション回避の対象外）。
 * - 自動巡回には一時停止ボタンを必ず添える（WCAG 2.2.2 Pause, Stop, Hide）。タブが非表示の間・
 *   ホバー/フォーカス中は自動送りを止める。
 */
export function HeroCarousel({
  slides,
  intervalMs = 5000,
}: {
  slides: HeroSlide[];
  intervalMs?: number;
}) {
  const [current, setCurrent] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [reducedMotion, setReducedMotion] = useState(false);
  const pausedRef = useRef(false);

  useEffect(() => {
    if (!("matchMedia" in window)) return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReducedMotion(mq.matches);
    const onChange = () => setReducedMotion(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    if (!playing || reducedMotion || slides.length < 2) return;
    const id = window.setInterval(() => {
      if (pausedRef.current || document.hidden) return;
      setCurrent((i) => (i + 1) % slides.length);
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [playing, reducedMotion, slides.length, intervalMs]);

  if (slides.length === 0) return null;
  const pause = () => { pausedRef.current = true; };
  const resume = () => { pausedRef.current = false; };

  return (
    <>
      <div
        className="img-frame img-frame--2x3 img-frame--hero-person"
        onMouseEnter={pause}
        onMouseLeave={resume}
      >
        {slides.map((s, i) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={s.id}
            src={`/img/v2/${s.id}.webp`}
            width={s.width}
            height={s.height}
            alt={s.alt}
            aria-hidden={i === current ? undefined : true}
            className={`hero-carousel__slide${i === current ? " is-active" : ""}`}
            loading="eager"
            fetchPriority={i === 0 ? "high" : "low"}
            decoding="async"
          />
        ))}
        {slides.length > 1 && (
          <div className="hero-carousel__ctrl" onFocus={pause} onBlur={resume}>
            <div className="hero-carousel__dots" role="tablist" aria-label="表示する人物を選ぶ">
              {slides.map((s, i) => (
                <button
                  key={s.id}
                  type="button"
                  role="tab"
                  aria-selected={i === current}
                  aria-label={`${i + 1}枚目: ${s.alt.replace(/（イメージ）$/, "")}を表示`}
                  className={`hero-carousel__dot${i === current ? " is-active" : ""}`}
                  onClick={() => setCurrent(i)}
                />
              ))}
            </div>
            {!reducedMotion && (
              <button
                type="button"
                className="hero-carousel__toggle"
                aria-pressed={!playing}
                aria-label={playing ? "自動切り替えを一時停止" : "自動切り替えを再開"}
                onClick={() => setPlaying((p) => !p)}
              >
                <Ic name={playing ? "pause" : "play"} />
              </button>
            )}
          </div>
        )}
      </div>
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
