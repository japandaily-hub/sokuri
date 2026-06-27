import "./not-found.css";
import Link from "next/link";
import { Ic } from "@/components/kdz/Icons";

/**
 * Next.js 15 App Router: 404 ページ。
 * デザイン正典 docs/design_handoff_katazuke/404.html をピクセル忠実に再現。
 * 共通クロム（SiteHeader/SiteFooter/Dock）配下で表示されるため独自ヘッダーは描かず、
 * フローティングする箱アイコン + よく使うページ導線3件 + トップ復帰のカードのみを担う。
 */
export const metadata = {
  title: "ページが見つかりません",
};

/** よく使うページ導線（3件）。アイコン面色はデザインのインラインstyleを踏襲。 */
const LINKS: {
  href: string;
  title: string;
  desc: string;
  icon: "house" | "box";
  bg: string;
  color: string;
}[] = [
  {
    href: "/",
    title: "トップページへ",
    desc: "カタヅケのトップに戻る",
    icon: "house",
    bg: "var(--pale)",
    color: "var(--blue)",
  },
  {
    href: "/create",
    title: "出品してみる",
    desc: "不用品を出品して業者に入札してもらう",
    icon: "box",
    bg: "#e8faf0",
    color: "var(--green)",
  },
];

export default function NotFound() {
  return (
    <main id="main" className="nf-main">
      <div className="nf-card">
        <div className="nf-icon" aria-hidden="true">
          <Ic name="box" />
        </div>
        <div className="nf-num">404</div>
        <h1 className="nf-title">ページが見つかりません</h1>
        <p className="nf-sub">
          お探しのページは移動・削除されたか、
          <br />
          URLが正しくない可能性があります。
        </p>

        <div className="nf-links">
          {LINKS.map((l) => (
            <Link href={l.href} className="nf-link" key={l.href}>
              <div className="nf-link-ic" style={{ background: l.bg, color: l.color }}>
                <Ic name={l.icon} />
              </div>
              <div className="nf-link-body">
                <strong>{l.title}</strong>
                <span>{l.desc}</span>
              </div>
              <div className="nf-link-arr">
                <Ic name="arrow" />
              </div>
            </Link>
          ))}

          {/* よくある質問: Icons.tsx に該当アイコンが無いため疑問符サークルをインラインSVGで再現 */}
          <Link href="/faq" className="nf-link">
            <div className="nf-link-ic" style={{ background: "#f6eeff", color: "#6c3495" }}>
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <circle cx="12" cy="12" r="9" />
                <path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3M12 17h.01" />
              </svg>
            </div>
            <div className="nf-link-body">
              <strong>よくある質問</strong>
              <span>お困りの場合はこちら</span>
            </div>
            <div className="nf-link-arr">
              <Ic name="arrow" />
            </div>
          </Link>
        </div>

        <Link href="/" className="nf-back">
          <Ic name="arrow" style={{ transform: "scaleX(-1)" }} />
          トップページへ戻る
        </Link>
      </div>
    </main>
  );
}
