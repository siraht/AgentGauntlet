"""Dependency-free integrity, secret, Gherkin, and traceability checks."""

from __future__ import annotations

import contextlib
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .project import excludes
from .util import git_diff, iter_files, read_json, write_json

TEST_SUFFIXES = {".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"}
CODE_SUFFIXES = TEST_SUFFIXES


@dataclass(slots=True)
class Finding:
    code: str
    severity: str
    message: str
    path: str | None = None
    line: int | None = None
    remediation: str | None = None
    fingerprint: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_test_path(rel: str) -> bool:
    lower = rel.lower()
    name = Path(rel).name.lower()
    parts = [part.lower() for part in Path(rel).parts]
    return (
        any(
            part in {"test", "tests", "spec", "specs", "__tests__", "e2e", "acceptance"}
            for part in parts
        )
        or bool(re.search(r"(?:^|[._-])(test|spec)(?:[._-]|$)", name))
        or lower.endswith("_test.py")
        or name.startswith("test_")
    )


def _source_file_count(root: Path, project: dict[str, Any]) -> int:
    return len(
        [
            path
            for path in iter_files(root, CODE_SUFFIXES, excludes(project))
            if not _is_test_path(path.relative_to(root).as_posix())
        ]
    )


def _test_files(root: Path, project: dict[str, Any]) -> list[Path]:
    return [
        path
        for path in iter_files(root, TEST_SUFFIXES, excludes(project))
        if _is_test_path(path.relative_to(root).as_posix())
    ]


def _baseline_fingerprints(root: Path, name: str) -> set[str]:
    path = root / "quality" / "baselines" / f"{name}.json"
    if not path.exists():
        return set()
    payload = read_json(path, default={})
    values = payload.get("fingerprints", []) if isinstance(payload, dict) else []
    return {str(value) for value in values}


def _test_anchor(content: str, position: int) -> str:
    patterns = (
        re.compile(r"^\s*(?:async\s+)?def\s+(test_[A-Za-z0-9_]+)\s*\(", re.MULTILINE),
        re.compile(r"^\s*class\s+(Test[A-Za-z0-9_]+)\b", re.MULTILINE),
        re.compile(r"\b(?:it|test)(?:\.(?:skip|only|todo))?\s*\(\s*['\"]([^'\"]+)['\"]"),
    )
    candidates = [
        (match.start(), match.group(1))
        for pattern in patterns
        for match in pattern.finditer(content)
    ]
    line_start = content.rfind("\n", 0, position) + 1
    decorated = content[line_start:position].lstrip().startswith("@") or content[
        line_start:
    ].lstrip().startswith("@")
    after = [candidate for candidate in candidates if candidate[0] > position]
    if decorated and after:
        return min(after, key=lambda candidate: candidate[0])[1]
    before = [candidate for candidate in candidates if candidate[0] <= position]
    if before:
        return max(before, key=lambda candidate: candidate[0])[1]
    return min(after, key=lambda candidate: candidate[0])[1] if after else "module"


