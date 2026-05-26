import { ImageResponse } from "next/og";

/**
 * Next.js 15 File Convention: /apple-icon
 * iOS の「ホーム画面に追加」用 180×180 アイコン。PWA standalone 表示時に使用される。
 */
export const runtime = "edge";
export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "linear-gradient(135deg, #1f54de 0%, #1d3677 100%)",
          color: "#ffffff",
          fontSize: "110px",
          fontWeight: 800,
          fontFamily: '"Hiragino Sans", "Yu Gothic UI", sans-serif',
          // iOS は角丸を自動付与するため、ここでは角丸不要
        }}
      >
        S
      </div>
    ),
    { ...size },
  );
}
