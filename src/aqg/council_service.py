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
    provider_identity,
    validate_ballot,
    validate_candidate_bundle,
    validate_council_result,
    verify_council_evidence,
    write_council_evidence,
)
from .council_chunks import (
    aggregate_series,
    build_bundle_series,
    series_evidence,
    verify_series,
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
REVIEW_PURPOSES = ("candidate", "debt_baseline", "policy_maintenance")


def _high_operability_model() -> str:
    """Return the no-cost third-provider route sized for high-tier bundles."""
    return "gemini/gemini-3-flash-preview"


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
        ("adversarial", "grok-4.5"),
        ("test_evidence", "codex/gpt-5.6-sol"),
        ("security_trust", "codex/gpt-5.6-sol"),
        ("operability_rollback", "opencode/deepseek-v4-flash-free"),
    ),
}


def _tier_members(tier: str) -> tuple[tuple[str, str], ...]:
    members = TIER_MEMBERS[tier]
    if tier != "high":
        return members
    return tuple(
        (role, _high_operability_model() if role == "operability_rollback" else model)
        for role, model in members
    )


def _series_limitations(chunked: bool) -> list[str]:
    if not chunked:
        return []
    return [
        (
            "Each ballot sees one bounded diff chunk plus the shared candidate context; "
            "cross-chunk relationships remain a residual review unknown."
        )
    ]


def _tier_rules(tier: str) -> tuple[list[str], int]:
    if tier not in TIER_MEMBERS:
        raise ConfigurationError(f"unknown council tier: {tier!r}")
    roles = sorted(ROLES) if tier == "smoke" else sorted(role for role, _ in _tier_members(tier))
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


def _seed_profile(summary: Mapping[str, Any]) -> str | None:
    profile = summary.get("profile")
    if profile is None:
        return None
    if not isinstance(profile, str) or profile not in PROFILE_ORDER:
        raise ConfigurationError("seed run has an unknown or malformed evidence profile")
    return profile


def _pre_council_assurance_context(
    summary: Mapping[str, Any], assurance_detail: Mapping[str, Any]
) -> dict[str, Any]:
    assurance = assurance_detail.get("assurance", {})
    controls = assurance.get("controls", {}) if isinstance(assurance, Mapping) else {}
    context = {
        "schema_version": 1,
        "seed_run_is_final_assurance": False,
        "failed_gates": [
            gate.get("name")
            for gate in summary.get("gates", [])
            if isinstance(gate, Mapping) and gate.get("exit_code") != PASS
        ],
        "assurance_failures": assurance.get("failures", []),
        "control_statuses": {
            name: control.get("status")
            for name, control in controls.items()
            if isinstance(control, Mapping)
        },
        "interpretation": (
            "A candidate council runs before final assurance. Inspect the complete assurance "
            "detail. If its sole unresolved control is this exact current council, that circular "
            "precondition is not an independent candidate defect; every other failure remains."
        ),
    }
    context["seed_run_profile"] = _seed_profile(summary)
    return context