def scan_test_integrity(root: Path, project: dict[str, Any]) -> dict[str, Any]:
    files = _test_files(root, project)
    findings: list[Finding] = []
    tests = 0
    focused_patterns = [
        (
            re.compile(r"\b(?:describe|context|it|test)\.only\s*\("),
            "focused-test",
            "Focused JavaScript test marker is committed.",
        ),
        (
            re.compile(r"\b(?:fdescribe|fit)\s*\("),
            "focused-test",
            "Focused JavaScript test alias is committed.",
        ),
    ]
    skip_patterns = [
        (
            re.compile(r"\b(?:describe|context|it|test)\.skip\s*\("),
            "skipped-test",
            "Skipped JavaScript test is committed.",
        ),
        (re.compile(r"\btest\.todo\s*\("), "todo-test", "A TODO JavaScript test does not execute."),
        (
            re.compile(r"@pytest\.mark\.(?:skip|skipif|xfail)\b"),
            "skipped-test",
            "Skipped or expected-failure pytest marker is committed.",
        ),
        (
            re.compile(r"@(?:unittest\.)?skip(?:If|Unless)?\b"),
            "skipped-test",
            "Skipped unittest is committed.",
        ),
        (
            re.compile(r"pytest\.(?:skip|xfail)\s*\("),
            "runtime-skip",
            "A runtime pytest skip or xfail can hide unexecuted behavior.",
        ),
    ]
    test_patterns = [
        re.compile(r"\b(?:it|test)\s*\("),
        re.compile(r"^\s*(?:async\s+)?def\s+test_[A-Za-z0-9_]+\s*\(", re.MULTILINE),
        re.compile(r"^\s*class\s+Test[A-Za-z0-9_]+\b", re.MULTILINE),
    ]
    for path in files:
        rel = path.relative_to(root).as_posix()
        content = path.read_text(encoding="utf-8", errors="replace")
        file_tests = sum(len(pattern.findall(content)) for pattern in test_patterns)
        tests += file_tests
        for pattern, code, message in [*focused_patterns, *skip_patterns]:
            for match in pattern.finditer(content):
                line = content.count("\n", 0, match.start()) + 1
                anchor = _test_anchor(content, match.start())
                fingerprint = f"{code}:{rel}:{anchor}:{match.group(0)}"
                findings.append(
                    Finding(
                        code=code,
                        severity="error" if code == "focused-test" else "warning",
                        message=message,
                        path=rel,
                        line=line,
                        remediation="Remove the marker, make the condition strict and temporary, or add a reviewed baseline waiver.",
                        fingerprint=fingerprint,
                    )
                )
        if re.search(r"\b(?:pass|return)\s*(?:#.*)?$", content, re.MULTILINE) and tests == 0:
            findings.append(
                Finding(
                    code="empty-test-module",
                    severity="warning",
                    message="Test-named module appears to contain no executable tests.",
                    path=rel,
                    fingerprint=f"empty-test-module:{rel}",
                )
            )
    baseline = _baseline_fingerprints(root, "test-integrity")
    for finding in findings:
        if finding.fingerprint in baseline and finding.severity != "error":
            finding.severity = "baseline"
    source_count = _source_file_count(root, project)
    if source_count and not files:
        findings.append(
            Finding(
                code="no-test-files",
                severity="error",
                message=f"{source_count} production source files were found, but no test files were discovered.",
                remediation="Create executable tests or correct quality/project.json test paths.",
                fingerprint="no-test-files",
            )
        )
    elif source_count and tests == 0:
        findings.append(
            Finding(
                code="no-test-cases",
                severity="error",
                message="Test files exist, but AQG could not identify any executable test cases.",
                remediation="Verify test discovery with the project runner and correct naming/configuration.",
                fingerprint="no-test-cases",
            )
        )
    return {
        "schema_version": 1,
        "source_files": source_count,
        "test_files": len(files),
        "test_case_markers": tests,
        "findings": [finding.as_dict() for finding in findings],
        "errors": sum(finding.severity == "error" for finding in findings),
        "warnings": sum(finding.severity == "warning" for finding in findings),
        "baselined": sum(finding.severity == "baseline" for finding in findings),
    }


def write_test_integrity_baseline(root: Path, report: dict[str, Any]) -> Path:
    path = root / "quality" / "baselines" / "test-integrity.json"
    fingerprints = [
        finding["fingerprint"]
        for finding in report.get("findings", [])
        if finding.get("fingerprint") and finding.get("code") != "focused-test"
    ]
    write_json(path, {"schema_version": 1, "fingerprints": sorted(set(fingerprints))})
    return path


SECRET_PATTERNS = [
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{30,}\b")),
    ("openai-key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    (
        "generic-secret-assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret|token|password|passwd)\s*[:=]\s*['\"]([A-Za-z0-9_./+=:-]{16,})['\"]"
        ),
    ),
]


