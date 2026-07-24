# Web UI testing with Playwright

> Test user-visible behavior through resilient accessibility-facing locators, isolated browser state, web-first assertions, and trace-backed failures; keep visual and accessibility judgment explicit.

## Scenario selection

Cover a few complete high-value journeys: first-use/empty state, primary success, validation failure, authorization boundary, retry/dependency failure, persistence after reload, and recovery. Unit/component tests cover combinatorial logic; browser tests prove wiring and user interaction.

## Locators

Prefer `getByRole` with accessible name, then label, text, placeholder, alt text, or an explicit test ID contract. CSS/XPath and `.nth()` are last resorts because they bind to DOM structure and can act on the wrong element. Locator strictness is useful: ambiguous matches should fail.

## Waiting and assertions

Use Playwright actions and web-first `expect` assertions, which auto-wait for actionable state. Never use fixed sleeps. Wait for an observable user state or a controlled network/event boundary. Verify final content, URL/state, persistent side effect, and absence of duplicate/forbidden action where relevant.

## Isolation

Each test receives a fresh browser context and its own account/data namespace. Seed through APIs or fixtures, not through another test. Clean up via API or disposable environment. Parallel tests must have unique records and ports.

## Debug evidence

Retain trace on first retry, screenshot only on failure or visual requirement, console errors, failed network requests, and server correlation IDs. A retry that passes still marks the test flaky and requires repair.

## Accessibility and responsive behavior

Run axe after the UI reaches the tested state. Add manual keyboard-only operation, visible focus, focus order/return, 200–400% zoom/reflow, reduced motion, high contrast/forced colors where supported, error association, target size, and screen-reader spot checks for critical journeys. Automated scans cannot establish full WCAG conformance.

## Anti-patterns

Avoid page-object methods that hide assertions and state, test flows that share one logged-in page, broad route mocking that bypasses integration, assertions on implementation classes, screenshot-only functional tests, and selectors copied from rendered framework internals.
