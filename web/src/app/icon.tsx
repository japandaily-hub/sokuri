import { ImageResponse } from "next/og";

/**
 * Next.js 15 File Convention: /icon
 * favicon を動的生成（32x32）。Apple/Android デバイスは別 file convention で対応可。
 */
export const runtime = "edge";
export const size = { width: 32, height: 32 };
export const contentType = "image/png";

export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background:
            "linear-gradient(135deg, #1f54de 0%, #1d3677 100%)",
          color: "#ffffff",
          fontSize: "20px",
          fontWeight: 800,
          fontFamily: '"Hiragino Sans", "Yu Gothic UI", sans-serif',
          borderRadius: "6px",
        }}
      >
        S
      </div>
    ),
    { ...size },
  );
}
