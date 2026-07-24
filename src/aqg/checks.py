"""Dependency-free integrity, secret, Gherkin, and traceability checks."""

from __future__ import annotations

from dataclasses import dataclass, asdict
import math
from pathlib import Path
import re
from typing import Any, Iterable

from .constants import DEFAULT_EXCLUDES
from .project import excludes, source_paths, test_paths
from .util import git_diff, iter_files, matches_any, read_json, sha256_file, write_json


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
        any(part in {"test", "tests", "spec", "specs", "__tests__", "e2e", "acceptance"} for part in parts)
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


def scan_test_integrity(root: Path, project: dict[str, Any]) -> dict[str, Any]:
    files = _test_files(root, project)
    findings: list[Finding] = []
    tests = 0
    focused_patterns = [
        (re.compile(r"\b(?:describe|context|it|test)\.only\s*\("), "focused-test", "Focused JavaScript test marker is committed."),
        (re.compile(r"\b(?:fdescribe|fit)\s*\("), "focused-test", "Focused JavaScript test alias is committed."),
    ]
    skip_patterns = [
        (re.compile(r"\b(?:describe|context|it|test)\.skip\s*\("), "skipped-test", "Skipped JavaScript test is committed."),
        (re.compile(r"\btest\.todo\s*\("), "todo-test", "A TODO JavaScript test does not execute."),
        (re.compile(r"@pytest\.mark\.(?:skip|skipif|xfail)\b"), "skipped-test", "Skipped or expected-failure pytest marker is committed."),
        (re.compile(r"@(?:unittest\.)?skip(?:If|Unless)?\b"), "skipped-test", "Skipped unittest is committed."),
        (re.compile(r"pytest\.(?:skip|xfail)\s*\("), "runtime-skip", "A runtime pytest skip or xfail can hide unexecuted behavior."),
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
                fingerprint = f"{code}:{rel}:{line}:{match.group(0)}"
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
    ("generic-secret-assignment", re.compile(r"(?i)\b(?:api[_-]?key|secret|token|password|passwd)\s*[:=]\s*['\"]([A-Za-z0-9_./+=:-]{16,})['\"]")),
]


def scan_secrets(root: Path, project: dict[str, Any], *, changed_only: bool = False) -> dict[str, Any]:
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
        candidates = [(path, line_no, line) for path, lines in content_by_file.items() for line_no, line in lines]
    else:
        suffixes = {
            ".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".json", ".toml", ".yaml", ".yml",
            ".env", ".ini", ".cfg", ".conf", ".html", ".css", ".md", ".sh",
        }
        candidates = []
        for path in iter_files(root, suffixes, excludes(project)):
            rel = path.relative_to(root).as_posix()
            if rel.startswith("quality/baselines/") or rel.startswith("docs/"):
                continue
            for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
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