def scan_secrets(
    root: Path, project: dict[str, Any], *, changed_only: bool = False
) -> dict[str, Any]:
    findings: list[Finding] = []
    if changed_only:
        content_by_file: dict[str, list[tuple[int, str]]] = {}
        current_path = ""
        current_line = 0
        for line in git_diff(root, unified=0).splitlines():
            if line.startswith("+++ b/"):
                current_path = line[6:]
            elif line.startswith("@@"):
                match = re.search(r"\+(\d+)", line)
                current_line = int(match.group(1)) if match else 0
            elif line.startswith("+") and not line.startswith("+++"):
                content_by_file.setdefault(current_path, []).append((current_line, line[1:]))
                current_line += 1
            elif not line.startswith("-"):
                current_line += 1
        candidates = [
            (path, line_no, line)
            for path, lines in content_by_file.items()
            for line_no, line in lines
        ]
    else:
        suffixes = {
            ".py",
            ".js",
            ".jsx",
            ".mjs",
            ".cjs",
            ".ts",
            ".tsx",
            ".json",
            ".toml",
            ".yaml",
            ".yml",
            ".env",
            ".ini",
            ".cfg",
            ".conf",
            ".html",
            ".css",
            ".md",
            ".sh",
        }
        candidates = []
        for path in iter_files(root, suffixes, excludes(project)):
            rel = path.relative_to(root).as_posix()
            if rel.startswith("quality/baselines/") or rel.startswith("docs/"):
                continue
            for line_no, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
            ):
                candidates.append((rel, line_no, line))
    allowlist_path = root / "quality" / "waivers" / "secrets.json"
    allowlist = read_json(allowlist_path, default={}) if allowlist_path.exists() else {}
    allowed = set(allowlist.get("fingerprints", [])) if isinstance(allowlist, dict) else set()
    for rel, line_no, line in candidates:
        if "AQG_ALLOW_SECRET" in line:
            continue
        for code, pattern in SECRET_PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            fingerprint = f"{code}:{rel}:{line_no}:{match.group(0)[:16]}"
            severity = "baseline" if fingerprint in allowed else "error"
            findings.append(
                Finding(
                    code=code,
                    severity=severity,
                    message="Potential credential or private key material is present.",
                    path=rel,
                    line=line_no,
                    remediation="Remove and rotate the secret. Store a narrow fingerprint waiver only for a proven false positive.",
                    fingerprint=fingerprint,
                )
            )
    return {
        "schema_version": 1,
        "changed_only": changed_only,
        "findings": [finding.as_dict() for finding in findings],
        "errors": sum(finding.severity == "error" for finding in findings),
        "baselined": sum(finding.severity == "baseline" for finding in findings),
    }


STEP_RE = re.compile(r"^(Given|When|Then|And)\s+(.+)$")
PLACEHOLDER_RE = re.compile(r"<([A-Za-z0-9_]+)>")
_UNSUPPORTED_GHERKIN_REMEDIATION = (
    "Use the deterministic subset Feature, Background, Scenario, Scenario Outline, "
    "Examples, Given, When, Then, and And."
)


@dataclass(slots=True)
class _FeatureParseState:
    feature: dict[str, Any]
    scenario: dict[str, Any] | None = None
    section: str = "none"
    headers: list[str] | None = None


def _empty_feature() -> dict[str, Any]:
    return {"name": "", "background": [], "scenarios": []}


def _new_scenario(name: str) -> dict[str, Any]:
    return {"name": name, "steps": [], "examples": []}


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip("|").split("|")]


def _step_payload(match: re.Match[str], line_no: int) -> dict[str, Any]:
    text = match.group(2)
    return {
        "keyword": match.group(1),
        "text": text,
        "line": line_no,
        "parameters": PLACEHOLDER_RE.findall(text),
    }


