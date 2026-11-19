"use client";

import { useSyncExternalStore } from "react";

/** 認証画面の左カラムが並ぶ幅（katazuke-pages.css の min-width:860px と同じ）。 */
const DESKTOP_QUERY = "(min-width: 860px)";

function subscribe(onChange: () => void): () => void {
  const mql = window.matchMedia(DESKTOP_QUERY);
  mql.addEventListener("change", onChange);
  return () => mql.removeEventListener("change", onChange);
}

const getSnapshot = (): boolean => window.matchMedia(DESKTOP_QUERY).matches;
/** SSR・ハイドレーション時は描かない（スマホで画像を要求しないため）。PC では直後に描かれる。 */
const getServerSnapshot = (): boolean => false;

/**
 * 認証画面（/login・/signup・/operator/login・/operator/signup）の左カラムの写真。
 * 左カラムはスマホ幅では出さない（CSS で .auth-side を非表示）ので、画像の取得自体を行わないよう
 * PC 幅のときだけ <img> を描く。装飾のため alt は空。
 */
export function AuthSidePhoto({ src, width, height }: { src: string; width: number; height: number }) {
  const isDesktop = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  if (!isDesktop) return null;
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={src} width={width} height={height} alt="" loading="lazy" decoding="async" />;
}
