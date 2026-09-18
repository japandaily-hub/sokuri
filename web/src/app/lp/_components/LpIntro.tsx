"use client";

import { useEffect, useState } from "react";
import { KdzLogo } from "@/components/kdz/Logo";

/** ページを開いた直後のオープニング。白地に「カタヅケ」がやわらかく浮かび上がり、本編へ溶ける。
 *  - 動きは CSS の @keyframes だけで完結させる（JS 無効でも約 2.6 秒で自動的に消える）。
 *  - prefers-reduced-motion では lp.css 側で display:none（そもそも出さない）。
 *  - 待たされたくない人のために、タップ／キー操作で即スキップできる。
 *  - 表示中も本編は下で読み込み・描画されているので、LCP を遅らせない。 */
const SKIP_KEYS = new Set(["Enter", " ", "Escape"]);

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
      <div className="lp-intro__mark">
        <KdzLogo size={44} />
      </div>
    </div>
  );
}