def _project_council_value(value: Any) -> Any:
    if isinstance(value, str) and len(value.encode()) > 4096:
        raw = value.encode()
        return {
            "projected": True,
            "utf8_bytes": len(raw),
            "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        }
    if isinstance(value, Mapping):
        return {str(key): _project_council_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_project_council_value(item) for item in value]
    return value


def _council_gate_detail(path: Path) -> str | bytes:
    raw = path.read_bytes()
    if len(raw) <= 50_000:
        return raw
    projected = _project_council_value(json.loads(raw))
    return _json_text(
        {
            "schema_version": 1,
            "kind": "aqg-council-gate-projection",
            "source": path.name,
            "source_bytes": len(raw),
            "source_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "projection_rule": "strings over 4096 UTF-8 bytes become length-and-digest records",
            "detail": projected,
        }
    )


def _add_candidate_run_inputs(
    run_dir: Path, summary: Mapping[str, Any], inputs: dict[str, str | bytes]
) -> None:
    inputs["run/retrospective.json"] = (run_dir / "retrospective.json").read_bytes()
    for path in sorted((run_dir / "gates").glob("*.details.json")):
        inputs[f"run/gates/{path.name}"] = _council_gate_detail(path)
    assurance = read_json(run_dir / "gates" / "assurance.details.json")
    inputs["controller/pre-council-assurance.json"] = _json_text(
        _pre_council_assurance_context(summary, assurance)
    )


def _add_feature_inputs(root: Path, purpose: str, inputs: dict[str, str | bytes]) -> None:
    paths = (
        [root / "feature-spec" / "AgentQualityGauntlet.Retrospective.md"]
        if purpose == "debt_baseline"
        else sorted((root / "feature-spec").glob("*.md"))
    )
    for path in paths:
        inputs[f"feature-spec/{path.name}"] = path.read_bytes()


def _bundle_inputs(
    root: Path,
    base: str,
    run_dir: Path,
    summary: Mapping[str, Any],
    purpose: str = "candidate",
) -> dict[str, str | bytes]:
    diff = git_diff(root, base, unified=3)
    inputs: dict[str, str | bytes] = {
        "current.diff.patch": "" if purpose == "debt_baseline" else diff,
        "run/manifest.json": (run_dir / "manifest.json").read_bytes(),
        "run/summary.json": _json_text(summary),
    }
    if purpose != "debt_baseline":
        inputs["quality/change-risk.json"] = (root / "quality" / "change-risk.json").read_bytes()
        inputs["review/current.json"] = _json_text(_review_projection(root, base))
    if purpose == "candidate":
        _add_candidate_run_inputs(run_dir, summary, inputs)
    _add_feature_inputs(root, purpose, inputs)
    if purpose == "debt_baseline":
        inputs["controller/debt-adoption-boundary.json"] = _json_text(
            {
                "schema_version": 1,
                "adoption_meaning": (
                    "This is the initial no-regression floor for the exact current committed "
                    "repository tree. It does not claim the inventory predates the current diff "
                    "and it does not certify any candidate behavior or non-baselinable failure."
                ),
                "omitted_diff_bytes": len(diff.encode()),
                "omitted_diff_sha256": "sha256:" + hashlib.sha256(diff.encode()).hexdigest(),
                "scope_binding": (
                    "The council scope still binds revision, base revision, complete change "
                    "fingerprint, control fingerprint, and source evidence manifest."
                ),
            }
        )
        _add_debt_review_inputs(root, run_dir, inputs)
    return inputs


def _add_debt_review_inputs(root: Path, run_dir: Path, inputs: dict[str, str | bytes]) -> None:
    """Include the exact inventory, proposal, provenance, and exclusions."""
    # Imported lazily because review -> runner imports debt_store while this
    # service is being initialized.
    from .debt import document_fingerprint
    from .debt_store import build_debt_baseline_proposal, debt_control_fingerprint_evidence
    from .retrospective_inventory import debt_inventory

    proposal = build_debt_baseline_proposal(root, run_dir.name)["baseline"]
    retrospective = read_json(run_dir / "retrospective.json")
    inventory = retrospective.get("inventory", [])
    excluded_keys = (
        "blocking_failures",
        "configuration_errors",
        "infrastructure_errors",
        "measured_failures",
        "missing_evidence",
        "unknown_product_intent",
    )
    exclusions = {key: retrospective.get(key, []) for key in excluded_keys}
    project = load_project(root)
    profile = str(proposal["measurement"]["profile"])
    thresholds = _merged_settings(
        project.get("thresholds", {}), project.get("profile_thresholds", {}).get(profile, {})
    )
    details = _debt_source_details(run_dir, inventory)
    recomputed = debt_inventory(details, thresholds)
    source_reports = {
        f"{gate}.details.json": "sha256:" + sha256_file(run_dir / "gates" / f"{gate}.details.json")
        for gate in sorted(details)
    }
    proposal_text = _json_text(proposal)
    proposal_material_sha256 = "sha256:" + hashlib.sha256(proposal_text.encode()).hexdigest()
    inputs.update(
        {
            "baseline/proposed.json": proposal_text,
            "controller/debt-eligibility.json": _json_text(
                {
                    "schema_version": 1,
                    "proposal_document_fingerprint": document_fingerprint(proposal),
                    "proposal_document_fingerprint_algorithm": (
                        "sha256(canonical_json(validated_debt_baseline_document))"
                    ),
                    "proposal_material_sha256": proposal_material_sha256,
                    "proposal_material_sha256_algorithm": "sha256(exact_utf8_material_bytes)",
                    "inventory_count": len(inventory) if isinstance(inventory, list) else None,
                    "inventory_categories": sorted(
                        {
                            str(item.get("category"))
                            for item in inventory
                            if isinstance(item, Mapping)
                        }
                    ),
                    "rule": (
                        "Only the exact items in baseline/proposed.json are eligible inherited "
                        "debt. Every condition listed below remains non-baselinable and unresolved."
                    ),
                    "non_baselinable": exclusions,
                }
            ),
            "controller/debt-reconciliation.json": _json_text(
                {
                    "schema_version": 1,
                    "exact_match": recomputed == proposal["inventory"],
                    "inventory_count": len(recomputed),
                    "inventory_sha256": _value_sha256(recomputed),
                    "proposal_inventory_sha256": _value_sha256(proposal["inventory"]),
                    "source_reports": source_reports,
                    "thresholds": thresholds,
                    "rule": (
                        "AQG deterministically recomputed the proposed inventory from the complete "
                        "bundled raw gate details and exact effective thresholds. Reviewers may "
                        "independently inspect both inputs and require exact equality."
                    ),
                }
            ),
            "controller/debt-control-binding.json": _json_text(
                debt_control_fingerprint_evidence(root)
            ),
        }
    )
    for gate in ("coverage", "structure"):
        path = run_dir / "gates" / f"{gate}.json"
        if path.is_file():
            inputs[f"run/gates/{path.name}"] = path.read_bytes()
    for gate in details:
        inputs[f"run/gates/{gate}.details.json"] = (
            run_dir / "gates" / f"{gate}.details.json"
        ).read_bytes()


def _debt_source_details(run_dir: Path, inventory: Any) -> dict[str, Mapping[str, Any]]:
    category_gate = {
        "coverage": "coverage",
        "crap": "coverage",
        "structure": "structure",
        "test_integrity": "test_integrity",
    }
    gates = {
        category_gate[str(item.get("category"))]
        for item in inventory
        if isinstance(item, Mapping) and str(item.get("category")) in category_gate
    }
    return {gate: read_json(run_dir / "gates" / f"{gate}.details.json") for gate in sorted(gates)}


def _merged_settings(base: Any, override: Any) -> dict[str, Any]:
    merged = {
        key: dict(value) if isinstance(value, Mapping) else value
        for key, value in (base.items() if isinstance(base, Mapping) else ())
    }
    for key, value in override.items() if isinstance(override, Mapping) else ():
        if isinstance(value, Mapping) and isinstance(merged.get(key), Mapping):
            merged[key] = _merged_settings(merged[key], value)
        else:
            merged[key] = value
    return merged


def _value_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _json_text(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _scope(root: Path, base: str) -> dict[str, str]:
    return {
        "revision": git_revision(root),
        "base_revision": base,
        "change_fingerprint": change_fingerprint(root, base),
        "control_fingerprint": control_fingerprint(root),
    }


def _review_purpose_decision(purpose: str) -> str:
    if purpose == "debt_baseline":
        return (
            "Decide only whether this shadow inventory is honest and safe to record as "
            "inherited debt for no-regression ratcheting. Clear does not certify the "
            "candidate, satisfy assurance, authorize release, or turn a failed measurement "
            "into a pass. This initial-adoption floor describes the exact current committed "
            "tree; do not require proof that items predate the bootstrap diff. Judge the exact "
            "inventory, raw sources, deterministic reconciliation, and ratchet safety. Other "
            "failures remain explicitly unresolved and outside this authority."
        )
    if purpose == "policy_maintenance":
        return (
            "Decide only whether the exact protected control changes preserve or strengthen "
            "guardrails and match their stated maintenance request. Clear does not certify "
            "unrelated implementation, satisfy assurance, authorize release, or erase "
            "deterministic failures."
        )
    return (
        "Review the exact candidate for technical assurance. This council is an input to the "
        "assurance gate, so do not block solely because the seed run lacks this same current "
        "council. A blocker-coded test-expectation-deleted review finding is also deliberately "
        "eligible for this council's resolution when unit, coverage, and changed-code mutation "
        "all pass and review is the seed run's only failed non-assurance gate. In that case, "
        "inspect every affected test path and the exact replacement evidence instead of merely "
        "repeating the scanner finding. Clear only when the replacement tests preserve or "
        "strengthen the removed oracles; otherwise identify the specific lost behavior and "
        "block. When ROLE is adversarial or test_evidence and you clear this scanner finding, "
        "include an info finding whose category is exactly test-expectation-resolution and whose "
        "non-empty claim summarizes the conclusion. Its oracle_resolutions must map every "
        "affected test path to an exact deleted oracle line, an exact added replacement line, "
        "and a non-empty explanation of the preserved observable behavior. Cite both "
        "current.diff.patch and review/current.json in that finding. "
        "The final review gate accepts only a verified, exact-candidate, high-tier clear "
        "council with adversarial and test-evidence coverage. The seed run is necessarily not "
        "the final passing run when its only other failed gate is assurance and the bundled "
        "assurance details show behavior, functional "
        "rehearsal, and rollback work while independent verification only lacks this exact "
        "current candidate council. In that precise circular case, neither the assurance-only "
        "failure nor review/current's resulting missing passing deep run is an independent "
        "blocker. Inspect the bundled gate details and do block every other deterministic "
        "failure, missing requirement, or unsafe condition."
    )


def _baseline_purpose_artifacts(inputs: Mapping[str, str | bytes]) -> dict[str, str]:
    from .debt import document_fingerprint

    return {
        "debt_baseline_document": document_fingerprint(
            json.loads(str(inputs["baseline/proposed.json"]))
        )
    }


def _prepare_plan(
    root: Path,
    tier: str,
    max_bundle_bytes: int,
    data_classification: str,
    purpose: str = "candidate",
) -> tuple[dict[str, Any], dict[str, Any]]:
    if purpose not in REVIEW_PURPOSES:
        raise ConfigurationError(f"unknown council review purpose: {purpose!r}")
    base = _base_ref(root)
    routing = _provider_routing(data_classification)
    scope = _scope(root, base)
    run_dir, summary = _matching_quality_run(root, scope, TIER_EVIDENCE_PROFILE[tier])
    inputs = _bundle_inputs(root, base, run_dir, summary, purpose)
    inputs["controller/review-purpose.json"] = _json_text(
        {"purpose": purpose, "decision": _review_purpose_decision(purpose)}
    )
    series = build_bundle_series(
        scope=scope,
        evidence_manifest_sha256="sha256:" + sha256_file(run_dir / "manifest.json"),
        inputs=inputs,
        max_bundle_bytes=max_bundle_bytes,
    )
    plan = _plan_payload(
        tier,
        run_dir,
        series,
        max_bundle_bytes,
        data_classification,
        routing,
        purpose,
    )
    if purpose == "debt_baseline":
        plan["purpose_artifacts"] = _baseline_purpose_artifacts(inputs)
    return plan, series


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


def _completion_meaning(chunked: bool) -> str:
    if chunked:
        return "all_required_chunk_ballots_received"
    return "all_required_candidate_ballots_received"


def _plan_payload(
    tier: str,
    run_dir: Path,
    series: Mapping[str, Any],
    max_bundle_bytes: int,
    data_classification: str,
    routing: Mapping[str, Any],
    purpose: str = "candidate",
) -> dict[str, Any]:
    roles, groups = _tier_rules(tier)
    chunked = len(series["bundles"]) > 1
    members = []
    for role, model_id in _tier_members(tier):
        members.append({"role": role, "model_id": model_id, **provider_identity(model_id)})
    return {
        "schema_version": SERVICE_SCHEMA_VERSION,
        "kind": "aqg-council-plan",
        "advisory_only": True,
        "banner": ADVISORY_BANNER,
        "tier": tier,
        "purpose": purpose,
        "provider_calls": False,
        "data_classification": data_classification,
        "provider_routing": dict(routing),
        "members": members,
        "required_roles": roles,
        "minimum_provider_groups": groups,
        "expected_standard": "high_assurance_incomplete" if tier == "smoke" else "complete",
        "quality_run_id": run_dir.name,
        "scope": dict(series["scope"]),
        "bundle_sha256": series["series_sha256"],
        "bundle_mode": "chunked" if chunked else "single",
        "bundle_count": len(series["bundles"]),
        "review_scope": "bounded_diff_chunk" if chunked else "candidate",
        "completion_meaning": _completion_meaning(chunked),
        "series_limitations": _series_limitations(chunked),
        "bundle_bytes": max(chunk["bundle_bytes"] for chunk in series["chunks"]),
        "total_bundle_bytes": sum(chunk["bundle_bytes"] for chunk in series["chunks"]),
        "max_bundle_bytes": max_bundle_bytes,
    }


def plan_council(
    root: Path,
    tier: str = "high",
    max_bundle_bytes: int = DEFAULT_BUNDLE_BYTES,
    data_classification: str = "unclassified",
    purpose: str = "candidate",
) -> dict[str, Any]:
    """Build a provider-free plan from current, finalized candidate evidence."""
    plan, _ = _prepare_plan(Path(root), tier, max_bundle_bytes, data_classification, purpose)
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
        name: _tool_version(name, which=which, executor=executor)
        for name in ("codex", "gemini", "grok", "opencode")
    }
    models = {tier: [model for _, model in _tier_members(tier)] for tier in TIER_MEMBERS}
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
    for role, model_id in _tier_members(tier):
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
        run_dir.mkdir(parents=True)
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


def _write_series_run(
    root: Path,
    run_id: str,
    plan: Mapping[str, Any],
    series: Mapping[str, Any],
    ballots: Sequence[Sequence[Mapping[str, Any]]],
    executions: Sequence[Sequence[Mapping[str, Any]]],
    results: Sequence[Mapping[str, Any]],
    result: Mapping[str, Any],
) -> Path:
    run_dir = root / ".aqg" / "council" / validate_run_id(run_id)
    try:
        run_dir.mkdir(parents=True)
    except FileExistsError as exc:
        raise ConfigurationError(f"council evidence already exists: {run_dir}") from exc
    except OSError as exc:
        raise InfrastructureError(f"cannot create council evidence: {exc}") from exc
    write_evidence_json(run_dir / "plan.json", dict(plan))
    write_evidence_json(run_dir / "bundle-series.json", series_evidence(series))
    write_evidence_json(run_dir / "toolchain.json", council_doctor())
    for index, bundle in enumerate(series["bundles"]):
        write_council_evidence(
            run_dir / "chunks", f"chunk-{index:04d}", bundle, ballots[index], results[index]
        )
        for member, execution in enumerate(executions[index]):
            write_evidence_json(
                run_dir / "executions" / f"chunk-{index:04d}-{member:03d}.json",
                dict(execution),
            )
    write_evidence_json(run_dir / "result.json", dict(result))
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
    purpose: str = "candidate",
) -> tuple[int, dict[str, Any]]:
    """Run council members sequentially and publish only verified immutable evidence."""
    if timeout_seconds <= 0:
        raise ConfigurationError("council member timeout must be positive")
    root = Path(root)
    plan, series = _prepare_plan(root, tier, max_bundle_bytes, data_classification, purpose)
    _require_provider_route(plan, data_classification)
    selected_id = validate_run_id(run_id) if run_id else _new_run_id()
    environment = minimal_environment(os.environ)
    roles, minimum_groups = _tier_rules(tier)
    ballots, executions, results = _run_series(
        tier, series, environment, timeout_seconds, executor, selected_id, roles, minimum_groups
    )
    result = aggregate_series(series, results)
    run_dir = _write_series_run(
        root, selected_id, plan, series, ballots, executions, results, result
    )
    _verify_and_publish(root, run_dir, selected_id, result)
    flattened = [item for chunk in executions for item in chunk]
    return _result_exit_code(result, flattened), report_council(root, selected_id)


