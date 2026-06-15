import { ImageResponse } from "next/og";

/**
 * Next.js 15 File Convention: /opengraph-image
 * 1200x630 の OGP/Twitter Card 画像を動的生成する。
 * X / Slack / LINE 共有時のリッチプレビュー用。
 */

export const runtime = "edge";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const alt = "カタヅケ — 部屋ごと撮るだけ、片付けと買取の見積もりが届く";

export default function OgImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          alignItems: "flex-start",
          justifyContent: "space-between",
          padding: "80px",
          background:
            "linear-gradient(135deg, #1f54de 0%, #1d3677 60%, #141f48 100%)",
          color: "#ffffff",
          fontFamily: '"Hiragino Sans", "Yu Gothic UI", sans-serif',
        }}
      >
        {/* Top: brand badge */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "20px",
          }}
        >
          <div
            style={{
              width: "72px",
              height: "72px",
              borderRadius: "16px",
              background: "rgba(255,255,255,0.16)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: "44px",
              fontWeight: 800,
            }}
          >
            カ
          </div>
          <div
            style={{
              fontSize: "44px",
              fontWeight: 800,
              letterSpacing: "-0.02em",
            }}
          >
            カタヅケ
          </div>
          <div
            style={{
              marginLeft: "16px",
              padding: "8px 18px",
              borderRadius: "999px",
              background: "rgba(255,255,255,0.16)",
              fontSize: "22px",
              fontWeight: 600,
            }}
          >
            AI査定 × リユース
          </div>
        </div>

        {/* Middle: headline */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "20px",
          }}
        >
          <div
            style={{
              fontSize: "92px",
              fontWeight: 800,
              lineHeight: 1.1,
              letterSpacing: "-0.03em",
              color: "#ffffff",
            }}
          >
            部屋ごと撮るだけ。
          </div>
          <div
            style={{
              fontSize: "92px",
              fontWeight: 800,
              lineHeight: 1.1,
              letterSpacing: "-0.03em",
              color: "#a7f3d0",
            }}
          >
            片付けと買取が、まとめて片づく。
          </div>
        </div>

        {/* Bottom: trust chips */}
        <div
          style={{
            display: "flex",
            gap: "16px",
            color: "#cbd5e1",
            fontSize: "26px",
            fontWeight: 600,
          }}
        >
          <div
            style={{
              padding: "10px 22px",
              borderRadius: "999px",
              border: "2px solid rgba(255,255,255,0.25)",
              background: "rgba(255,255,255,0.08)",
            }}
          >
            ●完全無料
          </div>
          <div
            style={{
              padding: "10px 22px",
              borderRadius: "999px",
              border: "2px solid rgba(255,255,255,0.25)",
              background: "rgba(255,255,255,0.08)",
            }}
          >
            ●撮るだけ
          </div>
          <div
            style={{
              padding: "10px 22px",
              borderRadius: "999px",
              border: "2px solid rgba(255,255,255,0.25)",
              background: "rgba(255,255,255,0.08)",
            }}
          >
            ●AI査定
          </div>
          <div
            style={{
              padding: "10px 22px",
              borderRadius: "999px",
              border: "2px solid rgba(255,255,255,0.25)",
              background: "rgba(255,255,255,0.08)",
            }}
          >
            ●営業電話ゼロ
          </div>
        </div>
      </div>
    ),
    { ...size },
  );
}
