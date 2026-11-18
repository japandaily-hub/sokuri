import { ImageResponse } from "next/og";

/**
 * Next.js 15 File Convention: /opengraph-image
 * 1200x630 の OGP/Twitter Card 画像を動的生成する。
 * X / Slack / LINE 共有時のリッチプレビュー用。
 * 見本 v12: 生成り地(#f6f2ea)・藍(#2e4a7d)・墨(#24221f)。直角・影なし。CSS 変数が使えないため値を直書きする。
 * 書体はシステム書体指定のまま（edge で和文フォントを取得する仕組みが無く、Zen Maru Gothic への替えは見送り）。
 */

export const runtime = "edge";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const alt = "カタヅケ｜家まるごと、まとめて片付け買取";

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
          background: "#f6f2ea",
          color: "#24221f",
          fontFamily: '"Hiragino Mincho ProN", "Yu Mincho", serif',
          border: "1px solid #24221f",
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
              color: "#24221f",
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
              color: "#2e4a7d",
            }}
          >
            KATAZUKE
          </div>
        </div>

        {/* 旧OGのピルを直角・細枠チップとして保持。文言は「AI査定」→「写真査定」。
            AI を主語にした査定は実装に無く（CONSTRAINTS §3・BRIEF §4.1）、本文も
            「写真と品目から」で統一しているため、OG だけ残すと誇張表示になる。 */}
        <div style={{ display: "flex", position: "absolute", top: "72px", right: "80px", border: "1px solid #2e4a7d", color: "#2e4a7d", fontSize: "22px", fontWeight: 400, padding: "8px 20px", letterSpacing: "0.08em" }}>
          写真 × 入札 × リユース
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
              color: "#24221f",
            }}
          >
            不用品を撮って送るだけ。
          </div>
          <div
            style={{
              display: "flex",
              fontSize: "74px",
              fontWeight: 400,
              lineHeight: 1.4,
              letterSpacing: "0.04em",
              color: "#2e4a7d",
            }}
          >
            片付けと買取が、まとめて片づく。
          </div>
          <div
            style={{
              display: "flex",
              width: "96px",
              height: "1px",
              background: "#2e4a7d",
            }}
          />
        </div>

        {/* Bottom: trust chips（直角・緑細枠） */}
        <div
          style={{
            display: "flex",
            gap: "16px",
            color: "#2e4a7d",
            fontSize: "24px",
            fontWeight: 400,
          }}
        >
          <div
            style={{
              display: "flex",
              padding: "10px 22px",
              border: "1px solid #2e4a7d",
              background: "#f6f2ea",
            }}
          >
            カタヅケの利用料は無料
          </div>
          <div
            style={{
              display: "flex",
              padding: "10px 22px",
              border: "1px solid #2e4a7d",
              background: "#f6f2ea",
            }}
          >
            撮るだけ
          </div>
          <div
            style={{
              display: "flex",
              padding: "10px 22px",
              border: "1px solid #2e4a7d",
              background: "#f6f2ea",
            }}
          >
            写真で入札
          </div>
          <div
            style={{
              display: "flex",
              padding: "10px 22px",
              border: "1px solid #2e4a7d",
              background: "#f6f2ea",
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