def _run_series(
    tier: str,
    series: Mapping[str, Any],
    environment: Mapping[str, str],
    timeout_seconds: float,
    executor: Callable[..., subprocess.CompletedProcess[str]],
    review_id: str,
    roles: Sequence[str],
    minimum_groups: int,
) -> tuple[list[list[dict[str, Any]]], list[list[dict[str, Any]]], list[dict[str, Any]]]:
    ballots, executions, results = [], [], []
    with tempfile.TemporaryDirectory() as temporary:
        for index, bundle in enumerate(series["bundles"]):
            cwd = Path(temporary) / f"chunk-{index:04d}"
            cwd.mkdir()
            chunk_ballots, chunk_executions = _run_members(
                tier,
                bundle,
                cwd,
                environment,
                timeout_seconds,
                executor,
                f"{review_id}-chunk-{index:04d}",
            )
            ballots.append(chunk_ballots)
            executions.append(chunk_executions)
            results.append(
                aggregate_ballots(
                    bundle,
                    chunk_ballots,
                    required_roles=roles,
                    minimum_provider_groups=minimum_groups,
                )
            )
    return ballots, executions, results


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
    bundle_name = (
        "bundle-series.json"
        if (run_dir / "bundle-series.json").is_file()
        else "candidate-bundle.json"
    )
    return (
        read_json(run_dir / "plan.json"),
        read_json(run_dir / bundle_name),
        read_json(run_dir / "result.json"),
        read_json(run_dir / "toolchain.json"),
    )


