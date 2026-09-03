/**
 * カタヅケ ロゴ（二段の文字ワードマーク）。
 * 人の森整合テーマでは紺+黄の PNG が最大の混色源になるため、和文明朝＋極小英字の
 * ワードマーク（CSS: .kdz-wm / katazuke.css）で描く。白抜きは variant="white"。
 * size は和文の font-size(px)。英字はその 0.4 倍で追従する。
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
      {/* 英字は装飾。SR が「カタヅケ KATAZUKE」と二重に読むのを避ける */}
      <span className="kdz-wm-en" aria-hidden="true">
        KATAZUKE
      </span>
    </span>
  );
}
