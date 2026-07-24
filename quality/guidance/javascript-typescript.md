# JavaScript and TypeScript quality

> Use strict runtime-independent types, explicit coverage scope, structural limits, deterministic Vitest tests, Playwright for user behavior, and Stryker for assertion quality.

## TypeScript

New code should pass `strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`, `useUnknownInCatchVariables`, and `noImplicitOverride` unless a narrow documented interoperability constraint prevents one. Validate untrusted runtime input; types disappear at runtime. Prefer discriminated unions and exhaustive `never` checks for state machines. Avoid `any`, non-null assertions, unchecked casts, `@ts-ignore`, and declaration merging that obscures ownership.

## JavaScript

Use JSDoc/types or TypeScript at public boundaries where practical. Validate external input, avoid implicit coercion, distinguish absent/null/undefined, and make promise rejection explicit. Do not use dynamic `eval`/Function, string-built HTML, or shell commands with untrusted input.

## Unit and coverage

Vitest configuration must define `coverage.include`; otherwise only imported files are reported and untouched production files disappear from the denominator. Clean coverage before each authoritative run. Run in deterministic shuffled order with a recorded seed. Use fake timers only through explicit clock control and always restore them.

## Structural constraints

Enforce cyclomatic complexity, function length, nesting depth, parameter count, and import cycles. A tiny wrapper chain does not solve complexity; review coupling and responsibility. Generated/minified code is excluded by path, never by inline suppressions.

## Browser and accessibility

Use Playwright role/label/text locators, web-first assertions, isolated contexts, traces on first retry, and no arbitrary sleeps. Run axe for automatically detectable violations and a manual WCAG-oriented QA procedure for keyboard, focus, zoom/reflow, names, errors, and cognitive behavior.

## Mutation

Stryker runs with explicit changed-file scope and incremental reuse disabled for authoritative evidence. Count `NoCoverage` as undetected. Inspect survivors in typed branches, optional-value handling, error paths, and async timing.
