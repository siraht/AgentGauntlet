"""Fail-closed Git reference resolution for immutable evidence identity."""

from __future__ import annotations

import re
from pathlib import Path

from .errors import ConfigurationError
from .util import change_fingerprint, control_fingerprint, git_output, git_revision


def resolve_git_commit(root: Path, ref: str) -> str:
    """Resolve a comparison ref to the immutable commit it currently names."""
    code, stdout, stderr = git_output(root, ["rev-parse", "--verify", f"{ref}^{{commit}}"])
    revision = stdout.strip()
    if code != 0 or not re.fullmatch(r"[0-9a-fA-F]{40,64}", revision):
        detail = stderr.strip() or "Git returned no commit identifier"
        raise ConfigurationError(f"comparison base {ref!r} does not resolve to a commit: {detail}")
    return revision.lower()


def immutable_provenance(root: Path, base_ref: str) -> dict[str, str]:
    """Bind a configured comparison ref and review surface to exact commits and hashes."""
    return {
        "revision": git_revision(root),
        "base_ref": base_ref,
        "base_revision": resolve_git_commit(root, base_ref),
        "change_fingerprint": change_fingerprint(root, base_ref),
        "control_fingerprint": control_fingerprint(root),
    }
