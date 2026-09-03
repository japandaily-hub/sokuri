import { ImageResponse } from "next/og";

/**
 * Next.js 15 File Convention: /opengraph-image
 * 1200x630 の OGP/Twitter Card 画像を動的生成する。
 * X / Slack / LINE 共有時のリッチプレビュー用。
 * 人の森整合テーマ: 白地・直角・影なし。緑の二段ワードマークと明朝の見出し。
 * フォントは既存実装と同じくシステム書体指定（外部フォントの取得は行わない）。
 */

export const runtime = "edge";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const alt = "カタヅケ｜部屋ごと撮るだけ、片付けと買取の見積もりが届く";

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
          padding: "72px 80px",
          background: "#ffffff",
          color: "#333333",
          fontFamily: '"Hiragino Mincho ProN", "Yu Mincho", serif',
          border: "1px solid #333333",
        }}
      >
        {/* Top: 二段ワードマーク */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            lineHeight: 1,
          }}
        >
          <div
            style={{
              display: "flex",
              fontSize: "46px",
              fontWeight: 400,
              letterSpacing: "0.14em",
              color: "#333333",
            }}
          >
            カタヅケ
          </div>
          <div
            style={{
              display: "flex",
              marginTop: "10px",
              fontSize: "19px",
              fontWeight: 600,
              letterSpacing: "0.18em",
              color: "#527e52",
            }}
          >
            KATAZUKE
          </div>
        </div>

        {/* Middle: headline */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "18px",
          }}
        >
          <div
            style={{
              display: "flex",
              fontSize: "74px",
              fontWeight: 400,
              lineHeight: 1.4,
              letterSpacing: "0.04em",
              color: "#333333",
            }}
          >
            部屋ごと撮るだけ。
          </div>
          <div
            style={{
              display: "flex",
              fontSize: "74px",
              fontWeight: 400,
              lineHeight: 1.4,
              letterSpacing: "0.04em",
              color: "#527e52",
            }}
          >
            片付けと買取が、まとめて片づく。
          </div>
          <div
            style={{
              display: "flex",
              width: "96px",
              height: "1px",
              background: "#527e52",
            }}
          />
        </div>

        {/* Bottom: trust chips（直角・緑細枠） */}
        <div
          style={{
            display: "flex",
            gap: "16px",
            color: "#527e52",
            fontSize: "24px",
            fontWeight: 400,
          }}
        >
          <div
            style={{
              display: "flex",
              padding: "10px 22px",
              border: "1px solid #527e52",
              background: "#ffffff",
            }}
          >
            完全無料
          </div>
          <div
            style={{
              display: "flex",
              padding: "10px 22px",
              border: "1px solid #527e52",
              background: "#ffffff",
            }}
          >
            撮るだけ
          </div>
          <div
            style={{
              display: "flex",
              padding: "10px 22px",
              border: "1px solid #527e52",
              background: "#ffffff",
            }}
          >
            AI査定
          </div>
          <div
            style={{
              display: "flex",
              padding: "10px 22px",
              border: "1px solid #527e52",
              background: "#ffffff",
            }}
          >
            営業電話ゼロ
          </div>
        </div>
      </div>
    ),
    { ...size },
  );
}
