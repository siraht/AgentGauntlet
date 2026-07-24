# Research and standards basis

> AQG uses current final standards as baselines, official tool behavior for adapter design, and draft material only as labeled forward-looking guidance.

## Secure development and supply chain

- NIST SP 800-218, **Secure Software Development Framework (SSDF) Version 1.1**, final: https://csrc.nist.gov/pubs/sp/800/218/final
- NIST SP 800-218 Rev. 1, **SSDF Version 1.2**, initial public draft as of July 2026: https://csrc.nist.gov/pubs/sp/800/218/r1/ipd
- NIST SP 800-218A, secure development profile for generative AI and dual-use foundation models: https://csrc.nist.gov/pubs/sp/800/218/a/final
- OWASP **Application Security Verification Standard 5.0.0**: https://owasp.org/www-project-application-security-verification-standard/
- SLSA **Version 1.2** Source and Build tracks: https://slsa.dev/spec/v1.2/

## Accessibility and QA method structure

- W3C **WCAG 2.2** Recommendation: https://www.w3.org/TR/WCAG22/
- W3C **Accessibility Conformance Testing Rules Format 1.1** Recommendation: https://www.w3.org/TR/act-rules-format/

AQG borrows ACT’s explicit rule identity, applicability, assumptions, input, procedure, and outcome model for manual/semi-automated QA. Automated accessibility evidence is deliberately incomplete; WCAG requires human evaluation for criteria automation cannot decide.

## Official tool guidance

- Playwright best practices and locators: https://playwright.dev/docs/best-practices and https://playwright.dev/docs/locators
- Playwright accessibility testing: https://playwright.dev/docs/accessibility-testing
- Vitest coverage scope: https://vitest.dev/guide/coverage.html
- Stryker mutation concepts/config/incremental limitations: https://stryker-mutator.io/docs/
- mutmut documentation: https://mutmut.readthedocs.io/
- pytest integration and flaky-test guidance: https://docs.pytest.org/en/stable/explanation/goodpractices.html and https://docs.pytest.org/en/stable/explanation/flaky.html
- Hypothesis guidance: https://hypothesis.readthedocs.io/
- mypy strict and legacy adoption guidance: https://mypy.readthedocs.io/en/stable/existing_code.html
- TypeScript strict options: https://www.typescriptlang.org/tsconfig/
- ESLint structural rules: https://eslint.org/docs/latest/rules/
- Stylelint rules: https://stylelint.io/user-guide/rules/

## Interpretation rules

A standard states requirements or a control vocabulary; it does not choose the correct project risk, tests, or thresholds automatically. Tool documentation describes mechanics, not proof of product correctness. AQG converts those sources into fail-closed operational defaults, independent evidence layers, and review prompts. Projects must add domain, regulatory, platform, and incident-history requirements.
