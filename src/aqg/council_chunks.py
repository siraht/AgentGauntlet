from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from .council import build_candidate_bundle, canonical_json, fingerprint, validate_candidate_bundle
from .errors import ConfigurationError

VERSION = 1
DIFF = "current.diff.patch"
AUTHORITY = (
    "Agent advisory only; this does not constitute human approval, code-owner approval, "
    "policy approval, or release authority."
)


def _bundle(scope: Mapping[str, str], evidence: str, inputs: Mapping[str, str]) -> dict[str, Any]:
    return build_candidate_bundle(**scope, evidence_manifest_sha256=evidence, inputs=inputs)


def _size(bundle: Mapping[str, Any]) -> int:
    return len(canonical_json(bundle))


def _prefix(
    diff: str, common: Mapping[str, str], scope: Mapping[str, str], evidence: str, maximum: int
) -> int:
    low, high, best = 1, len(diff), 0
    while low <= high:
        middle = (low + high) // 2
        if _size(_bundle(scope, evidence, {**common, DIFF: diff[:middle]})) <= maximum:
            best, low = middle, middle + 1
        else:
            high = middle - 1
    return best


def _decode_inputs(inputs: Mapping[str, str | bytes]) -> dict[str, str]:
    try:
        return {
            name: value if isinstance(value, str) else bytes(value).decode()
            for name, value in inputs.items()
        }
    except UnicodeDecodeError as exc:
        raise ConfigurationError("council materials must be UTF-8 text") from exc


def _chunk(bundle: Mapping[str, Any], index: int, start: int, end: int) -> dict[str, Any]:
    return {
        "index": index,
        "byte_start": start,
        "byte_end": end,
        "bundle_sha256": bundle["bundle_sha256"],
        "bundle_bytes": _size(bundle),
    }


def _chunks(
    diff: str,
    common: Mapping[str, str],
    scope: Mapping[str, str],
    evidence: str,
    maximum: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    bundles: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []
    if not diff:
        bundle = _bundle(scope, evidence, {**common, DIFF: ""})
        return [bundle], [_chunk(bundle, 0, 0, 0)]
    chars, byte = 0, 0
    while chars < len(diff):
        take = _prefix(diff[chars:], common, scope, evidence, maximum)
        if take == 0:
            raise ConfigurationError("council bundle cap cannot hold one diff character")
        part = diff[chars : chars + take]
        bundle = _bundle(scope, evidence, {**common, DIFF: part})
        width = len(part.encode())
        bundles.append(bundle)
        chunks.append(_chunk(bundle, len(chunks), byte, byte + width))
        chars, byte = chars + take, byte + width
    return bundles, chunks


def build_bundle_series(
    *,
    scope: Mapping[str, str],
    evidence_manifest_sha256: str,
    inputs: Mapping[str, str | bytes],
    max_bundle_bytes: int,
) -> dict[str, Any]:
    """Repeat common context and split only the exact diff into bounded bundles."""
    if max_bundle_bytes <= 0:
        raise ConfigurationError("council bundle size cap must be positive")
    common = _decode_inputs(inputs)
    diff = common.pop(DIFF, None)
    if diff is None:
        raise ConfigurationError(f"council inputs are missing {DIFF}")
    if _size(_bundle(scope, evidence_manifest_sha256, {**common, DIFF: ""})) > max_bundle_bytes:
        raise ConfigurationError("council context excluding the diff exceeds the bundle cap")
    bundles, chunks = _chunks(diff, common, scope, evidence_manifest_sha256, max_bundle_bytes)
    raw = diff.encode()
    core = {
        "schema_version": VERSION,
        "kind": "aqg-candidate-bundle-series",
        "scope": {**scope, "evidence_manifest_sha256": evidence_manifest_sha256},
        "diff_bytes": len(raw),
        "diff_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "chunks": chunks,
    }
    return {
        **core,
        "series_sha256": fingerprint(core),
        "max_bundle_bytes": max_bundle_bytes,
        "bundles": bundles,
    }


def series_evidence(series: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in series.items() if key != "bundles"}


def _result_status(statuses: Sequence[str], count_valid: bool) -> str:
    order = (
        "advisory_blocked",
        "advisory_incomplete",
        "advisory_dissent",
        "advisory_concerns",
        "advisory_clear",
    )
    selected = next((item for item in order if item in statuses), "advisory_incomplete")
    return selected if count_valid or selected == "advisory_blocked" else "advisory_incomplete"


def _intersection(results: Sequence[Mapping[str, Any]], field: str) -> list[str]:
    values = [set(map(str, result[field])) for result in results]
    return sorted(set.intersection(*values)) if values else []


def _blockers(results: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"chunk_index": index, **finding}
        for index, result in enumerate(results)
        for finding in result["blockers"]
    ]


