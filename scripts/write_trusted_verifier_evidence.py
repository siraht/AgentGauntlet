#!/usr/bin/env python3
"""Create externally anchored verifier evidence for the trusted CI workflow."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aqg.trusted_verification import (  # noqa: E402
    TRUSTED_EVIDENCE_DIRECTORY_ENV,
    TRUSTED_EVIDENCE_MANIFEST_ENV,
    write_trusted_verifier_evidence,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject", type=Path, required=True)
    parser.add_argument("--trusted-root", type=Path, required=True)
    parser.add_argument("--base-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-env", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    trusted_root = args.trusted_root.resolve(strict=True)
    report = write_trusted_verifier_evidence(
        args.subject,
        args.output,
        base_revision=args.base_revision,
        trusted_root=trusted_root,
        trusted_launcher=trusted_root / "quality" / "qg.py",
        trusted_policy=trusted_root / "quality" / "policy.toml",
        trusted_project=trusted_root / "quality" / "project.json",
    )
    environment = (
        f"{TRUSTED_EVIDENCE_DIRECTORY_ENV}={report['evidence_dir']}\n"
        f"{TRUSTED_EVIDENCE_MANIFEST_ENV}={report['manifest_sha256']}\n"
    )
    with args.github_env.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(environment)
    print(f"Trusted verifier evidence: {report['manifest_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
