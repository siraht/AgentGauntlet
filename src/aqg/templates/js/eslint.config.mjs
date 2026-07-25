import fs from "node:fs";
import js from "@eslint/js";
import globals from "globals";
import security from "eslint-plugin-security";
import tseslint from "typescript-eslint";

const project = JSON.parse(
  fs.readFileSync(new URL("../../../project.json", import.meta.url), "utf8"),
);
const profile = process.env.AQG_PROFILE || "pr";
const structure = {
  ...(project.thresholds?.structure || {}),
  ...(project.profile_thresholds?.[profile]?.structure || {}),
};
const ignores = [
  "**/node_modules/**",
  "**/.yarn/**",
  "**/.pnp.*",
  "**/.git/**",
  "**/.aqg/**",
  "**/quality/tools/**",
  "**/quality/_aqg/**",
  "**/dist/**",
  "**/build/**",
  "**/coverage/**",
  "**/.next/**",
  "**/.nuxt/**",
  "**/.svelte-kit/**",
  "**/playwright-report/**",
  "**/test-results/**",
  "**/*.min.js",
  "**/vendor/**",
];

export default tseslint.config(
  { ignores },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  security.configs.recommended,
  {
    files: ["**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: { ...globals.browser, ...globals.node, ...globals.es2024 },
    },
    linterOptions: { reportUnusedDisableDirectives: "error" },
    rules: {
      complexity: ["error", structure.max_cyclomatic_complexity ?? 10],
      "max-depth": ["error", structure.max_nesting_depth ?? 4],
      "max-lines-per-function": [
        "error",
        {
          max: structure.max_function_lines ?? 50,
          skipBlankLines: true,
          skipComments: true,
          IIFEs: true,
        },
      ],
      "max-params": ["error", 5],
      "no-warning-comments": [
        "warn",
        { terms: ["fixme", "hack"], location: "anywhere" },
      ],
      "no-constant-condition": ["error", { checkLoops: false }],
      "no-duplicate-imports": "error",
      "no-eval": "error",
      "no-implied-eval": "error",
      "no-new-func": "error",
      "security/detect-object-injection": "off",
      "no-promise-executor-return": "error",
      "no-self-compare": "error",
      "no-template-curly-in-string": "error",
      "no-unmodified-loop-condition": "error",
      "no-unreachable-loop": "error",
      "no-unused-private-class-members": "error",
      "prefer-const": "error",
      "require-atomic-updates": "error",
    },
  },
  {
    files: [
      "**/*.{test,spec}.{js,jsx,mjs,cjs,ts,tsx,mts,cts}",
      "**/{test,tests,spec,specs,__tests__,e2e}/**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}",
    ],
    languageOptions: {
      globals: { ...globals.vitest },
    },
    rules: {
      "max-lines-per-function": [
        "error",
        {
          max: Math.max(90, structure.max_function_lines ?? 50),
          skipBlankLines: true,
          skipComments: true,
        },
      ],
      "security/detect-object-injection": "off",
    },
  },
  {
    files: [
      "**/*.config.{js,mjs,cjs,ts,mts,cts}",
      "**/src/aqg/templates/**/*.{js,mjs,cjs,ts,mts,cts}",
    ],
    rules: {
      "security/detect-non-literal-fs-filename": "off",
      "security/detect-object-injection": "off",
    },
  },
);
