import type { CSSProperties } from "react";

/** 手描き風・多色のデコアイコン（/img/lp/deco）。page.tsx（サーバー）と LpIntro（クライアント）の両方から使う */
export const D = {
  box: "/img/lp/deco/deco-box.webp",
  camera: "/img/lp/deco/deco-camera.webp",
  clock: "/img/lp/deco/deco-clock.webp",
  teacup: "/img/lp/deco/deco-teacup.webp",
  gift: "/img/lp/deco/deco-gift.webp",
  tote: "/img/lp/deco/deco-tote.webp",
  lamp: "/img/lp/deco/deco-lamp.webp",
  plant: "/img/lp/deco/deco-plant2.webp",
} as const;

export type DecoIll = {
  src: string;
  top: string;
  left: string;
  w: number;
  sway: 1 | 2;
  float: 1 | 2 | 3;
  spTop?: string;
  spLeft?: string;
  hideSp?: boolean;
};

/** 浮遊デコアイコン1点（外側が translate、内側の img が rotate。2つの transform を別要素に分ける）。
 *  親は position:relative（または fixed）であること。`eager` は初回描画で見せる場所（オープニング）用。 */
export function FloatDeco({ ill, eager = false, index }: { ill: DecoIll; eager?: boolean; index?: number }) {
  return (
    <span
      className={`lp-ill lp-ill--f${ill.float}${ill.hideSp ? " lp-ill--sp-off" : ""}`}
      style={
        {
          "--lp-ill-top": ill.top,
          "--lp-ill-left": ill.left,
          "--lp-ill-sp-top": ill.spTop ?? ill.top,
          "--lp-ill-sp-left": ill.spLeft ?? ill.left,
          "--lp-ill-w": `${ill.w}px`,
          ...(index !== undefined ? { "--lp-ill-i": index } : null),
        } as CSSProperties
      }
    >
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        className={`lp-ill__img lp-ill__img--s${ill.sway}`}
        src={ill.src}
        alt=""
        width={512}
        height={512}
        loading={eager ? "eager" : "lazy"}
        decoding="async"
      />
    </span>
  );
}
