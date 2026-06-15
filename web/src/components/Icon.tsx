/**
 * 線画SVGアイコンの集約モジュール。
 *
 * デザインシステム上、絵文字アイコンは使用しない。アイコンは全てここに集約し、
 * 24x24 viewBox / stroke ベース / currentColor で統一する。
 * 色は親要素の text-* で制御する。
 */

import type { SVGProps } from "react";

/** 利用可能なアイコン名 */
export type IconName =
  // --- カテゴリ ---
  | "device"
  | "apparel"
  | "bag"
  | "gem"
  | "gamepad"
  | "music"
  | "book"
  | "sport"
  | "sofa"
  | "beauty"
  | "art"
  | "car"
  // --- 機能・手順 ---
  | "camera"
  | "scan"
  | "yen"
  | "scale"
  | "package"
  | "shield"
  | "bolt"
  // --- UI ---
  | "check"
  | "check-circle"
  | "close"
  | "plus"
  | "chevron-down"
  | "chevron-right"
  | "arrow-right"
  | "arrow-left"
  | "external"
  | "alert"
  | "info"
  | "trash"
  | "image"
  | "sparkle"
  | "lock";

/** 各アイコンの path 群（stroke 描画前提） */
const ICON_PATHS: Record<IconName, string[]> = {
  // --- カテゴリ ---
  device: ["M9 3h6a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z", "M10.5 18h3"],
  apparel: ["M8.5 4 6 6 4 9l2.6 2L8 9.8V20h8V9.8l1.4 1.2L20 9l-2-3-2.5-2", "M8.5 4a3.5 3.5 0 0 0 7 0"],
  bag: ["M6.2 8.5h11.6l1 11.5H5.2l1-11.5Z", "M9 8.5V7a3 3 0 0 1 6 0v1.5"],
  gem: ["M6 3.5h12l3 5.5-9 11.5L3 9l3-5.5Z", "M3 9h18", "M9.5 3.5 8 9l4 11.5L16 9l-1.5-5.5"],
  gamepad: [
    "M8 9h8a4.5 4.5 0 0 1 1 8.9c-1.4.3-2.3-.6-3.2-1.4l-.5-.5h-2.6l-.5.5c-.9.8-1.8 1.7-3.2 1.4A4.5 4.5 0 0 1 8 9Z",
    "M8.5 13h2.4M9.7 11.8v2.4",
    "M15 12.4h.01M16.6 14h.01",
  ],
  music: ["M9 17.5V6l10-2.2v11.5", "M6.5 17.5a2.5 2.5 0 1 0 5 0 2.5 2.5 0 0 0-5 0Z", "M16.5 15.3a2.5 2.5 0 1 0 5 0 2.5 2.5 0 0 0-5 0Z"],
  book: ["M6 4.5h11a2 2 0 0 1 2 2V20H8a2 2 0 0 1-2-2V4.5Z", "M6 18a2 2 0 0 1 2-2h11"],
  sport: ["M6 8.5v7M3.5 10.5v3M18 8.5v7M20.5 10.5v3", "M6 12h12"],
  sofa: [
    "M5 11.5V8a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v3.5",
    "M3 13.5a2 2 0 0 1 4 0V16h10v-2.5a2 2 0 0 1 4 0V19H3v-5.5Z",
    "M6.5 19v1.5M17.5 19v1.5",
  ],
  beauty: ["M12 3.2s6 5.8 6 10.3a6 6 0 0 1-12 0c0-4.5 6-10.3 6-10.3Z", "M9.5 14a2.5 2.5 0 0 0 2.5 2.5"],
  art: ["M4.5 5h15v14h-15Z", "M4.5 15.5 9.5 11l4 3.5L17 11l2.5 2.5", "M9 9.3a1.4 1.4 0 1 1-2.8 0 1.4 1.4 0 0 1 2.8 0Z"],
  car: [
    "M5 12.5 6.6 8a2 2 0 0 1 1.9-1.3h7a2 2 0 0 1 1.9 1.3L19 12.5",
    "M3.5 12.5h17v4.5a1 1 0 0 1-1 1H18M3.5 12.5v4.5a1 1 0 0 0 1 1H6",
    "M6 18a2 2 0 1 0 4 0 2 2 0 0 0-4 0ZM14 18a2 2 0 1 0 4 0 2 2 0 0 0-4 0Z",
  ],
  // --- 機能・手順 ---
  camera: [
    "M4 9.2a2 2 0 0 1 2-2h1.7l1-1.6a1 1 0 0 1 .85-.5h5.1a1 1 0 0 1 .85.5l1 1.6H18a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V9.2Z",
    "M12 16a3.3 3.3 0 1 0 0-6.6 3.3 3.3 0 0 0 0 6.6Z",
  ],
  scan: [
    "M5 8.5V6.5a1.5 1.5 0 0 1 1.5-1.5h2M15.5 5h2A1.5 1.5 0 0 1 19 6.5v2M19 15.5v2a1.5 1.5 0 0 1-1.5 1.5h-2M8.5 19h-2A1.5 1.5 0 0 1 5 17.5v-2",
    "M12 8.7l1.2 2.8 2.8 1-2.8 1.2L12 17l-1.2-2.8L8 13l2.8-1L12 8.7Z",
  ],
  yen: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z", "M8.6 8 12 12.4 15.4 8M12 12.4V17M9.4 13.4h5.2M9.4 15.5h5.2"],
  scale: [
    "M12 4.3V20M8.5 20h7",
    "M5 8h14M5 8l3-1.6M19 8l-3-1.6M12 4.3 8 6.4M12 4.3 16 6.4",
    "M2.5 13 5 8l2.5 5a2.5 2.5 0 0 1-5 0ZM16.5 13 19 8l2.5 5a2.5 2.5 0 0 1-5 0Z",
  ],
  package: ["M12 3 4 7.2v9.6L12 21l8-4.2V7.2L12 3Z", "M4 7.2 12 11.5l8-4.3M12 11.5V21", "M8 5.1l8 4.3"],
  shield: ["M12 3.2 5 6v5.2c0 4.8 2.9 7.8 7 9.6 4.1-1.8 7-4.8 7-9.6V6l-7-2.8Z", "M9 12l2 2 4-4.2"],
  bolt: ["M13 3 4.5 13.5H10l-1 7.5L19.5 10H14l-1-7Z"],
  // --- UI ---
  check: ["M5 12.5l4.2 4.2L19 7"],
  "check-circle": ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z", "M8.4 12.2l2.6 2.6 4.6-5"],
  close: ["M6 6l12 12M18 6 6 18"],
  plus: ["M12 5v14M5 12h14"],
  "chevron-down": ["M6 9.5l6 6 6-6"],
  "chevron-right": ["M9.5 6l6 6-6 6"],
  "arrow-right": ["M4.5 12h15M13 5.5l6.5 6.5L13 18.5"],
  "arrow-left": ["M19.5 12h-15M11 5.5 4.5 12 11 18.5"],
  external: ["M14 4.5h5.5V10", "M19.5 4.5 11 13", "M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"],
  alert: ["M12 4.2 2.7 20.3h18.6L12 4.2Z", "M12 10v4.3M12 17.6h.01"],
  info: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z", "M12 11v5.2M12 7.8h.01"],
  trash: ["M4.5 7h15M9.5 7V4.8h5V7M6.5 7l1 13h9l1-13", "M10.5 11v5.5M13.5 11v5.5"],
  image: ["M4.5 5h15v14h-15Z", "M4.5 16l5-5 4 4 3-3 3 3", "M9.2 9.5a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0Z"],
  sparkle: ["M12 3.5l1.9 5.1 5.1 1.9-5.1 1.9L12 17.5l-1.9-5.1L5 10.5l5.1-1.9L12 3.5Z"],
  lock: ["M6 11h12v9.5H6Z", "M9 11V8.2a3 3 0 0 1 6 0V11", "M12 14.5v2.5"],
};

