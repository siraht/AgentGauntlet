"""Application service for advisory, evidence-bound review councils."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .constants import CONFIGURATION_ERROR, INFRASTRUCTURE_ERROR, PASS, QUALITY_FAILURE
from .council import (
    ROLES,
    aggregate_ballots,
    build_candidate_bundle,
    canonical_json,
    provider_identity,
    validate_ballot,
    validate_candidate_bundle,
    validate_council_result,
    verify_council_evidence,
)
from .council_providers import collect_ballot, minimal_environment
from .errors import ConfigurationError, InfrastructureError
from .evidence_manifest import (
    validate_run_id,
    verify_run_manifest,
    write_evidence_json,
    write_run_manifest,
)
from .policy import load_policy
from .project import load_project
from .review import analyze_review
from .util import (
    change_fingerprint,
    control_fingerprint,
    git_diff,
    git_revision,
    read_json,
    sha256_file,
    utc_now,
    write_json,
)

SERVICE_SCHEMA_VERSION = 1
DEFAULT_BUNDLE_BYTES = 1_000_000
DEFAULT_TIMEOUT_SECONDS = 180.0
ADVISORY_BANNER = "AGENT ADVISORY — NOT AN APPROVAL OR RELEASE AUTHORITY"
DATA_CLASSIFICATIONS = ("unclassified", "public", "internal", "confidential", "regulated")
PROFILE_ORDER = ("inner", "fast", "pr", "deep", "release")
TIER_EVIDENCE_PROFILE = {"smoke": "fast", "pr": "pr", "high": "deep"}

TIER_MEMBERS: dict[str, tuple[tuple[str, str], ...]] = {
    "smoke": (
        ("requirements_behavior", "synthetic/hf:zai-org/GLM-4.7-Flash"),
        ("test_evidence", "opencode/deepseek-v4-flash-free"),
    ),
    "pr": (
        ("requirements_behavior", "grok-4.5"),
        ("test_evidence", "synthetic/hf:zai-org/GLM-5.2"),
        ("operability_rollback", "opencode/deepseek-v4-flash-free"),
    ),
    "high": (
        ("requirements_behavior", "grok-4.5"),
        ("test_evidence", "synthetic/hf:zai-org/GLM-5.2"),
        ("security_trust", "synthetic/hf:moonshotai/Kimi-K3"),
        ("operability_rollback", "opencode/deepseek-v4-flash-free"),
    ),
}


def _tier_rules(tier: str) -> tuple[list[str], int]:
    if tier not in TIER_MEMBERS:
        raise ConfigurationError(f"unknown council tier: {tier!r}")
    roles = sorted(ROLES) if tier == "smoke" else sorted(role for role, _ in TIER_MEMBERS[tier])
    return roles, 3


def _base_ref(root: Path) -> str:
    override = os.environ.get("AQG_DIFF_BASE")
    if override:
        return override
    return str(load_project(root).get("enforcement", {}).get("base_ref", "HEAD"))


def _is_secret_gate(name: object) -> bool:
    return name in {"secrets", "security_fast"}


def _secret_gate_passed(summary: Mapping[str, Any]) -> bool:
    gates = summary.get("gates")
    if not isinstance(gates, list):
        return False
    return any(
        isinstance(gate, Mapping)
        and _is_secret_gate(gate.get("name"))
        and gate.get("status") == "pass"
        and gate.get("exit_code") == PASS
        for gate in gates
    )


def _profile_satisfies(actual: object, required: str) -> bool:
    try:
        return PROFILE_ORDER.index(str(actual)) >= PROFILE_ORDER.index(required)
    except ValueError:
        return False


def _matching_quality_run(
    root: Path, scope: Mapping[str, str], required_profile: str
) -> tuple[Path, dict[str, Any]]:
    runs_dir = root / ".aqg" / "runs"
    for run_dir in sorted(runs_dir.glob("*"), reverse=True):
        manifest = verify_run_manifest(run_dir)
        if not manifest["ok"]:
            continue
        try:
            summary = read_json(run_dir / "summary.json")
        except ConfigurationError:
            continue
        expected = (scope["revision"], scope["change_fingerprint"], scope["control_fingerprint"])
        actual = (
            summary.get("revision"),
            summary.get("change_fingerprint"),
            summary.get("control_fingerprint"),
        )
        if (
            actual == expected
            and _secret_gate_passed(summary)
            and _profile_satisfies(summary.get("profile"), required_profile)
        ):
            return run_dir, summary
    raise ConfigurationError(
        "no finalized quality run matches the current revision, change fingerprint, "
        f"control fingerprint, passing secrets gate, and {required_profile!r} evidence profile"
    )


def _review_projection(root: Path, base: str) -> dict[str, Any]:
    packet = analyze_review(root, load_policy(root), base=base, require_evidence=True)
    keys = (
        "schema_version",
        "base",
        "revision",
        "change_fingerprint",
        "control_fingerprint",
        "changed_files",
        "summary",
        "risk",
        "evidence",
        "approvals",
        "findings",
    )
    return {key: packet[key] for key in keys}


def _bundle_inputs(
    root: Path, base: str, run_dir: Path, summary: Mapping[str, Any]
) -> dict[str, str | bytes]:
    inputs: dict[str, str | bytes] = {
        "current.diff.patch": git_diff(root, base, unified=3),
        "quality/change-risk.json": (root / "quality" / "change-risk.json").read_bytes(),
        "review/current.json": _json_text(_review_projection(root, base)),
        "run/manifest.json": (run_dir / "manifest.json").read_bytes(),
        "run/summary.json": _json_text(summary),
    }
    for path in sorted((root / "feature-spec").glob("*.md")):
        inputs[f"feature-spec/{path.name}"] = path.read_bytes()
    return inputs


def _json_text(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _scope(root: Path, base: str) -> dict[str, str]:
    return {
        "revision": git_revision(root),
        "base_revision": base,
        "change_fingerprint": change_fingerprint(root, base),
        "control_fingerprint": control_fingerprint(root),
    }


def _prepare_plan(
    root: Path, tier: str, max_bundle_bytes: int, data_classification: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    if max_bundle_bytes <= 0:
        raise ConfigurationError("council bundle size cap must be positive")
    base = _base_ref(root)
    routing = _provider_routing(data_classification)
    scope = _scope(root, base)
    run_dir, summary = _matching_quality_run(root, scope, TIER_EVIDENCE_PROFILE[tier])
    inputs = _bundle_inputs(root, base, run_dir, summary)
    bundle = build_candidate_bundle(
        **scope,
        evidence_manifest_sha256="sha256:" + sha256_file(run_dir / "manifest.json"),
        inputs=inputs,
    )
    bundle_bytes = len(canonical_json(bundle))
    if bundle_bytes > max_bundle_bytes:
        raise ConfigurationError(
            f"candidate bundle is {bundle_bytes} bytes; cap is {max_bundle_bytes} bytes"
        )
    return (
        _plan_payload(
            tier,
            run_dir,
            bundle,
            bundle_bytes,
            max_bundle_bytes,
            data_classification,
            routing,
        ),
        bundle,
    )


def _provider_routing(data_classification: str) -> dict[str, Any]:
    if data_classification not in DATA_CLASSIFICATIONS:
        raise ConfigurationError(
            "unknown council data classification: "
            f"{data_classification!r}; choose: {', '.join(DATA_CLASSIFICATIONS)}"
        )
    allowed = data_classification == "public"
    return {
        "classification": data_classification,
        "external_providers_allowed": allowed,
        "reason": (
            "candidate is explicitly classified public"
            if allowed
            else "no approved isolated or enterprise provider route is configured"
        ),
    }


def _plan_payload(
    tier: str,
    run_dir: Path,
    bundle: Mapping[str, Any],
    bundle_bytes: int,
    max_bundle_bytes: int,
    data_classification: str,
    routing: Mapping[str, Any],
) -> dict[str, Any]:
    roles, groups = _tier_rules(tier)
    members = []
    for role, model_id in TIER_MEMBERS[tier]:
        members.append({"role": role, "model_id": model_id, **provider_identity(model_id)})
    return {
        "schema_version": SERVICE_SCHEMA_VERSION,
        "kind": "aqg-council-plan",
        "advisory_only": True,
        "banner": ADVISORY_BANNER,
        "tier": tier,
        "provider_calls": False,
        "data_classification": data_classification,
        "provider_routing": dict(routing),
        "members": members,
        "required_roles": roles,
        "minimum_provider_groups": groups,
        "expected_standard": "high_assurance_incomplete" if tier == "smoke" else "complete",
        "quality_run_id": run_dir.name,
        "scope": dict(bundle["scope"]),
        "bundle_sha256": bundle["bundle_sha256"],
        "bundle_bytes": bundle_bytes,
        "max_bundle_bytes": max_bundle_bytes,
    }


def plan_council(
    root: Path,
    tier: str = "high",
    max_bundle_bytes: int = DEFAULT_BUNDLE_BYTES,
    data_classification: str = "unclassified",
) -> dict[str, Any]:
    """Build a provider-free plan from current, finalized candidate evidence."""
    plan, _ = _prepare_plan(Path(root), tier, max_bundle_bytes, data_classification)
    return plan


def _tool_version(
    name: str,
    *,
    which: Callable[[str], str | None],
    executor: Callable[..., subprocess.CompletedProcess[str]],
) -> dict[str, Any]:
    path = which(name)
    if path is None:
        return {"available": False, "path": None, "version": None, "error": "missing executable"}
    try:
        completed = executor(
            [path, "--version"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return {"available": True, "path": path, "version": None, "error": "version probe failed"}
    output = (completed.stdout or completed.stderr or "").strip().splitlines()
    version = output[0][:200] if completed.returncode == 0 and output else None
    error = None if version else "version unavailable"
    return {"available": True, "path": path, "version": version, "error": error}


def council_doctor(
    *,
    which: Callable[[str], str | None] = shutil.which,
    executor: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Report council tools and exact configured model identifiers without secrets."""
    tools = {
        name: _tool_version(name, which=which, executor=executor) for name in ("grok", "opencode")
    }
    models = {tier: [model for _, model in members] for tier, members in TIER_MEMBERS.items()}
    missing = sorted(name for name, item in tools.items() if not item["available"])
    return {
        "schema_version": SERVICE_SCHEMA_VERSION,
        "kind": "aqg-council-doctor",
        "advisory_only": True,
        "banner": ADVISORY_BANNER,
        "status": "ready" if not missing else "incomplete",
        "missing_tools": missing,
        "tools": tools,
        "models": models,
    }