def _apply_feature_declaration(
    line: str,
    line_no: int,
    state: _FeatureParseState,
    findings: list[Finding],
    path: Path,
) -> None:
    if state.feature["name"]:
        findings.append(
            Finding(
                "multiple-features",
                "error",
                "One file must contain exactly one Feature declaration.",
                str(path),
                line_no,
            )
        )
    state.feature["name"] = line.removeprefix("Feature:").strip()


def _apply_scenario_declaration(line: str, state: _FeatureParseState) -> None:
    name = line.split(":", 1)[1].strip()
    state.scenario = _new_scenario(name)
    state.feature["scenarios"].append(state.scenario)
    # Exit Background/Examples modes. Labels "feature"/"scenario" are never read.
    state.section = "none"


def _apply_examples_declaration(
    line_no: int,
    state: _FeatureParseState,
    findings: list[Finding],
    path: Path,
) -> None:
    if state.scenario is None:
        findings.append(
            Finding(
                "examples-outside-scenario",
                "error",
                "Examples must be inside a scenario.",
                str(path),
                line_no,
            )
        )
    state.section = "examples"
    state.headers = None


def _ingest_examples_row(
    line: str,
    line_no: int,
    state: _FeatureParseState,
    findings: list[Finding],
    path: Path,
) -> None:
    if state.section != "examples" or state.scenario is None:
        findings.append(
            Finding(
                "table-outside-examples",
                "error",
                "Table rows are allowed only inside Examples.",
                str(path),
                line_no,
            )
        )
        return
    cells = _table_cells(line)
    if state.headers is None:
        state.headers = cells
        if len(set(state.headers)) != len(state.headers):
            findings.append(
                Finding(
                    "duplicate-example-header",
                    "error",
                    "Examples headers must be unique.",
                    str(path),
                    line_no,
                )
            )
        return
    if len(cells) != len(state.headers):
        findings.append(
            Finding(
                "example-width",
                "error",
                "Examples row width does not match the header.",
                str(path),
                line_no,
            )
        )
        return
    # Width is validated above; pair by index (equivalent to zip of equal-length sequences).
    state.scenario["examples"].append(
        {state.headers[index]: cells[index] for index in range(len(state.headers))}
    )


def _append_step(
    payload: dict[str, Any],
    line_no: int,
    state: _FeatureParseState,
    findings: list[Finding],
    path: Path,
) -> None:
    if state.section == "background":
        state.feature["background"].append(payload)
        return
    if state.scenario is not None:
        state.scenario["steps"].append(payload)
        return
    findings.append(
        Finding(
            "step-outside-scenario",
            "error",
            "Step is outside Background or Scenario.",
            str(path),
            line_no,
        )
    )


def _process_feature_line(
    line: str,
    line_no: int,
    state: _FeatureParseState,
    findings: list[Finding],
    path: Path,
) -> None:
    if line.startswith("Feature:"):
        _apply_feature_declaration(line, line_no, state, findings, path)
        return
    if line == "Background:":
        state.section = "background"
        state.scenario = None
        return
    if line.startswith("Scenario Outline:") or line.startswith("Scenario:"):
        _apply_scenario_declaration(line, state)
        return
    if line == "Examples:":
        _apply_examples_declaration(line_no, state, findings, path)
        return
    if line.startswith("|"):
        _ingest_examples_row(line, line_no, state, findings, path)
        return
    step = STEP_RE.match(line)
    if step:
        _append_step(_step_payload(step, line_no), line_no, state, findings, path)
        return
    findings.append(
        Finding(
            "unsupported-gherkin",
            "error",
            f"Unsupported or misspelled Gherkin syntax: {line}",
            str(path),
            line_no,
            _UNSUPPORTED_GHERKIN_REMEDIATION,
        )
    )


def _scenario_placeholders(feature: dict[str, Any], scenario: dict[str, Any]) -> set[str]:
    return {
        parameter
        for step in [*feature["background"], *scenario["steps"]]
        for parameter in step["parameters"]
    }