def _execution_evidence_errors(run_dir: Path) -> list[str]:
    executions = sorted(run_dir.rglob("executions/*.json"))
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
            plan.get("bundle_sha256") in {bundle.get("bundle_sha256"), bundle.get("series_sha256")},
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
    core = (
        _verify_series_evidence(run_dir)
        if (run_dir / "bundle-series.json").is_file()
        else verify_council_evidence(run_dir)
    )
    core_errors = list(core["errors"])
    service_errors = [] if core_errors else _service_evidence_errors(run_dir)
    errors = core_errors + service_errors
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


def _read_chunk_evidence(
    paths: Sequence[Path],
) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    verified = [verify_council_evidence(path) for path in paths]
    errors = [error for item in verified for error in item["errors"]]
    if errors:
        return errors, [], []
    bundles = [read_json(path / "candidate-bundle.json") for path in paths]
    results = [read_json(path / "result.json") for path in paths]
    return [], bundles, results


def _verify_series_evidence(run_dir: Path) -> dict[str, Any]:
    manifest = verify_run_manifest(run_dir)
    manifest_errors = list(manifest["errors"])
    if manifest_errors:
        return {"errors": manifest_errors, "manifest": manifest}
    series = read_json(run_dir / "bundle-series.json")
    paths = sorted((run_dir / "chunks").glob("chunk-*"))
    errors, bundles, results = _read_chunk_evidence(paths)
    if errors:
        return {"errors": errors, "manifest": manifest}
    errors.extend(verify_series(series, bundles))
    if read_json(run_dir / "result.json") != aggregate_series(series, results):
        errors.append("series result does not match its bounded chunk results")
    return {"errors": errors, "manifest": manifest}


