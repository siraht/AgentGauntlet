"""Automated review heuristics and human-oriented review packet generation."""

from __future__ import annotations

import ast
import html
import io
import re
import token
import tokenize
from pathlib import Path
from typing import Any

from .approvals import validate_required_approvals
from .checks import test_feature_traceability
from .constants import PASS, QUALITY_FAILURE
from .policy import human_review_patterns, protected_patterns, risk_summary
from .project import load_project
from .runner import list_runs
from .util import (
    change_fingerprint,
    control_fingerprint,
    git_changed_files,
    git_diff,
    git_revision,
    matches_any,
    utc_now,
    write_json,
)

PRODUCTION_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".mts",
    ".cts",
    ".html",
    ".css",
    ".scss",
}
TEST_TOKENS = {"test", "tests", "spec", "specs", "__tests__", "e2e", "acceptance"}
LOOPBACK_URL = re.compile(r"https?://(?:127(?:\.\d+){3}|localhost|\[::1\])(?=[:/])")


def _is_test(path: str) -> bool:
    rel = Path(path)
    name = rel.name.lower()
    return (
        any(part.lower() in TEST_TOKENS for part in rel.parts)
        or bool(re.search(r"(?:^|[._-])(test|spec)(?:[._-]|$)", name))
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


def _finding(
    code: str,
    severity: str,
    title: str,
    detail: str,
    paths: list[str],
    action: str,
    automated: bool = True,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "title": title,
        "detail": detail,
        "paths": sorted(set(paths)),
        "action": action,
        "automated": automated,
    }


def _added_lines(diff: str) -> list[tuple[str, int, str]]:
    output: list[tuple[str, int, str]] = []
    path = ""
    line_number = 0
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
        elif line.startswith("@@"):
            match = re.search(r"\+(\d+)", line)
            line_number = int(match.group(1)) if match else 0
        elif line.startswith("+") and not line.startswith("+++"):
            output.append((path, line_number, line[1:]))
            line_number += 1
        elif not line.startswith("-"):
            line_number += 1
    return output


def _deleted_lines(diff: str) -> list[tuple[str, int, str]]:
    output: list[tuple[str, int, str]] = []
    path = ""
    line_number = 0
    for line in diff.splitlines():
        if line.startswith("--- a/"):
            path = line[6:]
        elif line.startswith("@@"):
            match = re.search(r"-(\d+)", line)
            line_number = int(match.group(1)) if match else 0
        elif line.startswith("-") and not line.startswith("---"):
            output.append((path, line_number, line[1:]))
            line_number += 1
        elif not line.startswith("+"):
            line_number += 1
    return output


def _line_locations(
    lines: list[tuple[str, int, str]], pattern: re.Pattern[str], *, predicate: Any | None = None
) -> list[str]:
    locations: list[str] = []
    for path, line_no, line in lines:
        if predicate is not None and not predicate(path):
            continue
        if pattern.search(line):
            locations.append(f"{path}:{line_no}")
    return sorted(set(locations))


def _qualified_call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _qualified_call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _static_string(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            str(value.value)
            for value in node.values
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        )
    return None


def _loopback_expression(node: ast.expr, safe_names: set[str]) -> bool:
    if isinstance(node, ast.Name):
        return node.id in safe_names
    static_text = _static_string(node)
    if static_text is not None:
        return bool(LOOPBACK_URL.search(static_text))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _loopback_expression(node.left, safe_names)
    if isinstance(node, ast.Call) and _qualified_call_name(node.func).endswith(".Request"):
        return bool(node.args) and _loopback_expression(node.args[0], safe_names)
    return False


def _python_assignments(root: Path, path: str) -> list[ast.Assign | ast.AnnAssign]:
    source = root / path
    if source.suffix.lower() not in {".py", ".pyi"} or not source.is_file():
        return []
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError):
        return []
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None
    ]


def _assigned_names(assignment: ast.Assign | ast.AnnAssign) -> set[str]:
    targets = assignment.targets if isinstance(assignment, ast.Assign) else [assignment.target]
    return {target.id for target in targets if isinstance(target, ast.Name)}


def _loopback_bindings(root: Path, path: str) -> set[str]:
    assignments = _python_assignments(root, path)
    safe: set[str] = set()
    while True:
        previous = len(safe)
        for assignment in assignments:
            value = assignment.value
            if value is not None and _loopback_expression(value, safe):
                safe.update(_assigned_names(assignment))
        if len(safe) == previous:
            return safe


def _is_controlled_loopback_call(root: Path, path: str, line: str) -> bool:
    if LOOPBACK_URL.search(line):
        return True
    argument = re.search(
        r"(?:fetch|requests\.(?:get|post|put|delete|patch)|httpx\.(?:get|post|put|delete|patch)|urllib\.request\.urlopen)\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)",
        line,
        re.IGNORECASE,
    )
    return bool(argument and argument.group(1) in _loopback_bindings(root, path))


def _nondeterministic_test_locations(
    root: Path,
    added: list[tuple[str, int, str]],
    pattern: re.Pattern[str],
    network_pattern: re.Pattern[str],
) -> list[str]:
    locations: list[str] = []
    for path, line_no, line in added:
        match = pattern.search(line)
        if not _is_test(path) or match is None:
            continue
        if _match_is_inside_python_string(root, path, line_no, match.start()):
            continue
        if network_pattern.search(line) and _is_controlled_loopback_call(root, path, line):
            continue
        locations.append(f"{path}:{line_no}")
    return sorted(set(locations))


