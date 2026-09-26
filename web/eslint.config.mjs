import { FlatCompat } from "@eslint/eslintrc";
import { dirname } from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const compat = new FlatCompat({
  baseDirectory: __dirname,
});

const eslintConfig = [
  {
    // next-env.d.ts は `next dev`/`next build` が自動生成するファイルで、
    // Next.js 公式が三重スラッシュ参照を前提に生成するため lint 対象から除外する。
    ignores: ["_archive/**", ".next/**", "node_modules/**", "next-env.d.ts"],
  },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  // E2E は e2e/helpers/test.ts の test / expect と newE2EContext() を使う。next dev の開発用
  // オーバーレイを消す fixture を迂回すると、375px 幅で左下のボタンのクリックが奪われる
  // （理由の詳細は docs/ops/e2e.md の設計方針）。慣習ではなく lint で守る（CI も e2e を lint する）。
  {
    // spec の test / expect は helpers/test 経由（context fixture の上書きを効かせるため）。
    // helpers は expect を直接使ってよい（helpers/ui.ts）ので spec に限る。
    // 接続先の検査（helpers/local-target.ts）を迂回させないため、spec では @playwright/test の request を
    // import せず（API は helpers/api.ts の Api＝作るたびに E2E_API_URL を検査）、baseURL は
    // playwright.config.ts（読み込み時に検査）だけで決める。test.use・test.extend・newE2EContext の
    // options などで baseURL を書くと、page を使わないテストでは検査が走らないため、spec 内の
    // オブジェクトの baseURL キーは書き方を問わず禁止する（分割代入の `({ baseURL })` は対象外）。
    files: ["e2e/**/*.spec.ts"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "@playwright/test",
              // default export も base の test なので、既定の import で迂回されないよう含める。
              importNames: ["test", "expect", "default"],
              message: "./helpers/test から import してください（docs/ops/e2e.md の設計方針）。",
            },
            {
              name: "@playwright/test",
              importNames: ["request"],
              message: "API は ./helpers/api の Api から呼んでください（接続先を検査するため。docs/ops/e2e.md の設計方針）。",
            },
          ],
        },
      ],
      "no-restricted-syntax": [
        "error",
        {
          selector: "ObjectExpression > Property[key.name='baseURL'], ObjectExpression > Property[key.value='baseURL']",
          message:
            "baseURL は playwright.config.ts（E2E_BASE_URL）だけで決めてください（接続先の検査を迂回しないため。docs/ops/e2e.md の設計方針）。",
        },
      ],
    },
  },
  {
    // ブラウザコンテキストの直接生成は helpers も含めて禁止（生成してよいのは helpers/test.ts だけ）。
    files: ["e2e/**/*.ts"],
    ignores: ["e2e/helpers/test.ts"],
    rules: {
      "no-restricted-properties": [
        "error",
        {
          object: "browser",
          property: "newContext",
          message: "newE2EContext(browser)（e2e/helpers/test.ts）を使ってください。",
        },
        {
          object: "browser",
          property: "newPage",
          message: "newE2EContext(browser) で作ったコンテキストから newPage してください。",
        },
      ],
    },
  },
];

export default eslintConfig;