def _reported_members(paths: Sequence[Path]) -> list[dict[str, Any]]:
    ballots = [read_json(path) for path in paths]
    return [
        {
            "model_id": ballot["reviewer"]["model_id"],
            "provider_group": ballot["reviewer"]["provider_group"],
            "role": ballot["reviewer"]["role"],
            "verdict": ballot["verdict"],
            "confidence": ballot["confidence"],
            "findings": len(ballot["findings"]),
        }
        for ballot in ballots
    ]


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
    series_mode = (run_dir / "bundle-series.json").is_file()
    bundle = read_json(run_dir / ("bundle-series.json" if series_mode else "candidate-bundle.json"))
    result = read_json(run_dir / "result.json")
    ballot_paths = sorted(
        run_dir.rglob("ballots/*.json") if series_mode else (run_dir / "ballots").glob("*.json")
    )
    return {
        "schema_version": SERVICE_SCHEMA_VERSION,
        "kind": "aqg-council-report",
        "advisory_only": True,
        "banner": ADVISORY_BANNER,
        "run_id": selected,
        "tier": plan["tier"],
        "purpose": plan.get("purpose", "candidate"),
        "purpose_artifacts": plan.get("purpose_artifacts", {}),
        "scope": bundle["scope"],
        "status": result["status"],
        "summary": result["summary"],
        "complete": result["complete"],
        "provider_groups": result["provider_groups"],
        "covered_roles": result["covered_roles"],
        "blockers": result["blockers"],
        "dissent": result["dissent"],
        "incomplete_reasons": result["incomplete_reasons"],
        "bundle_mode": plan.get("bundle_mode", "single"),
        "bundle_count": plan.get("bundle_count", 1),
        "review_scope": plan.get("review_scope", "candidate"),
        "completion_meaning": plan.get(
            "completion_meaning", "all_required_candidate_ballots_received"
        ),
        "series_limitations": plan.get("series_limitations", []),
        "members": _reported_members(ballot_paths),
        "executions": len(list((run_dir / "executions").glob("*.json"))),
        "verification": verification,
    }