def _is_production_path(path: str) -> bool:
    return (
        Path(path).suffix.lower() in PRODUCTION_EXTENSIONS
        and not _is_test(path)
        and not path.startswith(("quality/", ".aqg/"))
    )


def _match_is_inside_python_string(root: Path, path: str, line_no: int, column: int) -> bool:
    if Path(path).suffix.lower() not in {".py", ".pyi"}:
        return False
    source = root / path
    if not source.is_file():
        return False
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source.read_text(encoding="utf-8")).readline)
        return any(
            item.type == token.STRING
            and item.start <= (line_no, column)
            and (line_no, column) < item.end
            for item in tokens
        )
    except (OSError, UnicodeError, tokenize.TokenError):
        return False


def _match_is_inside_python_comment(root: Path, path: str, line_no: int, column: int) -> bool:
    if Path(path).suffix.lower() not in {".py", ".pyi"}:
        return False
    source = root / path
    if not source.is_file():
        return False
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source.read_text(encoding="utf-8")).readline)
        return any(
            item.type == token.COMMENT
            and item.start <= (line_no, column)
            and (line_no, column) < item.end
            for item in tokens
        )
    except (OSError, UnicodeError, tokenize.TokenError):
        return False


def _risk_factor_path_hints(changed: list[str]) -> dict[str, list[str]]:
    rules = {
        "authentication": re.compile(
            r"(?i)(auth|login|logout|session|password|credential|oauth|sso|jwt)"
        ),
        "authorization": re.compile(r"(?i)(permission|policy|role|acl|rbac|authorize|entitlement)"),
        "privacy": re.compile(
            r"(?i)(privacy|pii|personal[_-]?data|tracking|analytics|consent|cookie)"
        ),
        "money": re.compile(r"(?i)(payment|billing|invoice|price|checkout|refund|credit|currency)"),
        "migration": re.compile(r"(?i)(migration|alembic|schema|ddl|prisma|knex)"),
        "external_contract": re.compile(r"(?i)(openapi|swagger|graphql|proto|api|contract|schema)"),
        "concurrency": re.compile(
            r"(?i)(lock|mutex|semaphore|queue|worker|thread|async|concurrent|race)"
        ),
        "supply_chain": re.compile(
            r"(?i)(package-lock|pnpm-lock|yarn.lock|uv.lock|requirements|dockerfile|workflow|action)"
        ),
        "data_loss": re.compile(r"(?i)(delete|purge|drop|truncate|destroy|erase|overwrite)"),
    }
    product_surface = [
        path
        for path in changed
        if _is_production_path(path)
        or Path(path).suffix.lower() in {".sql", ".graphql", ".proto"}
        or path.startswith(("api/", "migrations/", "schemas/"))
    ]
    output = {
        factor: [path for path in product_surface if pattern.search(path)]
        for factor, pattern in rules.items()
        if factor != "supply_chain"
    }
    output["supply_chain"] = [path for path in changed if rules["supply_chain"].search(path)]
    return output


def _partition_changed_paths(changed: list[str]) -> tuple[list[str], list[str]]:
    production = [path for path in changed if _is_production_path(path)]
    tests = [path for path in changed if _is_test(path)]
    return production, tests


def _findings_policy_plane(changed: list[str], policy: dict[str, Any]) -> list[dict[str, Any]]:
    protected = [path for path in changed if matches_any(path, protected_patterns(policy))]
    if not protected:
        return []
    return [
        _finding(
            "policy-plane-change",
            "blocker",
            "Policy-plane files changed",
            "These files can change what counts as a pass or what agents are allowed to modify, so they require an explicit policy-maintenance review.",
            protected,
            "Review the raw diff with the policy owner and confirm the change does not weaken any gate, path protection, threshold, or command indirection.",
        )
    ]


def _findings_human_review_plane(
    changed: list[str], policy: dict[str, Any]
) -> list[dict[str, Any]]:
    review_paths = [path for path in changed if matches_any(path, human_review_patterns(policy))]
    if not review_paths:
        return []
    return [
        _finding(
            "human-review-plane-change",
            "review",
            "Behavioral or approval artifacts changed",
            "These files describe behavior, expected output, migrations, schemas, dependencies, or QA and must be reviewed as product evidence rather than accepted as incidental code churn.",
            review_paths,
            "Review each diff for intentional behavior, stable normalization, rollback impact, and consistency with the risk card.",
            automated=False,
        )
    ]


def _findings_production_without_tests(
    production: list[str], tests: list[str]
) -> list[dict[str, Any]]:
    if not production or tests:
        return []
    return [
        _finding(
            "production-without-tests",
            "blocker",
            "Production behavior changed without a changed executable test",
            "Existing tests may cover the change, but no test diff demonstrates the new or preserved behavior and mutation evidence may be too broad to reveal the gap.",
            production,
            "Add focused unit/property/contract/acceptance evidence, or document why existing immutable tests already prove the change and verify that claim with mutation testing.",
        )
    ]


def _deleted_test_assertion_paths(diff: str) -> list[str]:
    deleted_tests: list[str] = []
    current_path = ""
    for line in diff.splitlines():
        if line.startswith("--- a/"):
            current_path = line[6:]
            continue
        if (
            line.startswith("-")
            and not line.startswith("---")
            and _is_test(current_path)
            and re.search(r"\b(?:def\s+test_|it\s*\(|test\s*\(|expect\s*\(|assert\b)", line[1:])
        ):
            deleted_tests.append(current_path)
    return deleted_tests


