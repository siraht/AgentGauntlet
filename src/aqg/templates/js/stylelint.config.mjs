import fs from 'node:fs';

const project = JSON.parse(fs.readFileSync(new URL('../../../project.json', import.meta.url), 'utf8'));
const profile = process.env.AQG_PROFILE || 'pr';
const structure = {
  ...(project.thresholds?.structure || {}),
  ...(project.profile_thresholds?.[profile]?.structure || {}),
};

export default {
  extends: ['stylelint-config-standard'],
  ignoreFiles: ['**/node_modules/**', '**/.aqg/**', '**/quality/tools/**', '**/dist/**', '**/build/**', '**/*.min.css', '**/vendor/**'],
  linterOptions: {
    reportNeedlessDisables: true,
    reportInvalidScopeDisables: true,
  },
  rules: {
    'max-nesting-depth': Math.min(3, structure.max_nesting_depth ?? 3),
    'declaration-block-no-duplicate-properties': true,
    'selector-max-id': 0,
    'selector-max-compound-selectors': 5,
    'selector-max-specificity': '0,4,0',
  },
};
