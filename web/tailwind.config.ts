import type { Config } from "tailwindcss";

/**
 * ソクウリ / AssetWise デザインシステム — Tailwind トークン定義
 *
 * 方向性: 「信頼感・クリーン系」（フィンテック寄り）。
 * - 配色は真の青（trust blue）を基幹に、彩度を抑えた restraint な構成。
 * - 余白・角丸・影は段階を限定し、画面間で一貫したリズムを担保する。
 * - 個別画面でのアドホックな色指定を禁止し、本トークン経由で統一する。
 */
const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        /** 基幹ブランドカラー: 深く落ち着いた真の青（信頼感の主軸） */
        brand: {
          50: "#eef4ff",
          100: "#d9e6ff",
          200: "#bcd4ff",
          300: "#8eb6ff",
          400: "#598ffb",
          500: "#336bf2",
          600: "#1f54de", // primary action
          700: "#1c44b4", // hover
          800: "#1d3c92",
          900: "#1d3677", // 見出し / ダーク面
          950: "#141f48", // 最暗面（フッター・ヒーロー深部）
        },
        /** 補助カラー: 価値・成功・前向きシグナル（エメラルド） */
        accent: {
          50: "#ecfdf5",
          100: "#d1fae5",
          200: "#a7f3d0",
          300: "#6ee7b7",
          400: "#34d399",
          500: "#10b981",
          600: "#059669",
          700: "#047857",
        },
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Hiragino Kaku Gothic ProN",
          "Hiragino Sans",
          "Meiryo",
          "Yu Gothic UI",
          "Noto Sans JP",
          "Roboto",
          "Arial",
          "sans-serif",
        ],
      },
      boxShadow: {
        /** 段階を 4 つに限定し、要素の階層を明示する */
        xs: "0 1px 2px 0 rgb(20 31 72 / 0.06)",
        card: "0 1px 2px 0 rgb(20 31 72 / 0.04), 0 6px 18px -6px rgb(20 31 72 / 0.10)",
        "card-hover":
          "0 2px 4px 0 rgb(20 31 72 / 0.05), 0 14px 32px -10px rgb(20 31 72 / 0.18)",
        elevated:
          "0 10px 30px -8px rgb(20 31 72 / 0.18), 0 28px 56px -20px rgb(20 31 72 / 0.20)",
        cta: "0 10px 24px -8px rgb(31 84 222 / 0.45)",
      },
      borderRadius: {
        "4xl": "1.75rem",
      },
      maxWidth: {
        "container": "72rem",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(14px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        scan: {
          "0%": { transform: "translateY(-110%)" },
          "100%": { transform: "translateY(360%)" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.6s cubic-bezier(0.16, 1, 0.3, 1) both",
        "fade-in": "fade-in 0.5s ease both",
        scan: "scan 1.9s cubic-bezier(0.45, 0, 0.55, 1) infinite",
        shimmer: "shimmer 1.6s infinite",
      },
    },
  },
  plugins: [],
};

export default config;
