"use client";

/**
 * /lp キービジュアルのスライダー（参照LP `.home-kv__slider.-slow` の移植）。
 *
 * 参照の実測値（.agent-state/lp-habataki/reference-spec.md (b)）をそのまま踏襲する:
 * - 自動送り間隔 6000ms / 切替 1600ms（`--transition-slider-slow`）
 * - ドットは縦並び（PC は写真の右端・SP は写真の下）。参照は `dots:true` の丸ドット。
 *
 * a11y の実装は `components/kdz/interactions.tsx` の HeroCarousel をそのまま手本にしている:
 * - 自動再生には一時停止ボタンを必ず添える（WCAG 2.2.2 Pause, Stop, Hide）
 * - `document.hidden`・ホバー中・フォーカス中は自動送りを止める
 * - `prefers-reduced-motion: reduce` では自動送りしない（ドットでの手動切替は有効）
 * - 1枚目は React の初期状態で `is-active`＝無 JS でも 1 枚は必ず見える
 *
 * 画像は KV の情調を担う装飾（品目や人物を特定して読ませる意図がない）ため alt="" にし、
 * 切替の意味はドットの aria-label が持つ。
 */

import { useEffect, useRef, useState } from "react";
import { Ic } from "@/components/kdz/Icons";

export type LpSlide = {
  /** key と id 用の識別子（ファイル名と一致させる） */
  id: string;
  /** 画像パス（1536x1024）。省略時は /img/v2/<id>.webp */
  src?: string;
  /** 意味のある alt。装飾扱いなら省略（alt=""） */
  alt?: string;
};

export function LpSlider({
  slides,
  intervalMs = 6000,
}: {
  slides: LpSlide[];
  intervalMs?: number;
}) {
  const [current, setCurrent] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [reducedMotion, setReducedMotion] = useState(false);
  const pausedRef = useRef(false);

  useEffect(() => {
    if (!("matchMedia" in window)) return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReducedMotion(mq.matches);
    const onChange = () => setReducedMotion(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    if (!playing || reducedMotion || slides.length < 2) return;
    const id = window.setInterval(() => {
      if (pausedRef.current || document.hidden) return;
      setCurrent((i) => (i + 1) % slides.length);
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [playing, reducedMotion, slides.length, intervalMs]);

  if (slides.length === 0) return null;
  const pause = () => {
    pausedRef.current = true;
  };
  const resume = () => {
    pausedRef.current = false;
  };

  return (
    /* r2 A-3: 参照どおり KV 全面のフルブリード写真にする（`.lp-slider` を `.lp-kv` いっぱいに敷く）。
       ドット列は `.lp-kv` を基準にビューポート右端 24px へ絶対配置する（位置指定は lp.css 側）。 */
    <>
      <div className="lp-slider" onMouseEnter={pause} onMouseLeave={resume}>
        <div className="lp-slider__frame img-frame">
          {slides.map((s, i) => (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              key={s.id}
              id={`lp-slide-${s.id}`}
              src={s.src ?? `/img/v2/${s.id}.webp`}
              width={1536}
              height={1024}
              alt={s.alt ?? ""}
              aria-hidden={i === current ? undefined : true}
              className={`lp-slider__slide${i === current ? " is-active" : ""}`}
              loading={i === 0 ? "eager" : "lazy"}
              fetchPriority={i === 0 ? "high" : "auto"}
              decoding="async"
            />
          ))}
        </div>
      </div>
      {slides.length > 1 && (
        /* qa r2 L-2: ドット列の上にポインタがある間も自動送りを止める（写真枠と同じ扱い） */
        <div
          className="lp-slider__ctrl"
          onFocus={pause}
          onBlur={resume}
          onMouseEnter={pause}
          onMouseLeave={resume}
        >
          <div className="lp-slider__dots" role="tablist" aria-label="キービジュアルの写真を切り替える">
            {slides.map((s, i) => (
              <button
                key={s.id}
                type="button"
                role="tab"
                aria-selected={i === current}
                aria-controls={`lp-slide-${s.id}`}
                aria-label={`${i + 1}枚目の写真を表示`}
                className={`lp-slider__dot${i === current ? " is-active" : ""}`}
                onClick={() => setCurrent(i)}
              />
            ))}
          </div>
          {!reducedMotion && (
            <button
              type="button"
              className="lp-slider__toggle"
              aria-pressed={!playing}
              aria-label={playing ? "写真の自動切り替えを一時停止" : "写真の自動切り替えを再開"}
              onClick={() => setPlaying((p) => !p)}
            >
              <Ic name={playing ? "pause" : "play"} />
            </button>
          )}
        </div>
      )}
    </>
  );
}