def _findings_test_expectation_deleted(diff: str) -> list[dict[str, Any]]:
    deleted_tests = _deleted_test_assertion_paths(diff)
    if not deleted_tests:
        return []
    return [
        _finding(
            "test-expectation-deleted",
            "blocker",
            "Test assertions or cases were deleted",
            "Deleting an assertion can make an implementation appear correct by reducing the oracle rather than fixing behavior.",
            deleted_tests,
            "Explain every deleted expectation, identify replacement evidence, and inspect mutation survivors around the affected behavior.",
        )
    ]


_SUPPRESSION_PATTERNS = {
    "focused-or-skipped-test": re.compile(
        r"\b(?:describe|it|test)\.(?:only|skip|todo)\b|@pytest\.mark\.(?:skip|skipif|xfail)\b|pytest\.(?:skip|xfail)\s*\("
    ),
    "coverage-suppression": re.compile(
        r"(?i)(pragma:\s*no\s*cover|istanbul\s+ignore|c8\s+ignore|coverage:\s*ignore)"
    ),
    "mutation-suppression": re.compile(r"(?i)(pragma:\s*no\s+mutate|stryker\s+disable)"),
    "lint-or-type-suppression": re.compile(
        r"(?i)(eslint-disable|stylelint-disable|type:\s*ignore|noqa|mypy:\s*ignore-errors|ts-ignore|ts-nocheck)"
    ),
}


def _weak_marker_locations(
    root: Path, added: list[tuple[str, int, str]]
) -> dict[str, list[str]]:
    weak_markers: dict[str, list[str]] = {}
    for path, line_no, line in added:
        if Path(path).suffix.lower() in {".md", ".feature", ".txt"}:
            continue
        for code, pattern in _SUPPRESSION_PATTERNS.items():
            match = pattern.search(line)
            if match and not _match_is_inside_python_string(root, path, line_no, match.start()):
                weak_markers.setdefault(code, []).append(f"{path}:{line_no}")
    return weak_markers


def _findings_quality_suppressions(
    root: Path, added: list[tuple[str, int, str]]
) -> list[dict[str, Any]]:
    return [
        _finding(
            code,
            "blocker",
            "A new quality suppression was added",
            "Suppressions directly reduce what deterministic tools can prove and are equivalent to changing a test or threshold when used without narrow justification.",
            paths,
            "Remove the suppression or create a narrow, expiring, owner-approved waiver with a reproduced false positive and compensating evidence.",
        )
        for code, paths in _weak_marker_locations(root, added).items()
    ]


