import type { CSSProperties } from "react";
import { Reveal } from "@/components/kdz/interactions";

/**
 * スクロールに連動して描かれる 3 本の滑らかな曲線（水＝青・新緑＝緑・星＝黄）。
 * - path は pathLength="1" で正規化し、stroke-dashoffset 1→0 で「線が伸びる」動きを作る。
 * - 基本は Reveal（IntersectionObserver）で画面に入った時に描く（全ブラウザ）。
 *   animation-timeline: view() 対応ブラウザではスクロール量に追従して描画・視差が付く（lp.css）。
 * - 純装飾なので外側の div に aria-hidden。色・太さ・位置は lp.css の .lp-ribbon--* が持つ。
 */
const CURVES = {
  /* 添付スケッチの 3 本: 左下から右上へ、末端で立ち上がる */
  a: [
    "M 40 400 C 260 330, 480 330, 660 230 S 920 90, 980 10",
    "M 220 520 C 460 440, 640 340, 810 240 S 960 140, 1010 100",
    "M 60 600 C 300 530, 560 410, 760 310 S 940 190, 1020 160",
  ],
  /* 反転（右下→左上） */
  b: [
    "M 1160 400 C 940 330, 720 330, 540 230 S 280 90, 220 10",
    "M 980 520 C 740 440, 560 340, 390 240 S 240 140, 190 100",
    "M 1140 600 C 900 530, 640 410, 440 310 S 260 190, 180 160",
  ],
} as const;

const STARS: { x: number; y: number; s: number }[] = [
  { x: 1010, y: 40, s: 1 },
  { x: 940, y: 120, s: 0.6 },
  { x: 1060, y: 150, s: 0.75 },
  { x: 870, y: 60, s: 0.5 },
  { x: 1090, y: 90, s: 0.45 },
];

export function LpRibbon({
  variant = "a",
  className = "",
  stars = true,
}: {
  variant?: keyof typeof CURVES;
  className?: string;
  stars?: boolean;
}) {
  const paths = CURVES[variant];
  const mirror = variant === "b";
  return (
    <div className={`lp-ribbon lp-ribbon--${variant} ${className}`.trim()} aria-hidden="true">
      <Reveal className="lp-ribbon__inner">
        <svg viewBox="0 0 1200 620" fill="none" xmlns="http://www.w3.org/2000/svg" focusable="false">
          {paths.map((d, i) => (
            <path key={i} d={d} pathLength={1} className={`lp-ribbon__line lp-ribbon__line--${i + 1}`} />
          ))}
          {/* 位置は <g> の transform 属性で持つ。path 側は CSS の transform（きらめきの拡縮・回転）だけにし、
              属性 transform が CSS に上書きされて全星が原点へ集まる事故を避ける */}
          {stars &&
            STARS.map((st, i) => (
              <g key={`s${i}`} transform={`translate(${mirror ? 1200 - st.x : st.x} ${st.y}) scale(${st.s})`}>
                <path
                  className="lp-ribbon__star"
                  style={{ "--lp-star-i": i } as CSSProperties}
                  d="M0 -12 C1.2 -4 4 -1.2 12 0 C4 1.2 1.2 4 0 12 C-1.2 4 -4 1.2 -12 0 C-4 -1.2 -1.2 -4 0 -12 Z"
                />
              </g>
            ))}
        </svg>
      </Reveal>
    </div>
  );
}
