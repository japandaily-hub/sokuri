/**
 * カタヅケ ロゴ（ワードマーク）。
 * ハンドオフは logo-katazuke.png を参照するが実アセット未投入のため、
 * 角丸ブランドマーク（ハウス）＋見出しフォントのワードマークで自給する。
 * 実ロゴ確定後は本コンポーネントを差し替えるだけでよい。
 */
export function KdzLogo({
  variant = "brand",
  size = 22,
  className = "",
}: {
  variant?: "brand" | "white";
  size?: number;
  className?: string;
}) {
  const white = variant === "white";
  const mark = Math.round(size * 1.45);
  return (
    <span className={`inline-flex items-center gap-2 ${className}`.trim()} aria-label="カタヅケ">
      <span
        aria-hidden="true"
        style={{
          width: mark,
          height: mark,
          borderRadius: Math.round(mark * 0.28),
          background: white ? "rgba(255,255,255,.16)" : "var(--blue)",
          color: "#fff",
          display: "grid",
          placeItems: "center",
          flex: "none",
          boxShadow: white ? "none" : "0 6px 14px -6px rgba(31,84,222,.6)",
        }}
      >
        <svg className="ic" style={{ fontSize: Math.round(size * 0.92), strokeWidth: 2 }} aria-hidden="true">
          <use href="#i-house" />
        </svg>
      </span>
      <span
        style={{
          fontFamily: "var(--head)",
          fontWeight: 900,
          fontSize: size,
          letterSpacing: "-.01em",
          lineHeight: 1,
          color: white ? "#fff" : "var(--navy)",
        }}
      >
        カタヅケ
      </span>
    </span>
  );
}