def analyze_review(
    root: Path, policy: dict[str, Any], *, base: str = "HEAD", require_evidence: bool = True
) -> dict[str, Any]:
    project = load_project(root)
    changed = git_changed_files(root, base)
    diff = git_diff(root, base, unified=1)
    added = _added_lines(diff)
    deleted = _deleted_lines(diff)
    production, tests = _partition_changed_paths(changed)
    findings: list[dict[str, Any]] = [
        *_findings_policy_plane(changed, policy),
        *_findings_human_review_plane(changed, policy),
        *_findings_production_without_tests(production, tests),
        *_findings_test_expectation_deleted(diff),
        *_findings_quality_suppressions(root, added),
    ]

    # Review heuristics are intentionally conservative: they surface likely weak points but
    # do not claim semantic proof where a parser, runtime, or domain oracle is required.
    swallowed: list[str] = []
    by_path: dict[str, list[tuple[int, str]]] = {}
    for path, line_no, line in added:
        by_path.setdefault(path, []).append((line_no, line))
        if _is_production_path(path) and re.search(r"(?i)\bcatch\s*(?:\([^)]*\))?\s*\{\s*\}", line):
            swallowed.append(f"{path}:{line_no}")
    for path, lines in by_path.items():
        if not path.endswith((".py", ".pyi")) or not _is_production_path(path):
            continue
        ordered = sorted(lines)
        for index, (line_no, line) in enumerate(ordered):
            if not re.search(
                r"^\s*except\s+(?:BaseException|Exception)(?:\s+as\s+\w+)?\s*:\s*$", line
            ):
                continue
            following = "\n".join(value for _, value in ordered[index + 1 : index + 4])
            if re.search(r"(?m)^\s*(?:pass|return\s+None)\s*(?:#.*)?$", following):
                swallowed.append(f"{path}:{line_no}")
    if swallowed:
        findings.append(
            _finding(
                "swallowed-broad-exception",
                "blocker",
                "A broad exception is swallowed",
                "Catching a broad failure and continuing without a typed recovery, observable error, or preserved cause can convert corruption and infrastructure faults into apparent success.",
                swallowed,
                "Catch the narrow failure you can recover from, preserve or re-raise unexpected failures, and add a test that proves both the intended recovery and the non-recoverable path.",
            )
        )

    debt_pattern = re.compile(r"(?i)\b(?:TODO|FIXME|HACK|XXX)\b")
    debt_markers: list[str] = []
    for path, line_no, line in added:
        if not _is_production_path(path):
            continue
        match = debt_pattern.search(line)
        if match is None:
            continue
        if Path(path).suffix.lower() in {".py", ".pyi"} and not _match_is_inside_python_comment(
            root, path, line_no, match.start()
        ):
            continue
        debt_markers.append(f"{path}:{line_no}")
    debt_markers = sorted(set(debt_markers))
    if debt_markers:
        findings.append(
            _finding(
                "new-production-debt-marker",
                "warning",
                "New unresolved implementation debt was added",
                "A TODO, FIXME, HACK, or XXX marker in changed production code often represents an unstated requirement, deferred safety condition, or temporary branch that future agents will treat as normal behavior.",
                debt_markers,
                "Resolve it now or link a concrete tracked decision with an owner, bounded impact, and removal condition; do not use a comment as a substitute for a failing test or TODO feature specification.",
            )
        )

    network_test_patterns = re.compile(
        r"\b(?:fetch|requests\.(?:get|post|put|delete|patch)|httpx\.(?:get|post|put|delete|patch)|urllib\.request\.urlopen)\s*\(",
        re.IGNORECASE,
    )
    nondeterministic_test_patterns = re.compile(
        rf"(?:\b(?:time\.sleep|asyncio\.sleep|setTimeout|setInterval|Date\.now|datetime\.(?:now|utcnow)|time\.time|Math\.random|random\.(?:random|randint|choice)|uuid\.uuid4)\s*\(|{network_test_patterns.pattern})",
        re.IGNORECASE,
    )
    nondeterministic_tests = _nondeterministic_test_locations(
        root,
        added,
        nondeterministic_test_patterns,
        network_test_patterns,
    )
    if nondeterministic_tests:
        findings.append(
            _finding(
                "test-nondeterminism-introduced",
                "warning",
                "Changed tests appear to depend on uncontrolled time, randomness, delay, or network",
                "Real clocks, random generators, sleeps, and live network calls make tests timing-sensitive and can let a retry mask the behavior the test was meant to prove.",
                nondeterministic_tests,
                "Inject or freeze the varying dependency, wait on an observable condition instead of sleeping, and keep a separately labeled live probe only when the real dependency is the subject of the test.",
            )
        )

    weak_assertions = _line_locations(
        added,
        re.compile(
            r"(?:\.toBeTruthy\s*\(\s*\)|\.toBeDefined\s*\(\s*\)|\.toBe(?:GreaterThan|GreaterThanOrEqual)\s*\(\s*0\s*\)|^\s*assert\s+[A-Za-z_][A-Za-z0-9_.]*\s*(?:#.*)?$)"
        ),
        predicate=_is_test,
    )
    if weak_assertions:
        findings.append(
            _finding(
                "weak-test-oracle",
                "warning",
                "Changed tests contain low-specificity assertions",
                "Truthiness, existence, nonzero-count, and bare-object assertions can pass while the returned value, state transition, side effects, ordering, or authorization behavior is wrong.",
                weak_assertions,
                "Assert the exact domain result and critical side effects, then confirm the assertion kills a plausible mutation rather than merely observing that some value exists.",
            )
        )

    public_contracts = [
        path
        for path in changed
        if re.search(
            r"(?i)(?:^|/)(?:api|routes?|schemas?|contracts?|openapi|swagger|graphql|proto)(?:/|\.|$)",
            path,
        )
        or Path(path).suffix.lower() in {".proto", ".graphql", ".gql"}
        or re.search(r"(?i)(openapi|swagger).*(?:json|ya?ml)$", path)
    ]
    contract_evidence = [
        path
        for path in tests
        if re.search(r"(?i)(contract|schema|api|route|openapi|graphql|proto)", path)
    ]
    if public_contracts and not contract_evidence:
        findings.append(
            _finding(
                "public-contract-without-contract-test",
                "review",
                "A likely public interface changed without changed contract evidence",
                "API routes, schemas, protocol definitions, and public data shapes can remain unit-test green while breaking consumers, compatibility, error semantics, or authorization boundaries.",
                public_contracts,
                "Review the interface diff and add or update consumer-visible contract tests, compatibility fixtures, versioning/migration evidence, and negative authorization cases as applicable.",
                automated=False,
            )
        )

    lifecycle_scripts = _line_locations(
        added,
        re.compile(r'"(?:preinstall|install|postinstall|prepare)"\s*:'),
        predicate=lambda path: Path(path).name == "package.json",
    )
    if lifecycle_scripts:
        findings.append(
            _finding(
                "dependency-lifecycle-script-change",
                "review",
                "A package lifecycle script was added or changed",
                "Install and prepare hooks execute during dependency setup and can alter the build environment, fetch code, expose credentials, or bypass the ordinary quality command surface.",
                lifecycle_scripts,
                "Inspect the exact command and transitive tools, require a deterministic offline-safe path where practical, and ensure CI and developer setup execute the same reviewed behavior.",
                automated=False,
            )
        )

    deleted_case_markers = _line_locations(
        deleted,
        re.compile(r"(?:\b(?:it|test)\s*\(|^\s*(?:async\s+)?def\s+test_|^\s*class\s+Test)"),
        predicate=_is_test,
    )
    added_case_markers = _line_locations(
        added,
        re.compile(r"(?:\b(?:it|test)\s*\(|^\s*(?:async\s+)?def\s+test_|^\s*class\s+Test)"),
        predicate=_is_test,
    )
    if production and len(deleted_case_markers) > len(added_case_markers):
        findings.append(
            _finding(
                "test-case-count-reduced",
                "review",
                "The changed diff removes more test cases than it adds",
                "Test count alone is not quality, but a net reduction alongside production changes can shrink the behavioral oracle or remove a distinct equivalence class.",
                deleted_case_markers,
                "Map every removed case to preserved or stronger evidence and inspect mutation, boundary, and failure-path coverage before accepting the reduction.",
                automated=False,
            )
        )

    snapshots = [
        path
        for path in changed
        if re.search(r"(?i)(golden|snapshot|__snapshots__|fixture|cassette)", path)
    ]
    if snapshots:
        findings.append(
            _finding(
                "expected-output-change",
                "review",
                "Expected-output artifacts changed",
                "Regenerated snapshots and goldens can approve a regression as easily as they can record an intended change.",
                snapshots,
                "Review the full semantic diff and its source behavior; do not approve a bulk update solely because the test command requested it.",
                automated=False,
            )
        )

    dependencies = [
        path
        for path in changed
        if Path(path).name
        in {
            "package.json",
            "package-lock.json",
            "pnpm-lock.yaml",
            "yarn.lock",
            "bun.lock",
            "bun.lockb",
            "pyproject.toml",
            "uv.lock",
            "Pipfile",
            "Pipfile.lock",
        }
        or re.match(r"requirements.*\.txt", Path(path).name)
    ]
    if dependencies:
        findings.append(
            _finding(
                "dependency-change",
                "review",
                "Dependency or lockfile surface changed",
                "Dependency changes alter executable supply-chain input and can invalidate cached test and mutation evidence even when application source is unchanged.",
                dependencies,
                "Inspect direct and transitive changes, provenance, license/security findings, lockfile integrity, and whether mutation or golden caches were invalidated.",
                automated=False,
            )
        )

    risk_errors: list[str] = []
    risk_payload: dict[str, Any] | None = None
    try:
        risk_errors, risk_payload = risk_summary(root, policy, "quality/change-risk.json")
    except Exception as exc:  # rendered as a blocker, not hidden
        risk_errors = [str(exc)]
    if risk_errors:
        findings.append(
            _finding(
                "invalid-risk-card",
                "blocker",
                "Change-risk card is missing, invalid, or under-classified",
                "; ".join(risk_errors),
                ["quality/change-risk.json"],
                "Resolve the schema and deterministic minimum before relying on the selected execution profile.",
            )
        )
    if risk_payload:
        factors = risk_payload["card"].get("risk_factors", {})
        for factor, paths in _risk_factor_path_hints(changed).items():
            if paths and not factors.get(factor, False):
                findings.append(
                    _finding(
                        f"risk-factor-{factor}",
                        "blocker",
                        f"Changed paths imply the {factor.replace('_', ' ')} risk factor",
                        f"The risk card marks {factor!r} false, but path heuristics found likely affected files. This is a review prompt rather than proof, but the mismatch must be resolved explicitly.",
                        paths,
                        f"Set risk_factors.{factor}=true or document why these files do not affect that risk and have a human approve the classification.",
                    )
                )

    traceability = test_feature_traceability(root, project)
    for finding in traceability.get("findings", []):
        findings.append(
            _finding(
                finding["code"],
                "review",
                "Active product behavior lacks explicit test traceability",
                finding["message"],
                [finding.get("path", "feature-spec/")],
                finding.get("remediation") or "Add the feature identifier to an executable test.",
            )
        )

    runs = list_runs(root, limit=100)
    current_revision = git_revision(root)
    current_change_fingerprint = change_fingerprint(root, base)
    current_control_fingerprint = control_fingerprint(root)
    evidence_matrix: list[dict[str, Any]] = []
    required_profiles = (
        list(risk_payload.get("required_execution_profiles", [])) if risk_payload else []
    )
    for profile in required_profiles:
        matching = next(
            (
                run
                for run in runs
                if run.get("profile") == profile
                and run.get("status") == "pass"
                and run.get("revision") == current_revision
                and run.get("change_fingerprint") == current_change_fingerprint
                and run.get("control_fingerprint") == current_control_fingerprint
            ),
            None,
        )
        evidence_matrix.append(
            {
                "profile": profile,
                "status": "current_pass" if matching else "missing_or_stale",
                "run_id": matching.get("run_id") if matching else None,
            }
        )
    if require_evidence and not required_profiles:
        findings.append(
            _finding(
                "no-required-profile",
                "blocker",
                "Risk policy resolved to no required execution profile",
                "The risk card cannot authorize completion without at least one deterministic execution profile.",
                ["quality/change-risk.json", "quality/policy.toml"],
                "Repair the risk policy during policy maintenance and rerun the required profile.",
            )
        )
    for item in evidence_matrix:
        if require_evidence and item["status"] != "current_pass":
            findings.append(
                _finding(
                    f"missing-current-{item['profile']}-evidence",
                    "blocker",
                    f"No current passing {item['profile']} evidence",
                    "A prior run is not reusable when the revision, review-surface fingerprint, or control-plane fingerprint differs from the current repository state.",
                    [".aqg/runs"],
                    f"Run `python3 quality/qg.py check {item['profile']} --keep-going` after the final change, then regenerate the review packet.",
                )
            )
    approvals: dict[str, Any] = {"required": [], "results": {}, "errors": [], "exit_code": 0}
    if risk_payload:
        approvals = validate_required_approvals(
            root, str(risk_payload.get("selected_risk_profile") or "standard")
        )
    if require_evidence:
        for message in approvals.get("errors", []):
            findings.append(
                _finding(
                    "missing-or-stale-human-approval",
                    "blocker",
                    "Required human approval is missing, incomplete, or stale",
                    str(message),
                    ["quality/approvals"],
                    "Use `python3 quality/qg.py approval template <kind>`, complete the concrete scope/procedure/evidence as the named human reviewer, then validate it against the unchanged revision.",
                    automated=False,
                )
            )

    latest = runs[0] if runs else None
    if require_evidence and latest is None and not evidence_matrix:
        findings.append(
            _finding(
                "no-quality-evidence",
                "blocker",
                "No AQG profile evidence exists",
                "A completion claim is unsupported until deterministic gates have produced a normalized run record.",
                [],
                "Run `python3 quality/qg.py check-risk --keep-going` after the final code and test changes.",
            )
        )

    severity_order = {"blocker": 0, "review": 1, "warning": 2, "info": 3}
    findings.sort(key=lambda item: (severity_order.get(item["severity"], 9), item["code"]))
    return {
        "schema_version": 3,
        "generated_at": utc_now(),
        "base": base,
        "revision": current_revision,
        "change_fingerprint": current_change_fingerprint,
        "control_fingerprint": current_control_fingerprint,
        "changed_files": changed,
        "summary": {
            "changed": len(changed),
            "changed_files": len(changed),
            "production": len(production),
            "tests": len(tests),
            "blockers": sum(item["severity"] == "blocker" for item in findings),
            "human_review": sum(item["severity"] == "review" for item in findings),
            "warnings": sum(item["severity"] == "warning" for item in findings),
            "evidence_status": "current"
            if evidence_matrix and all(item["status"] == "current_pass" for item in evidence_matrix)
            else "missing_or_stale",
            "approval_status": "current" if not approvals.get("errors") else "missing_or_stale",
        },
        "risk": risk_payload,
        "evidence": evidence_matrix,
        "approvals": approvals,
        "latest_runs": runs,
        "findings": findings,
    }