def _example_keys(scenario: dict[str, Any]) -> set[str]:
    if not scenario["examples"]:
        return set()
    return set().union(*(row.keys() for row in scenario["examples"]))


def _validate_scenario(
    feature: dict[str, Any],
    scenario: dict[str, Any],
    findings: list[Finding],
    path: Path,
) -> None:
    keywords = [step["keyword"] for step in scenario["steps"]]
    if "When" not in keywords or "Then" not in keywords:
        findings.append(
            Finding(
                "incomplete-scenario",
                "error",
                f"Scenario {scenario['name']!r} needs at least one When and Then.",
                str(path),
            )
        )
    placeholders = _scenario_placeholders(feature, scenario)
    example_keys = _example_keys(scenario)
    for key in sorted(placeholders - example_keys):
        findings.append(
            Finding(
                "missing-example-value",
                "error",
                f"Placeholder <{key}> has no Examples column in scenario {scenario['name']!r}.",
                str(path),
            )
        )
    for key in sorted(example_keys - placeholders):
        findings.append(
            Finding(
                "unused-example-value",
                "error",
                f"Examples column {key!r} is not connected to a step in scenario {scenario['name']!r}.",
                str(path),
            )
        )


def _validate_parsed_feature(
    feature: dict[str, Any],
    findings: list[Finding],
    path: Path,
) -> None:
    if not feature["name"]:
        findings.append(
            Finding("missing-feature", "error", "Feature declaration is required.", str(path), 1)
        )
    if not feature["scenarios"]:
        findings.append(
            Finding("missing-scenario", "error", "At least one scenario is required.", str(path), 1)
        )
    for scenario in feature["scenarios"]:
        _validate_scenario(feature, scenario, findings, path)


def parse_feature(path: Path) -> tuple[dict[str, Any] | None, list[Finding]]:
    findings: list[Finding] = []
    state = _FeatureParseState(feature=_empty_feature())
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line_no, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        _process_feature_line(line, line_no, state, findings, path)
    _validate_parsed_feature(state.feature, findings, path)
    return state.feature, findings


def lint_features(root: Path) -> dict[str, Any]:
    feature_dir = root / "features"
    files = sorted(feature_dir.rglob("*.feature")) if feature_dir.exists() else []
    findings: list[Finding] = []
    parsed: list[dict[str, Any]] = []
    normalized_steps: dict[str, list[str]] = {}
    for path in files:
        feature, file_findings = parse_feature(path)
        for finding in file_findings:
            if finding.path:
                with contextlib.suppress(ValueError):
                    finding.path = Path(finding.path).relative_to(root).as_posix()
        findings.extend(file_findings)
        if feature:
            parsed.append({"path": path.relative_to(root).as_posix(), "feature": feature})
            for scenario in feature["scenarios"]:
                for step in [*feature["background"], *scenario["steps"]]:
                    normalized = PLACEHOLDER_RE.sub("<_>", step["text"].lower())
                    normalized_steps.setdefault(normalized, []).append(
                        f"{path.relative_to(root)}:{step['line']}"
                    )
    for _text, locations in normalized_steps.items():
        if len(locations) > 1 and len(set(locations)) > 1:
            # Reuse is normal; only repeated locations inside one file/scenario are actionable elsewhere.
            pass
    return {
        "schema_version": 1,
        "feature_files": len(files),
        "features": parsed,
        "findings": [finding.as_dict() for finding in findings],
        "errors": sum(finding.severity == "error" for finding in findings),
        "warnings": sum(finding.severity == "warning" for finding in findings),
    }


