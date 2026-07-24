import fs from 'node:fs';

const project = JSON.parse(fs.readFileSync(new URL('../../../project.json', import.meta.url), 'utf8'));
const runner = project.javascript?.test_runner === 'jest' ? 'jest' : 'vitest';
const sourceRoots = project.paths?.source || ['src'];
const mutate = sourceRoots.flatMap((root) => [
  `${root}/**/!(*.+(s|S)pec|*.+(t|T)est).+(cjs|mjs|js|ts|mts|cts|jsx|tsx)`,
  `!${root}/**/*.d.ts`,
]);

export default {
  testRunner: runner,
  mutate,
  reporters: ['clear-text', 'progress', 'json', 'html'],
  jsonReporter: { fileName: '.aqg/work/mutation/stryker.json' },
  htmlReporter: { fileName: '.aqg/work/mutation/stryker.html' },
  incremental: true,
  incrementalFile: '.aqg/cache/stryker.json',
  tempDirName: '.aqg/work/stryker-tmp',
  thresholds: { high: 85, low: 70, break: 70 },
  timeoutMS: 10000,
  timeoutFactor: 2.5,
  concurrency: Math.max(1, Math.min(4, Number(process.env.AQG_MUTATION_WORKERS || 2))),
  checkers: project.stacks?.typescript && fs.existsSync('tsconfig.json') ? ['typescript'] : [],
  tsconfigFile: fs.existsSync('tsconfig.json') ? 'tsconfig.json' : 'quality/config/js/tsconfig.aqg.json',
  coverageAnalysis: 'perTest',
  allowEmpty: false,
  ignorePatterns: ['.aqg', 'quality/tools', 'dist', 'build', 'coverage', 'playwright-report', 'test-results']
};
