"use client";

import { useEffect, useState } from "react";
import { KdzLogo } from "@/components/kdz/Logo";
import { D, FloatDeco, type DecoIll } from "./FloatDeco";

/** ページを開いた直後のオープニング。白地に「カタヅケ」がゆっくり浮かび上がり、本編へ溶ける。
 *  - 動きは CSS の @keyframes だけで完結させる（JS 無効でも約 4.8 秒で自動的に消える）。
 *  - prefers-reduced-motion では lp.css 側で display:none（そもそも出さない）。
 *  - 待たされたくない人のために、タップ／キー操作で即スキップできる。
 *  - 表示中も本編は下で読み込み・描画されているので、LCP を遅らせない。
 *  2026-09-18 ユーザー指示: 浮かび上がりをもっとゆっくりに。背景には FEE 区画と同じ手描きアイコンを
 *  ワードマークを囲むように散らし、3 本の曲線（水・新緑・星）が右からなびいて入り、KV 上部の同じ曲線
 *  （lp-ribbon--kv）へ繋がる。 */
const SKIP_KEYS = new Set(["Enter", " ", "Escape"]);

/* ワードマーク（中央・幅 175〜220px・高さ約 90px）を避け、FEE 区画の散らしと同じ 8 点を周囲に。
   % はビューポート基準。SP は中央の文字塊が横 22〜78% を占めるので左右へ寄せる。 */
const INTRO_DECO: DecoIll[] = [
  { src: D.box, top: "18%", left: "14%", w: 84, sway: 1, float: 1, spTop: "16%", spLeft: "16%" },
  { src: D.lamp, top: "12%", left: "52%", w: 72, sway: 1, float: 2, spTop: "10%", spLeft: "56%" },
  { src: D.clock, top: "22%", left: "84%", w: 76, sway: 2, float: 3, spTop: "26%", spLeft: "84%" },
  { src: D.gift, top: "42%", left: "26%", w: 66, sway: 1, float: 2, spTop: "36%", spLeft: "14%" },
  { src: D.plant, top: "48%", left: "74%", w: 84, sway: 2, float: 1, spTop: "54%", spLeft: "86%" },
  { src: D.camera, top: "66%", left: "12%", w: 90, sway: 2, float: 3, spTop: "68%", spLeft: "16%" },
  { src: D.tote, top: "80%", left: "44%", w: 80, sway: 1, float: 1, spTop: "84%", spLeft: "42%" },
  { src: D.teacup, top: "72%", left: "86%", w: 80, sway: 2, float: 2, spTop: "78%", spLeft: "82%" },
];

/* 右→左（LpRibbon の variant b と同じ形）。右端から描き始めるので「右からなびいて入る」動きになる */
const INTRO_CURVES = [
  "M 1160 400 C 940 330, 720 330, 540 230 S 280 90, 220 10",
  "M 980 520 C 740 440, 560 340, 390 240 S 240 140, 190 100",
  "M 1140 600 C 900 530, 640 410, 440 310 S 260 190, 180 160",
];

export function LpIntro({ oncePerSession = false }: { oncePerSession?: boolean }) {
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (oncePerSession) {
      try {
        if (sessionStorage.getItem("lp-intro-seen")) {
          setDone(true);
          return;
        }
        sessionStorage.setItem("lp-intro-seen", "1");
      } catch {
        /* storage が使えない環境では毎回表示する */
      }
    }
    const onKey = (e: KeyboardEvent) => {
      if (SKIP_KEYS.has(e.key)) setDone(true);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [oncePerSession]);

  if (done) return null;
  return (
    <div
      className="lp-intro"
      aria-hidden="true"
      onClick={() => setDone(true)}
      onAnimationEnd={(e) => {
        if (e.animationName === "lp-intro-out") setDone(true);
      }}
    >
      <div className="lp-intro__glow" />
      <div className="lp-intro__ribbon">
        <svg viewBox="0 0 1200 620" fill="none" xmlns="http://www.w3.org/2000/svg" focusable="false">
          {INTRO_CURVES.map((d, i) => (
            <path key={i} d={d} pathLength={1} className={`lp-intro__line lp-intro__line--${i + 1}`} />
          ))}
        </svg>
      </div>
      <div className="lp-intro__deco">
        {INTRO_DECO.map((ill, i) => (
          <FloatDeco key={ill.src} ill={ill} index={i} eager />
        ))}
      </div>
      <div className="lp-intro__mark">
        <KdzLogo size={44} />
      </div>
    </div>
  );
}
