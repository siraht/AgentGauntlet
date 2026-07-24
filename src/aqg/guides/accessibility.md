# Accessibility verification

> Target WCAG 2.2 AA for web product behavior, combine automated, semi-automated, and manual methods, and write each procedure with explicit applicability and outcome rules.

## Automated layer

Run semantic HTML validation and axe scans on each important UI state, not only the home page. Fail new applicable violations. Narrow existing exceptions by rule and element with owner and expiry; never exclude a large container to hide descendants. Automated passes mean only that no automatically detectable violation was found.

## Manual keyboard procedure

Using only keyboard input, reach and operate every interactive element in the journey. Verify logical focus order, visible focus, no keyboard trap, focus is not obscured, dialogs receive and return focus, shortcuts do not conflict, and drag-only actions have an alternative. Record browser/OS and exact state.

## Visual and reflow procedure

At 200% and 400% zoom or the equivalent responsive viewport, verify text and controls remain readable and operable, required content does not overlap or disappear, and two-dimensional scrolling is not introduced except for content that inherently requires it. Check text spacing overrides, contrast, non-color cues, reduced motion, and high contrast/forced colors where relevant.

## Names, roles, states, and errors

Spot-check the accessibility tree or a screen reader for critical controls. Names must match visible purpose; roles/states update correctly; form instructions and errors are programmatically associated; status messages are announced without stealing focus; authentication works with password managers and copy/paste where applicable.

## Procedure format

Follow ACT-style fields: rule identifier, accessibility requirement, applicability, assumptions, test input, step-by-step procedure, passed/failed/inapplicable outcomes, and test cases. Record where human judgment is required. Full-page WCAG conformance cannot be established by excluding failing portions.

## Inclusive validation

For high-impact products, add assessment by accessibility specialists and representative disabled users. Automated and checklist testing cannot cover every disability, assistive technology combination, or cognitive barrier.