def _markdown(packet: dict[str, Any]) -> str:
    summary = packet["summary"]
    decision = (
        "BLOCKED"
        if summary["blockers"]
        else "HUMAN REVIEW REQUIRED"
        if summary["human_review"]
        else "AUTOMATED REVIEW CLEAR"
    )
    lines = [
        "# AQG review packet",
        "",
        f"**Decision:** {decision}",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Revision | `{packet['revision']}` |",
        f"| Diff base | `{packet['base']}` |",
        f"| Change fingerprint | `{packet['change_fingerprint']}` |",
        f"| Control fingerprint | `{packet['control_fingerprint']}` |",
        f"| Changed files | {summary['changed']} total · {summary['production']} production · {summary['tests']} tests |",
        f"| Review result | {summary['blockers']} blocker(s) · {summary['human_review']} human prompt(s) · {summary['warnings']} warning(s) |",
        f"| Deterministic evidence | {summary['evidence_status']} |",
        f"| Human approvals | {summary['approval_status']} |",
        "",
    ]
    if packet.get("risk"):
        risk = packet["risk"]
        lines.extend(
            [
                "## Risk resolution",
                "",
                f"Selected **{risk['selected_risk_profile']}**; deterministic minimum **{risk['minimum_risk_profile']}**. Required execution profiles: `{', '.join(risk['required_execution_profiles'])}`.",
                "",
            ]
        )
    lines.extend(["## Evidence matrix", "", "| Profile | Status | Run |", "|---|---|---|"])
    if packet.get("evidence"):
        for item in packet["evidence"]:
            lines.append(
                f"| `{item['profile']}` | {item['status']} | `{item.get('run_id') or '—'}` |"
            )
    else:
        lines.append("| — | No required profile resolved | — |")
    lines.extend(
        ["", "## Human approval matrix", "", "| Approval | Status | Detail |", "|---|---|---|"]
    )
    approvals = packet.get("approvals", {})
    required = approvals.get("required", [])
    results = approvals.get("results", {})
    if required:
        for kind in required:
            result = results.get(kind, {}) if isinstance(results, dict) else {}
            errors = result.get("errors", []) if isinstance(result, dict) else []
            status = "current" if not errors else "missing_or_stale"
            detail = (
                "; ".join(str(value) for value in errors[:3])
                or "fingerprints match current review surface"
            )
            lines.append(f"| `{kind}` | {status} | {detail} |")
    else:
        lines.append("| — | none required | — |")
    lines.extend(["", "## Findings", ""])
    if not packet["findings"]:
        lines.append(
            "No automated findings. Human review is still required wherever the risk profile or behavior artifacts require it."
        )
    for finding in packet["findings"]:
        origin = "deterministic/heuristic" if finding.get("automated", True) else "human decision"
        lines.extend(
            [
                f"### {finding['severity'].upper()} · {finding['title']}",
                "",
                f"`{finding['code']}` · {origin}",
                "",
                finding["detail"],
                "",
                f"**Required action:** {finding['action']}",
            ]
        )
        if finding["paths"]:
            lines.extend(["", "Affected locations:", *[f"- `{path}`" for path in finding["paths"]]])
        lines.append("")
    lines.extend(
        [
            "## Reviewer decision record",
            "",
            "- Reviewer:",
            "- Decision: pending",
            "- Intent and behavior diff reviewed:",
            "- Expected-output/dependency/policy diffs reviewed:",
            "- Residual risk and rollback:",
            "- Evidence or approval links:",
            "",
            "## Changed files",
            "",
            *[f"- `{path}`" for path in packet["changed_files"]],
            "",
        ]
    )
    return "\n".join(lines)


