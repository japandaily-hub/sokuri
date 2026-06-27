import type { SVGProps } from "react";

/**
 * カタヅケ デザインハンドオフの SVG アイコンスプライト。
 * デザイン（katazuke-main.css / 各HTML）が `<svg class="ic"><use href="#i-xxx"/></svg>`
 * を前提とするため、symbol 定義をそのまま移植し layout で一度だけ描画する。
 * 線画スタイル（stroke / 1.9px）は .ic クラス（katazuke.css）が付与する。
 */
export function KdzIconSprite() {
  return (
    <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true">
      <defs>
        <symbol id="i-camera" viewBox="0 0 24 24"><path d="M4 8h3l2-3h6l2 3h3v11H4z" /><circle cx="12" cy="13" r="3.6" /></symbol>
        <symbol id="i-arrow" viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6" /></symbol>
        <symbol id="i-check" viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7" /></symbol>
        <symbol id="i-x" viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18" /></symbol>
        <symbol id="i-spark" viewBox="0 0 24 24"><path d="M12 3l1.8 4.9L19 9.7l-4.9 1.8L12 16l-2.1-4.5L5 9.7l5.2-1.8z" /></symbol>
        <symbol id="i-trend" viewBox="0 0 24 24"><path d="M4 17l5-5 3 3 7-7" /><path d="M16 8h4v4" /></symbol>
        <symbol id="i-people" viewBox="0 0 24 24"><circle cx="9" cy="8" r="3.2" /><path d="M3.5 19c.8-3.4 4-5 5.5-5s4.7 1.6 5.5 5" /><path d="M16 6.2A3 3 0 0118 11.6M17.5 14c1.6.3 3.4 1.7 4 5" /></symbol>
        <symbol id="i-scan" viewBox="0 0 24 24"><path d="M4 8V5h3M20 8V5h-3M4 16v3h3M20 16v3h-3" /><path d="M4 12h16" /></symbol>
        <symbol id="i-scale" viewBox="0 0 24 24"><path d="M12 4v16M6 8h12" /><path d="M6 8l-3 6a3 3 0 006 0zM18 8l-3 6a3 3 0 006 0z" /><path d="M8 20h8" /></symbol>
        <symbol id="i-truck" viewBox="0 0 24 24"><path d="M3 6h11v9H3z" /><path d="M14 9h4l3 3v3h-7z" /><circle cx="7" cy="18" r="1.6" /><circle cx="17" cy="18" r="1.6" /></symbol>
        <symbol id="i-check-circle" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9" /><path d="M8 12l2.5 2.5L16 9" /></symbol>
        <symbol id="i-menu" viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16" /></symbol>
        <symbol id="i-shield" viewBox="0 0 24 24"><path d="M12 3l7 3v6c0 4.7-3 7.9-7 9-4-1.1-7-4.3-7-9V6z" /><path d="M9 12l2 2 4-4" /></symbol>
        <symbol id="i-bag" viewBox="0 0 24 24"><path d="M5 8h14l-1.4 11H6.4z" /><path d="M9 8a3 3 0 016 0" /></symbol>
        <symbol id="i-lock" viewBox="0 0 24 24"><rect x="5" y="10" width="14" height="10" rx="2" /><path d="M8 10V8a4 4 0 018 0v2" /></symbol>
        <symbol id="i-sun" viewBox="0 0 24 24"><circle cx="12" cy="12" r="4" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2" /></symbol>
        <symbol id="i-tag" viewBox="0 0 24 24"><path d="M4 4h7l9 9-7 7-9-9z" /><circle cx="8.5" cy="8.5" r="1.3" /></symbol>
        <symbol id="i-zoom" viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4.3-4.3M11 8.5v5M8.5 11h5" /></symbol>
        <symbol id="i-crop" viewBox="0 0 24 24"><path d="M6 2v14a2 2 0 002 2h14" /><path d="M2 6h14a2 2 0 012 2v14" /></symbol>
        <symbol id="i-chat" viewBox="0 0 24 24"><path d="M5 5h14a2 2 0 012 2v8a2 2 0 01-2 2H9l-4 4V7a2 2 0 012-2z" /><path d="M8 10h8M8 13h5" /></symbol>
        <symbol id="i-up" viewBox="0 0 24 24"><path d="M12 19V6M6 12l6-6 6 6" /></symbol>
        <symbol id="i-house" viewBox="0 0 24 24"><path d="M3.5 11.2L12 4l8.5 7.2" /><path d="M5.6 10v9.2h12.8V10" /></symbol>
        <symbol id="i-crown" viewBox="0 0 24 24"><path d="M4 8l3.5 3L12 5l4.5 6L20 8l-1.6 10H5.6z" /><path d="M5.6 18h12.8" /></symbol>
        <symbol id="i-phone" viewBox="0 0 24 24"><path d="M6 3h3l2 5-2.5 1.5a12 12 0 005 5L16 12l5 2v3a2 2 0 01-2 2A16 16 0 014 6a2 2 0 012-3z" /></symbol>
        <symbol id="i-clock" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8" /><path d="M12 8v4.5l3 2" /></symbol>
        <symbol id="i-pin" viewBox="0 0 24 24"><path d="M12 21s7-6.3 7-11a7 7 0 10-14 0c0 4.7 7 11 7 11z" /><circle cx="12" cy="10" r="2.5" /></symbol>
        <symbol id="i-sofa" viewBox="0 0 24 24"><path d="M4 11V8a2 2 0 012-2h12a2 2 0 012 2v3" /><path d="M3 12a2 2 0 012 2v3h14v-3a2 2 0 012-2 2 2 0 00-2-2 2 2 0 00-2 2v1H7v-1a2 2 0 00-2-2 2 2 0 00-2 2z" /><path d="M6 17v2M18 17v2" /></symbol>
        <symbol id="i-box" viewBox="0 0 24 24"><path d="M3 7.5L12 3l9 4.5v9L12 21l-9-4.5z" /><path d="M3 7.5L12 12l9-4.5M12 12v9" /></symbol>
        <symbol id="i-chev" viewBox="0 0 24 24"><path d="M6 9l6 6 6-6" /></symbol>
        <symbol id="i-yen" viewBox="0 0 24 24"><path d="M12 13v7M7 4l5 7 5-7M8 13h8M8 16.5h8" /></symbol>
      </defs>
    </svg>
  );
}

export type IcName =
  | "camera" | "arrow" | "check" | "x" | "spark" | "trend" | "people" | "scan"
  | "scale" | "truck" | "check-circle" | "menu" | "shield" | "bag" | "lock"
  | "sun" | "tag" | "zoom" | "crop" | "chat" | "up" | "house" | "crown"
  | "phone" | "clock" | "pin" | "sofa" | "box" | "chev" | "yen";

/** デザインの `<svg class="ic"><use href="#i-xxx"/></svg>` を React で再現する薄いヘルパー。 */
export function Ic({ name, className, ...rest }: { name: IcName } & SVGProps<SVGSVGElement>) {
  return (
    <svg className={`ic${className ? ` ${className}` : ""}`} aria-hidden="true" {...rest}>
      <use href={`#i-${name}`} />
    </svg>
  );
}
