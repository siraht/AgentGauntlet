# Strict-mode readiness

Revision: `ba03a206c954928667d3015b58e62b5569f32b57` · mode: **adopt** · strict ready: **no**

## Current evidence

- Tests: 62
- Line coverage: 57.43% (gap 27.57 points)
- Branch coverage: 42.62% (gap 32.38 points)
- Functions above complexity cap: 52

## Lowest coverage modules

| Module | Lines | Branches | Missing statements |
|---|---:|---:|---:|
| `src/aqg/__main__.py` | 0.00% | 100.00% | 2 |
| `src/aqg/acceptance.py` | 17.24% | 0.00% | 96 |
| `src/aqg/wizard.py` | 19.12% | 0.00% | 55 |
| `src/aqg/adapters.py` | 22.00% | 13.28% | 702 |
| `src/aqg/portfolio.py` | 22.73% | 0.00% | 51 |
| `src/aqg/authoring.py` | 25.64% | 0.00% | 29 |
| `src/aqg/reporting.py` | 27.12% | 4.17% | 43 |
| `src/aqg/runner.py` | 46.32% | 17.39% | 73 |
| `src/aqg/sbom.py` | 48.17% | 35.00% | 241 |
| `src/aqg/dashboard.py` | 51.61% | 32.14% | 105 |
| `src/aqg/tui.py` | 62.25% | 28.95% | 57 |
| `src/aqg/doctor.py` | 62.93% | 37.50% | 86 |

## Highest complexity functions

| Function | Complexity | Rank |
|---|---:|:---:|
| `src/aqg/review.py:188::analyze_review` | 96 | F |
| `src/aqg/scaffold.py:782::build_onboarding` | 47 | F |
| `src/aqg/scaffold.py:1239::install_toolchains` | 35 | E |
| `src/aqg/checks.py:304::parse_feature` | 33 | E |
| `src/aqg/approvals.py:105::validate_approval` | 30 | D |
| `src/aqg/doctor.py:261::_check_toolchains` | 30 | D |
| `src/aqg/checks.py:213::scan_secrets` | 25 | D |
| `src/aqg/review.py:761::_html` | 25 | D |
| `src/aqg/hooks.py:104::hook_pretool` | 24 | D |
| `src/aqg/scaffold.py:1055::initialize_project` | 23 | D |
| `src/aqg/tui.py:41::_draw` | 23 | D |
| `src/aqg/adapters.py:734::_js_coverage_metrics` | 21 | D |
| `src/aqg/conformance.py:384::run_tool_conformance` | 20 | C |
| `src/aqg/review.py:658::_markdown` | 20 | C |
| `src/aqg/sbom.py:250::_strip_jsonc` | 20 | C |
| `src/aqg/wizard.py:30::run_wizard` | 20 | C |
| `src/aqg/adapters.py:685::_python_coverage_metrics` | 19 | C |
| `src/aqg/adapters.py:791::_python_crap` | 19 | C |
| `src/aqg/adapters.py:1712::_reproducible_build` | 19 | C |
| `src/aqg/checks.py:74::scan_test_integrity` | 19 | C |

## Switch contract

- whole-tree line and branch coverage meet Standard thresholds
- whole-tree structure and CRAP meet Standard caps
- whole-tree mutation meets the Standard target after survivor triage
- all supported adapter, control-surface, and release conformance passes
- no missing, stale, crashed, or silently skipped required evidence

## Ratchet-to-strict roadmap

1. Keep changed-code Standard gates authoritative while inherited debt remains visible.
2. Test low-coverage control and evidence modules by observable failure mode, not by line.
3. Split the highest-complexity functions behind characterization tests without changing diagnostics.
4. Run broader source mutation only after fresh coverage makes the scope trustworthy.
5. Switch `quality/project.json` to strict in a dedicated policy-maintenance change only when every switch-contract item is green.

Suggested coverage checkpoints are 60%, 70%, then the 85% Standard line target. They are progress markers, not substitutes for the final threshold.
