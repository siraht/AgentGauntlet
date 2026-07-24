"""Review and evidence export helpers, including SARIF and GitHub summaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .util import atomic_write, read_json, utc_now, write_json


SEVERITY_LEVEL = {"blocker": "error", "review": "warning", "warning": "warning", "info": "note"}


def review_to_sarif(packet: dict[str, Any]) -> dict[str, Any]:
    rules: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    for finding in packet.get("findings", []):
        code = str(finding.get("code", "aqg-review"))
        rules.setdefault(
            code,
            {
                "id": code,
                "name": code.replace("-", " ").title(),
                "shortDescription": {"text": str(finding.get("title", code))},
                "fullDescription": {"text": str(finding.get("detail", ""))},
                "help": {"text": str(finding.get("action", "Review and resolve this finding."))},
                "defaultConfiguration": {"level": SEVERITY_LEVEL.get(str(finding.get("severity")), "warning")},
            },
        )
        paths = finding.get("paths") or [None]
        for path in paths:
            result: dict[str, Any] = {
                "ruleId": code,
                "level": SEVERITY_LEVEL.get(str(finding.get("severity")), "warning"),
                "message": {"text": f"{finding.get('title')}: {finding.get('detail')}"},
                "properties": {"automated": bool(finding.get("automated", True)), "action": finding.get("action")},
            }
            if path:
                result["locations"] = [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": str(path)},
                            "region": {"startLine": 1},
                        }
                    }
                ]
            results.append(result)
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Agent Quality Gauntlet Review",
                        "informationUri": "https://github.com/",
                        "semanticVersion": "2.0.0",
                        "rules": list(rules.values()),
                    }
                },
                "results": results,
                "properties": {"generatedAt": packet.get("generated_at", utc_now()), "base": packet.get("base")},
            }
        ],
    }


def write_review_sarif(root: Path, packet: dict[str, Any]) -> Path:
    path = root / ".aqg" / "review" / "review.sarif"
    write_json(path, review_to_sarif(packet))
    return path


def github_summary(packet: dict[str, Any]) -> str:
    summary = packet.get("summary", {})
    lines = [
        "# Agent Quality Gauntlet review",
        "",
        f"- **Automated blockers:** {summary.get('blockers', 0)}",
        f"- **Human review prompts:** {summary.get('human_review', 0)}",
        f"- **Changed files:** {summary.get('changed_files', 0)}",
        f"- **Evidence status:** {summary.get('evidence_status', 'unknown')}",
        f"- **Revision:** `{packet.get('revision', 'unknown')}`",
        f"- **Change fingerprint:** `{str(packet.get('change_fingerprint', 'unknown'))[:24]}`",
        f"- **Control fingerprint:** `{str(packet.get('control_fingerprint', 'unknown'))[:24]}`",
        "",
    ]
    evidence = packet.get("evidence", [])
    if evidence:
        lines.extend(["## Required evidence", "", "| Profile | Status | Run |", "| --- | --- | --- |"] )
        for item in evidence:
            lines.append(f"| `{item.get('profile')}` | {item.get('status')} | `{item.get('run_id') or '—'}` |")
        lines.append("")
    for severity in ("blocker", "review", "info"):
        findings = [item for item in packet.get("findings", []) if item.get("severity") == severity]
        if not findings:
            continue
        lines.extend([f"## {severity.title()} findings", ""])
        for finding in findings:
            lines.append(f"### {finding.get('title')}")
            lines.append(str(finding.get("detail", "")))
            if finding.get("paths"):
                lines.append("Affected: " + ", ".join(f"`{path}`" for path in finding["paths"]))
            lines.append("Action: " + str(finding.get("action", "Review and resolve.")))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_github_summary(root: Path, packet: dict[str, Any], destination: Path | None = None) -> Path:
    path = destination or root / ".aqg" / "review" / "github-summary.md"
    atomic_write(path, github_summary(packet))
    return path


def latest_evidence_bundle(root: Path) -> dict[str, Any]:
    latest = read_json(root / ".aqg" / "latest.json", default={})
    review = read_json(root / ".aqg" / "review" / "review.json", default={})
    run_id = latest.get("run_id")
    gates: dict[str, Any] = {}
    if run_id:
        gate_dir = root / ".aqg" / "runs" / str(run_id) / "gates"
        if gate_dir.exists():
            for path in sorted(gate_dir.glob("*.json")):
                gates[path.stem] = read_json(path)
    return {"schema_version": 1, "generated_at": utc_now(), "latest": latest, "review": review, "gates": gates}
