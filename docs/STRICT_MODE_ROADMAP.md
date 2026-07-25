# Strict-mode readiness

Revision: `de25a0c33132c12f989a4b39f9e66fd17448456e` · mode: **adopt** · strict ready: **no**

## Current evidence

- Tests: 94
- Line coverage: 55.62% (gap 29.38 points)
- Branch coverage: 43.27% (gap 31.73 points)
- Functions above complexity cap: 54

## Lowest coverage modules

| Module                                |  Lines | Branches | Missing statements |
| ------------------------------------- | -----: | -------: | -----------------: |
| `scripts/build_release.py`            |  0.00% |    0.00% |                117 |
| `scripts/dogfood_control_surfaces.py` |  0.00% |    0.00% |                171 |
| `scripts/measure_strict_readiness.py` |  0.00% |    0.00% |                 59 |
| `src/aqg/__main__.py`                 |  0.00% |  100.00% |                  2 |
| `src/aqg/acceptance.py`               | 17.24% |    0.00% |                 96 |
| `src/aqg/wizard.py`                   | 19.12% |    0.00% |                 55 |
| `src/aqg/portfolio.py`                | 22.73% |    0.00% |                 51 |
| `src/aqg/authoring.py`                | 25.64% |    0.00% |                 29 |
| `src/aqg/reporting.py`                | 27.12% |    4.17% |                 43 |
| `scripts/project_matrix.py`           | 27.91% |    8.33% |                124 |
| `src/aqg/adapters.py`                 | 30.81% |   20.32% |                667 |
| `src/aqg/runner.py`                   | 46.32% |   17.39% |                 73 |

## Highest complexity functions

| Function                                           | Complexity | Rank |
| -------------------------------------------------- | ---------: | :--: |
| `src/aqg/review.py:304::analyze_review`            |        101 |  F   |
| `src/aqg/scaffold.py:785::build_onboarding`        |         47 |  F   |
| `src/aqg/scaffold.py:1307::install_toolchains`     |         35 |  E   |
| `src/aqg/checks.py:304::parse_feature`             |         33 |  E   |
| `src/aqg/approvals.py:105::validate_approval`      |         30 |  D   |
| `src/aqg/doctor.py:261::_check_toolchains`         |         30 |  D   |
| `src/aqg/checks.py:213::scan_secrets`              |         25 |  D   |
| `src/aqg/review.py:894::_html`                     |         25 |  D   |
| `src/aqg/hooks.py:104::hook_pretool`               |         24 |  D   |
| `src/aqg/scaffold.py:1058::initialize_project`     |         23 |  D   |
| `src/aqg/tui.py:41::_draw`                         |         23 |  D   |
| `src/aqg/conformance.py:384::run_tool_conformance` |         20 |  C   |
| `src/aqg/review.py:791::_markdown`                 |         20 |  C   |
| `src/aqg/sbom.py:252::_strip_jsonc`                |         20 |  C   |
| `src/aqg/wizard.py:30::run_wizard`                 |         20 |  C   |
| `src/aqg/adapters.py:817::_python_crap`            |         19 |  C   |
| `src/aqg/adapters.py:1854::_reproducible_build`    |         19 |  C   |
| `src/aqg/checks.py:74::scan_test_integrity`        |         19 |  C   |
| `src/aqg/doctor.py:84::diagnose`                   |         19 |  C   |
| `src/aqg/tui.py:140::_run`                         |         19 |  C   |

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
