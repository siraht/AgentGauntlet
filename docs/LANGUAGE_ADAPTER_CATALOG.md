# Language adapter catalog

These are examples, not mandatory choices. The bootstrap agent should prefer maintained tools already used by the repository, verify current support, pin versions, and wrap exit codes/evidence to the adapter contract.

| Stack | Format/lint/type | Coverage/complexity | Mutation/property | Security/contracts |
|---|---|---|---|---|
| Python | Ruff, Pyright or mypy, pytest | coverage.py, Radon/Xenon | mutmut or Cosmic Ray, Hypothesis | pip-audit, Bandit, schema/HTTP contract tools |
| JavaScript/TypeScript | Prettier, ESLint, `tsc` | c8/Istanbul, ESLint complexity | StrykerJS, fast-check | package audit, Playwright, API/schema contracts |
| Go | gofmt, go vet, Staticcheck | `go test -cover`, gocyclo | Gremlins or go-mutesting, rapid/gopter | govulncheck, fuzzing, interface/API contracts |
| Java/Kotlin | Checkstyle/PMD/SpotBugs/Error Prone | JaCoCo, PMD complexity | PIT, jqwik/QuickTheories | ArchUnit, dependency scanning, schema/HTTP contracts |
| .NET | `dotnet format`, analyzers | Coverlet, complexity analyzers | Stryker.NET, FsCheck | dependency audit, architecture tests, API contracts |
| Rust | rustfmt, Clippy | cargo-llvm-cov, complexity lints | cargo-mutants, proptest | cargo-audit/deny, unsafe-code policy |
| C/C++ | clang-format, clang-tidy | llvm-cov/gcov, complexity tools | Mull, property/fuzz harnesses | sanitizers, static analysis, dependency/SBOM tools |
| Ruby | RuboCop, type tooling where used | SimpleCov, flog | mutant, property libraries | bundle audit, contract tests |
| PHP | PHP-CS-Fixer, PHPStan/Psalm | PHPUnit coverage, complexity analyzers | Infection | Composer audit, API/schema contracts |
| Clojure | clj-kondo, tests/specs | Cloverage, crap4clj | clj-mutate, test.check | dependency and boundary checks |

Adapters should expose stable commands such as:

```text
quality/bin/format-check
quality/bin/lint
quality/bin/test-integrity
quality/bin/unit
quality/bin/structure
quality/bin/coverage
quality/bin/acceptance
quality/bin/mutation-changed
quality/bin/security-fast
```

`quality/policy.toml` points at these commands, so Codex, Claude Code, local developers, and CI all invoke the same behavior.
