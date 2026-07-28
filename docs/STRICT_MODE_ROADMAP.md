# Strict-mode readiness

Revision: `fa0e5e2affec76cb1822520af670341ca238d85e` · mode: **adopt** · strict ready: **no**

## Current evidence

- Tests: 415
- Line coverage: 68.47% (gap 16.53 points)
- Branch coverage: 57.67% (gap 17.33 points)
- Functions above complexity cap: 62

## Lowest coverage modules

| Module                                |  Lines | Branches | Missing statements |
| ------------------------------------- | -----: | -------: | -----------------: |
| `scripts/dogfood_control_surfaces.py` |  0.00% |    0.00% |                171 |
| `src/aqg/__main__.py`                 |  0.00% |  100.00% |                  2 |
| `src/aqg/wizard.py`                   | 19.12% |    0.00% |                 55 |
| `src/aqg/portfolio.py`                | 22.73% |    0.00% |                 51 |
| `src/aqg/authoring.py`                | 25.64% |    0.00% |                 29 |
| `scripts/project_matrix.py`           | 27.91% |    8.33% |                124 |
| `scripts/build_release.py`            | 33.94% |   23.81% |                109 |
| `src/aqg/acceptance.py`               | 41.24% |   33.87% |                114 |
| `scripts/measure_strict_readiness.py` | 42.11% |   66.67% |                 44 |
| `src/aqg/reporting.py`                | 47.46% |   25.00% |                 31 |
| `src/aqg/adapters.py`                 | 48.72% |   34.30% |                619 |
| `src/aqg/sbom.py`                     | 48.73% |   35.12% |                242 |

## Highest complexity functions

| Function                                             | Complexity | Rank |
| ---------------------------------------------------- | ---------: | :--: |
| `src/aqg/scaffold.py:833::build_onboarding`          |         47 |  F   |
| `src/aqg/scaffold.py:1368::install_toolchains`       |         35 |  E   |
| `src/aqg/acceptance.py:225::run_acceptance_mutation` |         33 |  E   |
| `src/aqg/approvals.py:119::validate_approval`        |         30 |  D   |
| `src/aqg/doctor.py:320::_check_toolchains`           |         30 |  D   |
| `src/aqg/hooks.py:140::hook_pretool`                 |         29 |  D   |
| `src/aqg/runner.py:262::run_profile`                 |         26 |  D   |
| `src/aqg/checks.py:267::scan_secrets`                |         25 |  D   |
| `src/aqg/review.py:1131::_html`                      |         25 |  D   |
| `src/aqg/scaffold.py:1106::initialize_project`       |         23 |  D   |
| `src/aqg/tui.py:41::_draw`                           |         23 |  D   |
| `src/aqg/runner.py:147::run_gate`                    |         21 |  D   |
| `src/aqg/conformance.py:389::run_tool_conformance`   |         20 |  C   |
| `src/aqg/review.py:1028::_markdown`                  |         20 |  C   |
| `src/aqg/sbom.py:252::_strip_jsonc`                  |         20 |  C   |
| `src/aqg/adapters.py:939::_python_crap`              |         19 |  C   |
| `src/aqg/adapters.py:2485::_reproducible_build`      |         19 |  C   |
| `src/aqg/checks.py:126::scan_test_integrity`         |         19 |  C   |
| `src/aqg/checks.py:669::test_feature_traceability`   |         19 |  C   |
| `src/aqg/tui.py:140::_run`                           |         19 |  C   |

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
