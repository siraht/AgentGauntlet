# HTML and CSS quality

> Treat semantic structure, accessible names, responsive behavior, cascade complexity, and visual stability as testable product contracts rather than formatting concerns.

## HTML

Use valid document structure, correct language, meaningful landmarks/headings, native elements before ARIA, associated labels, button/link semantics, table headers, safe form autocomplete, and explicit image alternatives. Static validation catches syntax and many structural defects; browser accessibility and manual tests cover computed semantics and interaction.

Do not use clickable `div`/`span` when a button or link fits, duplicate IDs, positive tabindex, inaccessible custom controls, placeholder-only labels, invalid nesting, or hidden content that remains focusable. Runtime-rendered HTML must be included in browser tests because source-file validation cannot see it.

## CSS

Enforce bounded nesting and selector complexity. Prefer component or utility boundaries with predictable cascade layers. Avoid IDs and escalating specificity, unscoped global selectors, `!important` except a documented layer policy, fixed dimensions that break text zoom, focus removal, motion without reduced-motion alternatives, and color as the only information channel.

## Responsive and visual checks

Test canonical small, medium, and large viewports, plus 200–400% zoom/reflow for important pages. Assert no horizontal scrolling where WCAG requires reflow, no obscured focus, usable target sizes, and stable content order. Use screenshot diffs only for intentionally visual invariants and keep thresholds narrow; functional and accessibility assertions remain primary.

## Performance

Budget CSS/JS/image bytes and core user-journey metrics. Lighthouse is diagnostic and can vary, so use controlled environments, repeated samples where thresholds are close, and direct resource budgets. A score alone is not a performance contract.
