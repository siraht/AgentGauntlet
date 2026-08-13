#!/usr/bin/env python3
"""Verify that release authority is exact-tag, base-bound high-council evidence."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

TRUSTED_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TRUSTED_ROOT / "src"))

from aqg.council import ROLES  # noqa: E402
from aqg.council_service import report_council  # noqa: E402
from aqg.errors import ConfigurationError  # noqa: E402
from aqg.util import change_fingerprint, control_fingerprint  # noqa: E402

_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_TAG = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+(?:[.-][0-9A-Za-z.-]+)?$")


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "git command failed"
        raise ConfigurationError(detail)
    return completed.stdout.strip()


def _identity_errors(subject: Path, tag: str, comparison_sha: str) -> tuple[str, list[str]]:
    errors: list[str] = []
    if not _TAG.fullmatch(tag):
        errors.append("release tag must use vX.Y.Z syntax")
    if not _COMMIT.fullmatch(comparison_sha):
        errors.append("comparison revision must be a full lowercase Git commit SHA")
    if errors:
        return "", errors
    revision = _git(subject, "rev-parse", "HEAD")
    tagged = _git(subject, "rev-parse", f"refs/tags/{tag}^{{commit}}")
    if revision != tagged:
        errors.append("subject HEAD does not match the exact release tag")
    if comparison_sha == revision:
        errors.append("comparison revision must predate the release candidate")
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", comparison_sha, revision],
        cwd=subject,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        errors.append("comparison revision is not an ancestor of the release candidate")
    if _git(subject, "status", "--porcelain", "--untracked-files=no"):
        errors.append("release subject has tracked working-tree changes")
    return revision, errors


def _council_errors(
    report: dict[str, Any],
    *,
    revision: str,
    comparison_sha: str,
    subject: Path,
) -> list[str]:
    scope = report.get("scope", {})
    expected = {
        "revision": revision,
        "base_revision": comparison_sha,
        "change_fingerprint": change_fingerprint(subject, comparison_sha),
        "control_fingerprint": control_fingerprint(subject),
    }
    checks = (
        (report.get("tier") == "high", "council evidence is not high tier"),
        (report.get("purpose") == "candidate", "council purpose is not the release candidate"),
        (report.get("status") == "advisory_clear", "council did not reach advisory_clear"),
        (report.get("complete") is True, "council evidence is incomplete"),
        (not report.get("blockers"), "council evidence contains blockers"),
        (report.get("dissent", {}).get("present") is False, "council evidence contains dissent"),
        (not report.get("incomplete_reasons"), "council evidence has incomplete reasons"),
        (set(report.get("covered_roles", [])) == set(ROLES), "council does not cover every role"),
        (
            len(set(report.get("provider_groups", []))) >= 3,
            "council has fewer than three provider groups",
        ),
        (scope == expected, "council scope does not match the exact tag and comparison revision"),
    )
    return [message for valid, message in checks if not valid]


def verify_release_authority(
    subject: Path,
    *,
    tag: str,
    comparison_sha: str,
    council_run_id: str,
) -> dict[str, Any]:
    """Return a fail-closed exact-candidate release-authority report."""
    subject = subject.resolve()
    revision, errors = _identity_errors(subject, tag, comparison_sha)
    council: dict[str, Any] | None = None
    if not errors:
        try:
            council = report_council(subject, council_run_id)
            errors.extend(
                _council_errors(
                    council,
                    revision=revision,
                    comparison_sha=comparison_sha,
                    subject=subject,
                )
            )
        except (ConfigurationError, OSError) as exc:
            errors.append(f"council evidence is unavailable or invalid: {exc}")
    return {
        "schema_version": 1,
        "kind": "aqg-release-authority",
        "status": "verified" if not errors else "invalid",
        "tag": tag,
        "revision": revision or None,
        "comparison_revision": comparison_sha,
        "council_run_id": council_run_id,
        "council_result_sha256": council.get("verification", {})
        .get("manifest", {})
        .get("manifest_sha256")
        if council
        else None,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--comparison-sha", required=True)
    parser.add_argument("--council-run-id", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify_release_authority(
        args.subject,
        tag=args.tag,
        comparison_sha=args.comparison_sha,
        council_run_id=args.council_run_id,
    )
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if result["status"] == "verified" else 1


if __name__ == "__main__":
    raise SystemExit(main())