def _incomplete(results: Sequence[Mapping[str, Any]], count_valid: bool) -> list[str]:
    reasons = [
        f"chunk {index}: {reason}"
        for index, result in enumerate(results)
        for reason in result["incomplete_reasons"]
    ]
    return reasons if count_valid else [*reasons, "chunk result count does not match bundle count"]


def _dissent(results: Sequence[Mapping[str, Any]]) -> list[int]:
    return [index for index, result in enumerate(results) if result["dissent"]["present"]]


def aggregate_series(
    series: Mapping[str, Any], results: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    statuses = [str(result["status"]) for result in results]
    count_valid = len(results) == len(series["chunks"]) and bool(results)
    status = _result_status(statuses, count_valid)
    dissent = _dissent(results)
    core = {
        "schema_version": VERSION,
        "kind": "aqg-council-series-result",
        "advisory_only": True,
        "authority": AUTHORITY,
        "series_sha256": series["series_sha256"],
        "status": status,
        "complete": count_valid and all(item["complete"] for item in results),
        "provider_groups": _intersection(results, "provider_groups"),
        "covered_roles": _intersection(results, "covered_roles"),
        "blockers": _blockers(results),
        "dissent": {"present": bool(dissent), "chunk_indexes": dissent},
        "incomplete_reasons": sorted(_incomplete(results, count_valid)),
        "chunk_result_sha256s": [item["result_sha256"] for item in results],
        "summary": (
            f"Agent advisory only: {status} across {len(results)} bounded bundle(s); "
            "no human approval or release authority is granted."
        ),
    }
    return {**core, "result_sha256": fingerprint(core)}


def _validate_header(evidence: Mapping[str, Any], bundles: Sequence[Mapping[str, Any]]) -> None:
    core = {
        key: value
        for key, value in evidence.items()
        if key not in {"series_sha256", "max_bundle_bytes"}
    }
    valid = (
        evidence["schema_version"] == VERSION
        and evidence["kind"] == "aqg-candidate-bundle-series"
        and evidence["series_sha256"] == fingerprint(core)
        and len(bundles) == len(evidence["chunks"])
        and bool(bundles)
    )
    if not valid:
        raise ConfigurationError("candidate bundle series identity or count is invalid")


def _validate_chunk(
    raw: Mapping[str, Any],
    chunk: Mapping[str, Any],
    index: int,
    start: int,
    evidence: Mapping[str, Any],
    common: object,
) -> tuple[bytes, object]:
    bundle = validate_candidate_bundle(raw)
    materials = {item["name"]: item for item in bundle["materials"]}
    part = materials.pop(DIFF)["content"].encode()
    shared = (bundle["scope"], materials)
    expected = tuple(
        chunk[key] for key in ("index", "byte_start", "byte_end", "bundle_sha256", "bundle_bytes")
    )
    actual = (index, start, start + len(part), bundle["bundle_sha256"], _size(bundle))
    if (
        (common is not None and shared != common)
        or bundle["scope"] != evidence["scope"]
        or actual != expected
        or _size(bundle) > evidence["max_bundle_bytes"]
    ):
        raise ConfigurationError(f"candidate bundle series chunk {index} is invalid")
    return part, shared


def verify_series(evidence: Mapping[str, Any], bundles: Sequence[Mapping[str, Any]]) -> list[str]:
    try:
        _validate_header(evidence, bundles)
        parts, start, common = [], 0, None
        for index, raw in enumerate(bundles):
            part, shared = _validate_chunk(
                raw, evidence["chunks"][index], index, start, evidence, common
            )
            common = shared
            parts.append(part)
            start += len(part)
        joined = b"".join(parts)
        digest = "sha256:" + hashlib.sha256(joined).hexdigest()
        if len(joined) != evidence["diff_bytes"] or digest != evidence["diff_sha256"]:
            raise ConfigurationError("candidate bundle chunks do not reconstruct the exact diff")
    except (ConfigurationError, KeyError, StopIteration, TypeError, AttributeError) as exc:
        return [str(exc)]
    return []
