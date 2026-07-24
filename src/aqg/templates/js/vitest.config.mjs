import fs from 'node:fs';
import { defineConfig } from 'vitest/config';

const project = JSON.parse(fs.readFileSync(new URL('../../../project.json', import.meta.url), 'utf8'));
const profile = process.env.AQG_PROFILE || 'pr';
const merge = (base, override = {}) => Object.fromEntries(
  Array.from(new Set([...Object.keys(base || {}), ...Object.keys(override || {})])).map((key) => [
    key,
    base?.[key] && override?.[key] && typeof base[key] === 'object' && typeof override[key] === 'object'
      ? merge(base[key], override[key])
      : (override?.[key] ?? base?.[key]),
  ]),
);
const thresholds = merge(project.thresholds || {}, project.profile_thresholds?.[profile] || {});
const sourceRoots = project.paths?.source?.length ? project.paths.source : ['src'];
const coverageInclude = sourceRoots.flatMap((root) => {
  const prefix = root === '.' ? '' : `${root.replace(/\/$/, '')}/`;
  return [`${prefix}**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}`];
});

export default defineConfig({
  test: {
    root: process.cwd(),
    include: [
      '**/*.{test,spec}.{js,jsx,mjs,cjs,ts,tsx,mts,cts}',
      '**/{test,tests,spec,specs,__tests__}/**/*.{js,jsx,mjs,cjs,ts,tsx,mts,cts}',
    ],
    exclude: ['**/node_modules/**', '**/.aqg/**', '**/quality/tools/**', '**/dist/**', '**/build/**', '**/e2e/**'],
    allowOnly: false,
    passWithNoTests: false,
    restoreMocks: true,
    unstubEnvs: true,
    unstubGlobals: true,
    sequence: { shuffle: true, seed: 14717 },
    testTimeout: 10000,
    hookTimeout: 10000,
    coverage: {
      provider: 'v8',
      include: coverageInclude,
      reporter: ['text', 'json', 'json-summary', 'html'],
      reportsDirectory: '.aqg/work/coverage/js',
      clean: true,
      cleanOnRerun: true,
      exclude: [
        '**/*.{test,spec}.*', '**/{test,tests,spec,specs,__tests__,e2e}/**',
        '**/node_modules/**', '**/.aqg/**', '**/quality/**', '**/dist/**', '**/build/**',
        '**/*.config.*', '**/*.d.ts',
      ],
      thresholds: {
        lines: thresholds.coverage?.lines ?? 85,
        functions: thresholds.coverage?.functions ?? 80,
        statements: thresholds.coverage?.statements ?? 85,
        branches: thresholds.coverage?.branches ?? 75,
      },
    },
  },
});