def _html(packet: dict[str, Any]) -> str:
    summary = packet["summary"]
    decision_class = (
        "blocker" if summary["blockers"] else "review" if summary["human_review"] else "pass"
    )
    decision = (
        "Blocked"
        if summary["blockers"]
        else "Human review required"
        if summary["human_review"]
        else "Automated review clear"
    )
    cards = []
    for finding in packet["findings"]:
        paths = "".join(f"<li><code>{html.escape(path)}</code></li>" for path in finding["paths"])
        origin = "Automated signal" if finding.get("automated", True) else "Human decision"
        locations = (
            f"<details><summary>{len(finding['paths'])} affected location(s)</summary>"
            f"<ul>{paths}</ul></details>"
            if paths
            else ""
        )
        cards.append(
            f"""<article class="finding {html.escape(finding["severity"])}">
              <div class="finding-head"><span class="severity">{html.escape(finding["severity"].upper())}</span><div><h3>{html.escape(finding["title"])}</h3><code>{html.escape(finding["code"])}</code> · <small>{origin}</small></div></div>
              <p>{html.escape(finding["detail"])}</p>
              <div class="action"><strong>Required action</strong><p>{html.escape(finding["action"])}</p></div>
              {locations}
            </article>"""
        )
    changed = "".join(
        f"<li><code>{html.escape(path)}</code></li>" for path in packet["changed_files"]
    )
    risk = packet.get("risk") or {}
    evidence_rows = (
        "".join(
            f'<tr><td><code>{html.escape(str(item["profile"]))}</code></td><td><span class="status {html.escape(str(item["status"]))}">{html.escape(str(item["status"]).replace("_", " "))}</span></td><td><code>{html.escape(str(item.get("run_id") or "—"))}</code></td></tr>'
            for item in packet.get("evidence", [])
        )
        or '<tr><td colspan="3" class="muted">No required execution profile resolved.</td></tr>'
    )
    approvals = packet.get("approvals", {})
    approval_rows = []
    for kind in approvals.get("required", []):
        result = (
            approvals.get("results", {}).get(kind, {})
            if isinstance(approvals.get("results"), dict)
            else {}
        )
        errors = result.get("errors", []) if isinstance(result, dict) else []
        status = "current" if not errors else "missing_or_stale"
        detail = (
            "; ".join(str(value) for value in errors[:3])
            or "Fingerprints match the current review surface."
        )
        approval_rows.append(
            f'<tr><td><code>{html.escape(str(kind))}</code></td><td><span class="status {status}">{status.replace("_", " ")}</span></td><td>{html.escape(detail)}</td></tr>'
        )
    approval_rows_html = (
        "".join(approval_rows)
        or '<tr><td colspan="3" class="muted">No human approval record is required at this risk profile.</td></tr>'
    )
    generated = html.escape(str(packet["generated_at"]))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AQG review packet</title>
