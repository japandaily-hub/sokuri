/**
 * カタヅケ ロゴ（ワードマーク）。
 * 正規アセット logo-katazuke.png（web/public/、house型ブランドマーク+ワードマーク、
 * 1100x307・透過PNG）を使用する。white variant はダーク背景向けに白一色反転。
 */
const LOGO_ASPECT = 1100 / 307;

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
  // size はワードマークのテキスト相当の視覚サイズに合わせる（旧実装のフォントサイズ22=標準）。
  const height = Math.round(size * 1.45);
  const width = Math.round(height * LOGO_ASPECT);
  return (
    <span className={`inline-flex items-center ${className}`.trim()} aria-label="カタヅケ">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src="/logo-katazuke.png"
        alt="カタヅケ"
        width={width}
        height={height}
        style={{
          width,
          height,
          display: "block",
          filter: white ? "brightness(0) invert(1)" : "none",
        }}
      />
    </span>
  );
}
