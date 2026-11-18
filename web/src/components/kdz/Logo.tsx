/**
 * カタヅケ ロゴ（二段の文字ワードマーク）。
 * 見本 v12 の .logo に合わせ、丸ゴ 700 の和文のみのワードマーク（CSS: .kdz-wm / katazuke.css）で描く。
 * 英字（KATAZUKE）は撤去した。白抜きは variant="white"。size は和文の font-size(px)。
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
  return (
    <span
      className={`kdz-wm${white ? " white" : ""}${className ? ` ${className}` : ""}`}
      style={{ "--wm": `${size}px` } as React.CSSProperties}
    >
      <span className="kdz-wm-ja">カタヅケ</span>
    </span>
  );
}
