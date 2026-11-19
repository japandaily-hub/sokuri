"use client";

import { useSyncExternalStore } from "react";

/** 認証画面の左カラムが並ぶ幅（katazuke-pages.css の min-width:860px と同じ）。 */
const DESKTOP_QUERY = "(min-width: 860px)";

/** addEventListener を持たない古い Safari（14 未満）は addListener/removeListener にフォールバックする。 */
function subscribe(onChange: () => void): () => void {
  const mql = window.matchMedia(DESKTOP_QUERY);
  if (typeof mql.addEventListener === "function") {
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }
  mql.addListener(onChange);
  return () => mql.removeListener(onChange);
}

const getSnapshot = (): boolean => window.matchMedia(DESKTOP_QUERY).matches;
/** SSR・ハイドレーション時は <img> を描かない（スマホで画像を要求しないため）。PC では直後に描かれる。 */
const getServerSnapshot = (): boolean => false;

/**
 * 認証画面（/login・/signup・/operator/login・/operator/signup）の左カラムの写真。
 * 左カラムはスマホ幅では出さない（CSS で .auth-side を非表示）ので、画像の取得自体を行わないよう
 * PC 幅のときだけ <img> を描く。枠（.auth-side__photo）は常に描いて高さ（flex:1）を先に確保するため、
 * PC で画像が後から出ても見出し文・注記の位置はずれない。装飾のため alt は空。
 */
export function AuthSidePhoto({ src, width, height }: { src: string; width: number; height: number }) {
  const isDesktop = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  return (
    <div className="auth-side__photo">
      {isDesktop ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={src} width={width} height={height} alt="" loading="eager" decoding="async" />
      ) : null}
    </div>
  );
}
