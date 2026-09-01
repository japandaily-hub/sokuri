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
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="data:image/png;base64,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"
            width={72}
            height={72}
            alt=""
            style={{ borderRadius: "16px", background: "rgba(255,255,255,0.16)" }}
          />
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
