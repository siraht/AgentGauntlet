import tseslint from "typescript-eslint";
import aqgAbc from "./aqg-abc-plugin.mjs";

const files = ["**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}"];
const typescriptFiles = ["**/*.{ts,tsx,mts,cts}"];
const ignores = [
  "**/node_modules/**",
  "**/.yarn/**",
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
  "**/*.min.js",
  "**/vendor/**",
];

export default tseslint.config(
  { ignores },
  {
    files,
    plugins: { "aqg-abc": aqgAbc },
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    rules: { "aqg-abc/report": "warn" },
  },
  {
    files: typescriptFiles,
    languageOptions: {
      parser: tseslint.parser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
  },
);