interface IconProps extends Omit<SVGProps<SVGSVGElement>, "name"> {
  name: IconName;
  /** 線の太さ。既定 1.75（デザインシステム規定） */
  strokeWidth?: number;
}

/**
 * 線画アイコン。サイズ・色は className（h-* w-* text-*）で制御する。
 */
export function Icon({ name, strokeWidth = 1.75, className, ...rest }: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
      {...rest}
    >
      {ICON_PATHS[name].map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}

/**
 * 読み込み中スピナー。サイズ・色は className で制御する。
 */
export function Spinner({ className }: { className?: string }) {
  return (
    <svg
      className={`animate-spin ${className ?? ""}`}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle
        className="opacity-20"
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeWidth="3"
      />
      <path
        className="opacity-90"
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  );
}

/**
 * カタヅケのブランドマーク（ロゴアイコン）。
 * 角丸タイル + 白の上向きグリフで「撮る → 価値が上がる」を象徴する。
 */
export function BrandMark({ className }: { className?: string }) {
  return (
    <span
      className={`inline-flex items-center justify-center rounded-[10px] bg-gradient-to-br from-brand-500 to-brand-800 shadow-xs ${
        className ?? "h-9 w-9"
      }`}
    >
      <svg viewBox="0 0 24 24" fill="none" className="h-[60%] w-[60%]" aria-hidden="true">
        <path
          d="M12 17.5V8.2M7.8 12.4 12 8.2l4.2 4.2"
          stroke="#fff"
          strokeWidth="2.2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path d="M8 18.6h8" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" opacity="0.65" />
      </svg>
    </span>
  );
}