def parse_feature(path: Path) -> tuple[dict[str, Any] | None, list[Finding]]:
    findings: list[Finding] = []
    feature: dict[str, Any] = {"name": "", "background": [], "scenarios": []}
    scenario: dict[str, Any] | None = None
    section = "none"
    headers: list[str] | None = None
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for line_no, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("Feature:"):
            if feature["name"]:
                findings.append(Finding("multiple-features", "error", "One file must contain exactly one Feature declaration.", str(path), line_no))
            feature["name"] = line.removeprefix("Feature:").strip()
            section = "feature"
            continue
        if line == "Background:":
            section = "background"
            scenario = None
            continue
        if line.startswith("Scenario Outline:") or line.startswith("Scenario:"):
            name = line.split(":", 1)[1].strip()
            scenario = {"name": name, "steps": [], "examples": []}
            feature["scenarios"].append(scenario)
            section = "scenario"
            headers = None
            continue
        if line == "Examples:":
            if scenario is None:
                findings.append(Finding("examples-outside-scenario", "error", "Examples must be inside a scenario.", str(path), line_no))
            section = "examples"
            headers = None
            continue
        if line.startswith("|"):
            if section != "examples" or scenario is None:
                findings.append(Finding("table-outside-examples", "error", "Table rows are allowed only inside Examples.", str(path), line_no))
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if headers is None:
                headers = cells
                if len(set(headers)) != len(headers):
                    findings.append(Finding("duplicate-example-header", "error", "Examples headers must be unique.", str(path), line_no))
            elif len(cells) != len(headers):
                findings.append(Finding("example-width", "error", "Examples row width does not match the header.", str(path), line_no))
            else:
                scenario["examples"].append(dict(zip(headers, cells, strict=True)))
            continue
        step = STEP_RE.match(line)
        if step:
            payload = {"keyword": step.group(1), "text": step.group(2), "line": line_no, "parameters": PLACEHOLDER_RE.findall(step.group(2))}
            if section == "background":
                feature["background"].append(payload)
            elif scenario is not None:
                scenario["steps"].append(payload)
            else:
                findings.append(Finding("step-outside-scenario", "error", "Step is outside Background or Scenario.", str(path), line_no))
            continue
        findings.append(
            Finding(
                "unsupported-gherkin",
                "error",
                f"Unsupported or misspelled Gherkin syntax: {line}",
                str(path),
                line_no,
                "Use the deterministic subset Feature, Background, Scenario, Scenario Outline, Examples, Given, When, Then, and And.",
            )
        )
    if not feature["name"]:
        findings.append(Finding("missing-feature", "error", "Feature declaration is required.", str(path), 1))
    if not feature["scenarios"]:
        findings.append(Finding("missing-scenario", "error", "At least one scenario is required.", str(path), 1))
    for scenario in feature["scenarios"]:
        keywords = [step["keyword"] for step in scenario["steps"]]
        if "When" not in keywords or "Then" not in keywords:
            findings.append(Finding("incomplete-scenario", "error", f"Scenario {scenario['name']!r} needs at least one When and Then.", str(path)))
        placeholders = {parameter for step in [*feature["background"], *scenario["steps"]] for parameter in step["parameters"]}
        example_keys = set().union(*(row.keys() for row in scenario["examples"])) if scenario["examples"] else set()
        missing = placeholders - example_keys
        unused = example_keys - placeholders
        for key in sorted(missing):
            findings.append(Finding("missing-example-value", "error", f"Placeholder <{key}> has no Examples column in scenario {scenario['name']!r}.", str(path)))
        for key in sorted(unused):
            findings.append(Finding("unused-example-value", "error", f"Examples column {key!r} is not connected to a step in scenario {scenario['name']!r}.", str(path)))
    return feature, findings


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
                try:
                    finding.path = Path(finding.path).relative_to(root).as_posix()
                except ValueError:
                    pass
        findings.extend(file_findings)
        if feature:
            parsed.append({"path": path.relative_to(root).as_posix(), "feature": feature})
            for scenario in feature["scenarios"]:
                for step in [*feature["background"], *scenario["steps"]]:
                    normalized = PLACEHOLDER_RE.sub("<_>", step["text"].lower())
                    normalized_steps.setdefault(normalized, []).append(f"{path.relative_to(root)}:{step['line']}")
    for text, locations in normalized_steps.items():
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
    active_specs = [path for path in (root / "feature-spec").glob("*.md") if not path.name.startswith("TODO.")] if (root / "feature-spec").exists() else []
    test_content = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in _test_files(root, project))
    findings: list[Finding] = []
    for spec in active_specs:
        name = spec.stem
        if name.startswith("EXAMPLE."):
            continue
        if name not in test_content:
            findings.append(
                Finding(
                    "unmapped-active-spec",
                    "warning",
                    f"Active feature specification {name!r} has no test annotation or reference.",
                    spec.relative_to(root).as_posix(),
                    remediation=f"Reference the most specific feature with `Feature-Spec: {name}` in an executable test.",
                    fingerprint=f"unmapped-active-spec:{name}",
                )
            )
    return {
        "active_specs": len(active_specs),
        "findings": [finding.as_dict() for finding in findings],
        "warnings": len(findings),
    }


def crap_score(complexity: int, coverage_fraction: float) -> float:
    return complexity**2 * (1.0 - coverage_fraction) ** 3 + complexity
