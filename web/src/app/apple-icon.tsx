import { ImageResponse } from "next/og";

/**
 * Next.js 15 File Convention: /apple-icon
 * iOS の「ホーム画面に追加」用 180×180 アイコン。PWA standalone 表示時に使用される。
 * 人の森整合テーマ: 白地に緑の二段ワードマーク（カタヅケ / KATAZUKE）。
 * フォントは既存実装と同じくシステム書体指定（外部フォントの取得は行わない）。
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
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          background: "#ffffff",
          fontFamily: '"Hiragino Mincho ProN", "Yu Mincho", serif',
          // iOS は角丸を自動付与するため、ここでは角丸不要
        }}
      >
        <div
          style={{
            display: "flex",
            fontSize: "44px",
            fontWeight: 400,
            letterSpacing: "0.06em",
            color: "#333333",
            lineHeight: 1,
          }}
        >
          カタヅケ
        </div>
        <div
          style={{
            display: "flex",
            marginTop: "12px",
            fontSize: "16px",
            fontWeight: 600,
            letterSpacing: "0.18em",
            color: "#1447e0",
            lineHeight: 1,
          }}
        >
          KATAZUKE
        </div>
      </div>
    ),
    { ...size },
  );
}