<style>
:root{{--bg:#080b10;--panel:#111722;--panel2:#0d121b;--muted:#9ba9bb;--text:#edf4fb;--line:#263246;--red:#ff7182;--amber:#ffd166;--blue:#78b7ff;--green:#5ee0a0;--cyan:#67e6dc;--shadow:0 18px 55px rgba(0,0,0,.24)}}
*{{box-sizing:border-box}}html{{color-scheme:dark}}body{{margin:0;background:radial-gradient(circle at 12% 0%,#172338 0,transparent 31%),var(--bg);color:var(--text);font:15px/1.58 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}main{{max-width:1180px;margin:auto;padding:44px 24px 96px}}h1{{font-size:clamp(34px,5vw,58px);letter-spacing:-.045em;margin:4px 0 10px}}h2{{font-size:22px;margin:0 0 16px}}h3{{margin:0 0 2px;font-size:17px}}p{{max-width:88ch}}code{{font-family:"SFMono-Regular",Consolas,monospace;color:#c5ddff;overflow-wrap:anywhere}}.eyebrow{{color:var(--cyan);text-transform:uppercase;letter-spacing:.16em;font-size:11px;font-weight:800}}.muted,small{{color:var(--muted)}}.hero{{display:grid;grid-template-columns:1.5fr .8fr;gap:22px;align-items:stretch;margin-bottom:24px}}.hero-copy,.decision,.panel,.finding{{background:linear-gradient(180deg,rgba(18,24,35,.96),rgba(13,18,27,.96));border:1px solid var(--line);border-radius:18px;box-shadow:var(--shadow)}}.hero-copy{{padding:28px}}.decision{{padding:28px;display:flex;flex-direction:column;justify-content:space-between;border-top:4px solid var(--green)}}.decision.blocker{{border-top-color:var(--red)}}.decision.review{{border-top-color:var(--amber)}}.decision strong{{font-size:26px;line-height:1.15}}.fingerprints{{display:grid;gap:6px;margin-top:18px;font-size:12px}}.metrics{{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin:18px 0 26px}}.metric{{background:var(--panel2);border:1px solid var(--line);border-radius:14px;padding:15px}}.metric b{{display:block;font-size:27px;line-height:1.1;margin-bottom:6px}}.metric span{{color:var(--muted);font-size:12px}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:16px 0}}.panel{{padding:22px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:11px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}th{{font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}}.status{{display:inline-flex;padding:3px 8px;border-radius:999px;background:#263246;font-size:11px}}.status.current,.status.current_pass{{background:rgba(94,224,160,.13);color:var(--green)}}.status.missing_or_stale{{background:rgba(255,113,130,.13);color:var(--red)}}.finding{{padding:22px;margin:14px 0;border-left:5px solid var(--blue)}}.finding.blocker{{border-left-color:var(--red)}}.finding.review{{border-left-color:var(--amber)}}.finding.warning{{border-left-color:var(--blue)}}.finding-head{{display:flex;gap:13px;align-items:flex-start}}.severity{{font-size:10px;letter-spacing:.12em;padding:4px 7px;border:1px solid var(--line);border-radius:6px;color:var(--muted)}}.action{{background:#0a0f17;border:1px solid var(--line);border-radius:12px;padding:13px 15px;margin-top:14px}}.action p{{margin:3px 0 0}}details{{margin-top:12px}}summary{{cursor:pointer;color:var(--blue)}}ul{{padding-left:22px}}.changed{{columns:2;column-gap:28px}}.changed li{{break-inside:avoid;margin:3px 0}}.review-record li{{margin:8px 0}}@media(max-width:900px){{.hero,.grid{{grid-template-columns:1fr}}.metrics{{grid-template-columns:repeat(3,1fr)}}.changed{{columns:1}}}}@media(max-width:560px){{main{{padding:24px 14px 70px}}.metrics{{grid-template-columns:repeat(2,1fr)}}.hero-copy,.decision,.panel,.finding{{border-radius:13px;padding:17px}}}}@media print{{:root{{--bg:#fff;--panel:#fff;--panel2:#fff;--muted:#4a5565;--text:#10141a;--line:#ccd3dc}}body{{background:#fff}}main{{max-width:none;padding:0}}.hero-copy,.decision,.panel,.finding,.metric{{box-shadow:none;break-inside:avoid}}code{{color:#173b66}}}}
</style></head><body><main>
<section class="hero"><div class="hero-copy"><div class="eyebrow">Agent Quality Gauntlet · review evidence</div><h1>AQG review packet</h1><p class="muted">Generated {generated} from the exact current revision, diff surface, and protected control plane.</p><div class="fingerprints"><span>Revision <code>{html.escape(str(packet["revision"]))}</code></span><span>Base <code>{html.escape(str(packet["base"]))}</code></span><span>Change <code>{html.escape(str(packet["change_fingerprint"]))}</code></span><span>Controls <code>{html.escape(str(packet["control_fingerprint"]))}</code></span></div></div><aside class="decision {decision_class}"><div class="eyebrow">Current decision</div><strong>{decision}</strong><p class="muted">{summary["blockers"]} blocker(s), {summary["human_review"]} human prompt(s), {summary["warnings"]} warning(s).</p></aside></section>
<section class="metrics"><div class="metric"><b>{summary["changed"]}</b><span>changed files</span></div><div class="metric"><b>{summary["production"]}</b><span>production</span></div><div class="metric"><b>{summary["tests"]}</b><span>tests</span></div><div class="metric"><b>{summary["blockers"]}</b><span>blockers</span></div><div class="metric"><b>{summary["human_review"]}</b><span>human prompts</span></div><div class="metric"><b>{summary["warnings"]}</b><span>warnings</span></div></section>
<section class="grid"><article class="panel"><div class="eyebrow">Risk</div><h2>{html.escape(str(risk.get("selected_risk_profile", "unresolved")).replace("_", " ")).title()}</h2><p>Deterministic minimum: <strong>{html.escape(str(risk.get("minimum_risk_profile", "unresolved")).replace("_", " "))}</strong></p><p>Required profiles: <code>{html.escape(", ".join(str(value) for value in risk.get("required_execution_profiles", [])) or "none")}</code></p></article><article class="panel"><div class="eyebrow">Evidence validity</div><h2>{html.escape(summary["evidence_status"].replace("_", " ")).title()}</h2><p>Human approvals: <strong>{html.escape(summary["approval_status"].replace("_", " "))}</strong></p><p class="muted">Evidence is reusable only while revision, change fingerprint, and control fingerprint remain unchanged.</p></article></section>
<section class="grid"><article class="panel"><div class="eyebrow">Deterministic profiles</div><h2>Evidence matrix</h2><table><thead><tr><th>Profile</th><th>Status</th><th>Run</th></tr></thead><tbody>{evidence_rows}</tbody></table></article><article class="panel"><div class="eyebrow">Human authority</div><h2>Approval matrix</h2><table><thead><tr><th>Approval</th><th>Status</th><th>Detail</th></tr></thead><tbody>{approval_rows_html}</tbody></table></article></section>
<section><div class="eyebrow">Review intelligence</div><h2>Findings</h2>{"".join(cards) or '<article class="panel"><p>No automated findings. Complete any risk-required human review before release.</p></article>'}</section>
<section class="panel review-record"><div class="eyebrow">Human decision</div><h2>Reviewer record</h2><ul><li>Reviewer:</li><li>Decision:</li><li>Behavior and expected-output diffs reviewed:</li><li>Residual risk and rollback:</li><li>Evidence / approval links:</li></ul></section>
<section class="panel"><div class="eyebrow">Scope</div><h2>Changed files</h2><ul class="changed">{changed or "<li>None</li>"}</ul></section>
</main></body></html>"""


def write_review_packet(root: Path, packet: dict[str, Any]) -> dict[str, str]:
    directory = root / ".aqg" / "review"
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "review.json"
    md_path = directory / "review.md"
    html_path = directory / "review.html"
    write_json(json_path, packet)
    md_path.write_text(_markdown(packet) + "\n", encoding="utf-8")
    html_path.write_text(_html(packet), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path), "html": str(html_path)}


def review_exit_code(packet: dict[str, Any]) -> int:
    return QUALITY_FAILURE if packet["summary"]["blockers"] else PASS