def _safe_execution(execution: Mapping[str, Any]) -> dict[str, Any]:
    safe = {key: value for key, value in execution.items() if key not in {"stdout", "stderr"}}
    stdout = str(execution.get("stdout", ""))
    stderr = str(execution.get("stderr", ""))
    safe["stdout_bytes"] = len(stdout.encode("utf-8"))
    safe["stderr_bytes"] = len(stderr.encode("utf-8"))
    safe["stderr_sha256"] = "sha256:" + hashlib.sha256(stderr.encode("utf-8")).hexdigest()
    return safe


def _run_members(
    tier: str,
    bundle: Mapping[str, Any],
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
    executor: Callable[..., subprocess.CompletedProcess[str]],
    review_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ballots: list[dict[str, Any]] = []
    executions: list[dict[str, Any]] = []
    for role, model_id in TIER_MEMBERS[tier]:
        ballot, execution = collect_ballot(
            review_id=review_id,
            model_id=model_id,
            role=role,
            bundle=bundle,
            cwd=cwd,
            environment=environment,
            timeout_seconds=timeout_seconds,
            executor=executor,
        )
        executions.append(_safe_execution(execution))
        if ballot is not None:
            ballots.append(ballot)
    return ballots, executions


def _result_exit_code(result: Mapping[str, Any], executions: Sequence[Mapping[str, Any]]) -> int:
    codes = {item.get("exit_code") for item in executions}
    if CONFIGURATION_ERROR in codes:
        return CONFIGURATION_ERROR
    if INFRASTRUCTURE_ERROR in codes or not result["complete"]:
        return INFRASTRUCTURE_ERROR
    if result["status"] == "advisory_clear":
        return PASS
    return QUALITY_FAILURE


def _new_run_id() -> str:
    stamp = utc_now().replace("+00:00", "Z").replace(":", "").replace("-", "")
    return validate_run_id(f"council-{stamp}-{uuid.uuid4().hex[:8]}")


def _write_council_run(
    root: Path,
    run_id: str,
    plan: Mapping[str, Any],
    bundle: Mapping[str, Any],
    ballots: Sequence[Mapping[str, Any]],
    executions: Sequence[Mapping[str, Any]],
    result: Mapping[str, Any],
    toolchain: Mapping[str, Any],
) -> Path:
    run_dir = root / ".aqg" / "council" / validate_run_id(run_id)
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise ConfigurationError(f"council evidence already exists: {run_dir}") from exc
    except OSError as exc:
        raise InfrastructureError(f"cannot create council evidence: {exc}") from exc
    write_evidence_json(run_dir / "plan.json", dict(plan))
    write_evidence_json(run_dir / "candidate-bundle.json", validate_candidate_bundle(bundle))
    write_evidence_json(run_dir / "toolchain.json", dict(toolchain))
    for index, execution in enumerate(executions):
        write_evidence_json(run_dir / "executions" / f"{index:03d}.json", dict(execution))
    for index, ballot in enumerate(sorted(ballots, key=lambda item: item["ballot_sha256"])):
        write_evidence_json(
            run_dir / "ballots" / f"{index:03d}.json", validate_ballot(ballot, bundle=bundle)
        )
    write_evidence_json(run_dir / "result.json", validate_council_result(result, bundle=bundle))
    write_run_manifest(run_dir, run_id)
    return run_dir


def _publish_latest(root: Path, run_dir: Path, result: Mapping[str, Any]) -> None:
    payload = {
        "schema_version": SERVICE_SCHEMA_VERSION,
        "run_id": run_dir.name,
        "status": result["status"],
        "result_sha256": result["result_sha256"],
        "manifest_sha256": "sha256:" + sha256_file(run_dir / "manifest.json"),
        "updated_at": utc_now(),
    }
    write_json(root / ".aqg" / "council" / "latest.json", payload)


def run_council(
    root: Path,
    tier: str = "high",
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_bundle_bytes: int = DEFAULT_BUNDLE_BYTES,
    executor: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    run_id: str | None = None,
    data_classification: str,
) -> tuple[int, dict[str, Any]]:
    """Run council members sequentially and publish only verified immutable evidence."""
    if timeout_seconds <= 0:
        raise ConfigurationError("council member timeout must be positive")
    root = Path(root)
    plan, bundle = _prepare_plan(root, tier, max_bundle_bytes, data_classification)
    _require_provider_route(plan, data_classification)
    selected_id = validate_run_id(run_id) if run_id else _new_run_id()
    environment = minimal_environment(os.environ)
    with tempfile.TemporaryDirectory(prefix="aqg-council-") as temporary:
        ballots, executions = _run_members(
            tier, bundle, Path(temporary), environment, timeout_seconds, executor, selected_id
        )
    roles, minimum_groups = _tier_rules(tier)
    result = aggregate_ballots(
        bundle, ballots, required_roles=roles, minimum_provider_groups=minimum_groups
    )
    run_dir = _write_council_run(
        root, selected_id, plan, bundle, ballots, executions, result, council_doctor()
    )
    _verify_and_publish(root, run_dir, selected_id, result)
    return _result_exit_code(result, executions), report_council(root, selected_id)


def _require_provider_route(plan: Mapping[str, Any], data_classification: str) -> None:
    if plan["provider_routing"]["external_providers_allowed"]:
        return
    raise ConfigurationError(
        f"council data is {data_classification}; no approved external-provider route is configured"
    )


def _verify_and_publish(root: Path, run_dir: Path, run_id: str, result: Mapping[str, Any]) -> None:
    verification = verify_council_run(root, run_id)
    if not verification["ok"]:
        raise InfrastructureError(
            "council evidence failed verification: " + "; ".join(verification["errors"])
        )
    _publish_latest(root, run_dir, result)


def _resolve_run_id(root: Path, run_id: str) -> str:
    if run_id != "latest":
        return validate_run_id(run_id)
    latest = read_json(root / ".aqg" / "council" / "latest.json")
    return validate_run_id(str(latest.get("run_id", "")))


def _load_service_evidence(run_dir: Path) -> tuple[dict[str, Any], ...]:
    return (
        read_json(run_dir / "plan.json"),
        read_json(run_dir / "candidate-bundle.json"),
        read_json(run_dir / "result.json"),
        read_json(run_dir / "toolchain.json"),
    )


def _execution_evidence_errors(run_dir: Path) -> list[str]:
    executions = sorted((run_dir / "executions").glob("*.json"))
    leaked = any("stdout" in read_json(path) or "stderr" in read_json(path) for path in executions)
    return (
        ["provider output was persisted instead of digest-only execution evidence"]
        if leaked
        else []
    )


def _service_metadata_errors(
    plan: Mapping[str, Any],
    bundle: Mapping[str, Any],
    result: Mapping[str, Any],
    toolchain: Mapping[str, Any],
) -> list[str]:
    checks = (
        (
            plan.get("kind") == "aqg-council-plan" and plan.get("advisory_only") is True,
            "plan is not an advisory council plan",
        ),
        (
            plan.get("bundle_sha256") == bundle.get("bundle_sha256"),
            "plan does not identify the manifested candidate bundle",
        ),
        (result.get("advisory_only") is True, "result is missing its advisory-only marker"),
        (
            toolchain.get("kind") == "aqg-council-doctor"
            and toolchain.get("advisory_only") is True,
            "toolchain provenance is missing or malformed",
        ),
    )
    return [message for valid, message in checks if not valid]


def _service_evidence_errors(run_dir: Path) -> list[str]:
    try:
        plan, bundle, result, toolchain = _load_service_evidence(run_dir)
        return _service_metadata_errors(plan, bundle, result, toolchain) + (
            _execution_evidence_errors(run_dir)
        )
    except (ConfigurationError, OSError) as exc:
        return [str(exc)]


def verify_council_run(root: Path, run_id: str = "latest") -> dict[str, Any]:
    """Verify a council run's manifest, core contracts, and service evidence."""
    root = Path(root)
    selected = _resolve_run_id(root, run_id)
    run_dir = root / ".aqg" / "council" / selected
    core = verify_council_evidence(run_dir)
    errors = list(core["errors"])
    if core["ok"]:
        errors.extend(_service_evidence_errors(run_dir))
    return {
        "schema_version": SERVICE_SCHEMA_VERSION,
        "kind": "aqg-council-verification",
        "advisory_only": True,
        "banner": ADVISORY_BANNER,
        "run_id": selected,
        "ok": not errors,
        "errors": errors,
        "manifest": core["manifest"],
    }


def report_council(root: Path, run_id: str = "latest") -> dict[str, Any]:
    """Return a compact advisory report from verified immutable evidence."""
    root = Path(root)
    selected = _resolve_run_id(root, run_id)
    run_dir = root / ".aqg" / "council" / selected
    verification = verify_council_run(root, selected)
    if not verification["ok"]:
        raise ConfigurationError(
            "council evidence is invalid: " + "; ".join(verification["errors"])
        )
    plan = read_json(run_dir / "plan.json")
    bundle = read_json(run_dir / "candidate-bundle.json")
    result = read_json(run_dir / "result.json")
    ballot_paths = sorted((run_dir / "ballots").glob("*.json"))
    ballots = [read_json(path) for path in ballot_paths]
    return {
        "schema_version": SERVICE_SCHEMA_VERSION,
        "kind": "aqg-council-report",
        "advisory_only": True,
        "banner": ADVISORY_BANNER,
        "run_id": selected,
        "tier": plan["tier"],
        "scope": bundle["scope"],
        "status": result["status"],
        "summary": result["summary"],
        "complete": result["complete"],
        "provider_groups": result["provider_groups"],
        "covered_roles": result["covered_roles"],
        "blockers": result["blockers"],
        "dissent": result["dissent"],
        "incomplete_reasons": result["incomplete_reasons"],
        "members": [
            {
                "model_id": ballot["reviewer"]["model_id"],
                "provider_group": ballot["reviewer"]["provider_group"],
                "role": ballot["reviewer"]["role"],
                "verdict": ballot["verdict"],
                "confidence": ballot["confidence"],
                "findings": len(ballot["findings"]),
            }
            for ballot in ballots
        ],
        "executions": len(list((run_dir / "executions").glob("*.json"))),
        "verification": verification,
    }