def test_feature_traceability(root: Path, project: dict[str, Any]) -> dict[str, Any]:
    active_specs = (
        [
            path
            for path in (root / "feature-spec").glob("*.md")
            if not path.name.startswith(("README", "EXAMPLE", "TODO."))
        ]
        if (root / "feature-spec").exists()
        else []
    )
    requirement_pattern = re.compile(r"^\s*-\s+`([A-Z][A-Z0-9_-]+)`\s+", re.MULTILINE)
    bullet_pattern = re.compile(r"^\s*-\s+.+\bMUST\b", re.MULTILINE)
    annotation_pattern = re.compile(
        r"Feature-Spec:\s*([A-Za-z0-9_.-]+)([^\r\n]*)",
    )
    identifier_pattern = re.compile(r"\b[A-Z][A-Z0-9]+(?:-[A-Z0-9]+){2,}\b")
    annotations: dict[str, set[str]] = {}
    annotation_locations: dict[tuple[str, str], str] = {}
    for path in _test_files(root, project):
        relative = path.relative_to(root).as_posix()
        content = path.read_text(encoding="utf-8", errors="ignore")
        for match in annotation_pattern.finditer(content):
            name = match.group(1)
            for identifier in identifier_pattern.findall(match.group(2)):
                annotations.setdefault(name, set()).add(identifier)
                annotation_locations[(name, identifier)] = relative
    findings: list[Finding] = []
    requirements = 0
    mapped = 0
    known: set[tuple[str, str]] = set()
    globally_seen: dict[str, str] = {}
    for spec in active_specs:
        name = spec.stem
        content = spec.read_text(encoding="utf-8", errors="replace")
        declared = requirement_pattern.findall(content)
        requirements += len(declared)
        for identifier in declared:
            known.add((name, identifier))
            other = globally_seen.get(identifier)
            if other and other != name:
                findings.append(
                    Finding(
                        "duplicate-requirement-id",
                        "warning",
                        f"Requirement identifier {identifier!r} is also declared by {other!r}.",
                        spec.relative_to(root).as_posix(),
                        remediation="Assign one globally unique stable identifier to each active requirement.",
                        fingerprint=f"duplicate-requirement-id:{identifier}",
                    )
                )
            globally_seen[identifier] = name
            if identifier in annotations.get(name, set()):
                mapped += 1
                continue
            findings.append(
                Finding(
                    "unmapped-active-requirement",
                    "warning",
                    f"Active requirement {identifier!r} in {name!r} has no exact test mapping.",
                    spec.relative_to(root).as_posix(),
                    remediation=(
                        f"Add `Feature-Spec: {name} {identifier}` to executable evidence "
                        "that proves this requirement."
                    ),
                    fingerprint=f"unmapped-active-requirement:{name}:{identifier}",
                )
            )
        if not declared and bullet_pattern.search(content):
            findings.append(
                Finding(
                    "requirement-id-missing",
                    "warning",
                    f"Active feature specification {name!r} has MUST requirements without stable IDs.",
                    spec.relative_to(root).as_posix(),
                    remediation="Prefix each active requirement with a stable backticked identifier.",
                    fingerprint=f"requirement-id-missing:{name}",
                )
            )
    for name, identifiers in annotations.items():
        for identifier in identifiers:
            if (name, identifier) in known:
                continue
            findings.append(
                Finding(
                    "unknown-requirement-reference",
                    "warning",
                    f"Test mapping references undefined requirement {name} {identifier}.",
                    annotation_locations[(name, identifier)],
                    remediation="Correct the identifier or add the active requirement before claiming coverage.",
                    fingerprint=f"unknown-requirement-reference:{name}:{identifier}",
                )
            )
    findings.sort(key=lambda finding: (finding.code, finding.fingerprint or ""))
    return {
        "active_specs": len(active_specs),
        "requirements": requirements,
        "mapped_requirements": mapped,
        "findings": [finding.as_dict() for finding in findings],
        "warnings": len(findings),
    }


def crap_score(complexity: int, coverage_fraction: float) -> float:
    return complexity**2 * (1.0 - coverage_fraction) ** 3 + complexity
