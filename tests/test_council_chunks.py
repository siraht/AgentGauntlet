# Feature-Spec: AgentQualityGauntlet.ReviewCouncil AQG-COUNCIL-013 AQG-COUNCIL-014

from __future__ import annotations

import copy
from typing import Any

import pytest

from aqg.council import build_candidate_bundle, canonical_json, fingerprint
from aqg.council_chunks import aggregate_series, build_bundle_series, series_evidence, verify_series
from aqg.errors import ConfigurationError


def _scope() -> dict[str, str]:
    return {
        "revision": "a" * 40,
        "base_revision": "b" * 40,
        "change_fingerprint": "sha256:" + "1" * 64,
        "control_fingerprint": "sha256:" + "2" * 64,
    }


def _series(diff: str = "α change\n" * 2_000) -> dict[str, Any]:
    return build_bundle_series(
        scope=_scope(),
        evidence_manifest_sha256="sha256:" + "3" * 64,
        inputs={
            "current.diff.patch": diff,
            "feature-spec/contract.md": "The observable contract remains true.\n",
        },
        max_bundle_bytes=2_000,
    )


def _clear_result(**changes: Any) -> dict[str, Any]:
    result = {
        "status": "advisory_clear",
        "complete": True,
        "provider_groups": ["shared", "other"],
        "covered_roles": ["requirements_behavior"],
        "blockers": [],
        "dissent": {"present": False},
        "incomplete_reasons": [],
        "result_sha256": "sha256:" + "4" * 64,
    }
    return {**result, **changes}


def test_oversized_diff_is_exactly_reconstructed_from_bounded_bundles() -> None:
    series = _series()

    assert len(series["bundles"]) > 1
    assert max(chunk["bundle_bytes"] for chunk in series["chunks"]) <= 2_000
    assert verify_series(series_evidence(series), series["bundles"]) == []
    common = [
        {item["name"]: item for item in bundle["materials"] if item["name"] != "current.diff.patch"}
        for bundle in series["bundles"]
    ]
    assert all(materials == common[0] for materials in common)


def test_reordered_missing_and_tampered_chunks_fail_verification() -> None:
    series = _series()
    evidence = series_evidence(series)
    tampered = [dict(bundle) for bundle in series["bundles"]]
    tampered[0]["bundle_sha256"] = "sha256:" + "0" * 64

    assert verify_series(evidence, list(reversed(series["bundles"]))) == [
        "candidate bundle series chunk 0 is invalid"
    ]
    assert verify_series(evidence, series["bundles"][:-1]) == [
        "candidate bundle series identity or count is invalid"
    ]
    assert verify_series(evidence, tampered) == [
        "candidate bundle fingerprint does not match its contents"
    ]
    assert verify_series({}, []) == ["'schema_version'"]
    wrong_diff = dict(evidence)
    wrong_diff["diff_sha256"] = "sha256:" + "0" * 64
    core = {
        key: value
        for key, value in wrong_diff.items()
        if key not in {"series_sha256", "max_bundle_bytes"}
    }
    wrong_diff["series_sha256"] = fingerprint(core)
    assert verify_series(wrong_diff, series["bundles"]) == [
        "candidate bundle chunks do not reconstruct the exact diff"
    ]
    too_small = dict(evidence)
    too_small["max_bundle_bytes"] = evidence["chunks"][0]["bundle_bytes"] - 1
    assert verify_series(too_small, series["bundles"]) == [
        "candidate bundle series chunk 0 is invalid"
    ]


def test_empty_diff_still_produces_one_verified_bundle() -> None:
    series = _series("")

    assert len(series["bundles"]) == 1
    assert series["diff_bytes"] == 0
    assert series["chunks"][0]["byte_start"] == 0
    assert series["chunks"][0]["byte_end"] == 0
    assert verify_series(series_evidence(series), series["bundles"]) == []


def test_smallest_fitting_prefix_is_not_skipped() -> None:
    series = build_bundle_series(
        scope=_scope(),
        evidence_manifest_sha256="sha256:" + "3" * 64,
        inputs={"current.diff.patch": "xx"},
        max_bundle_bytes=725,
    )

    assert [chunk["byte_end"] - chunk["byte_start"] for chunk in series["chunks"]] == [1, 1]


def test_canonical_series_boundaries_and_identity_are_exact() -> None:
    series = build_bundle_series(
        scope=_scope(),
        evidence_manifest_sha256="sha256:" + "3" * 64,
        inputs={"current.diff.patch": "α" * 100},
        max_bundle_bytes=800,
    )

    assert series_evidence(series) == {
        "schema_version": 1,
        "kind": "aqg-candidate-bundle-series",
        "scope": {
            **_scope(),
            "evidence_manifest_sha256": "sha256:" + "3" * 64,
        },
        "diff_bytes": 200,
        "diff_sha256": "sha256:0b5233ba65d47606a07f235fbc3fe5070754c351a19fc783f79de94cf4447add",
        "chunks": [
            {
                "index": 0,
                "byte_start": 0,
                "byte_end": 74,
                "bundle_sha256": "sha256:f473e939b04594d6bc72f24049f9e5e299738c95226533118bb0a91988203b0a",
                "bundle_bytes": 799,
            },
            {
                "index": 1,
                "byte_start": 74,
                "byte_end": 148,
                "bundle_sha256": "sha256:f473e939b04594d6bc72f24049f9e5e299738c95226533118bb0a91988203b0a",
                "bundle_bytes": 799,
            },
            {
                "index": 2,
                "byte_start": 148,
                "byte_end": 200,
                "bundle_sha256": "sha256:18db1c4c21f9be9c39dbaae4f20d723303d13e60e109e91fe90f6becbf838155",
                "bundle_bytes": 777,
            },
        ],
        "series_sha256": "sha256:abc2e3f933355661fa23861c1c33519e1c7c1d138fc42f5311505cd3df943c5e",
        "max_bundle_bytes": 800,
    }
    assert (
        build_bundle_series(
            scope=_scope(),
            evidence_manifest_sha256="sha256:" + "3" * 64,
            inputs={"current.diff.patch": "α" * 100},
            max_bundle_bytes=799,
        )["chunks"][0]["bundle_bytes"]
        == 799
    )


def test_changed_shared_context_is_rejected_even_with_valid_fingerprints() -> None:
    series = _series()
    bundles = list(series["bundles"])
    part = next(
        item["content"] for item in bundles[1]["materials"] if item["name"] == "current.diff.patch"
    )
    replacement = build_candidate_bundle(
        **_scope(),
        evidence_manifest_sha256="sha256:" + "3" * 64,
        inputs={
            "current.diff.patch": part,
            "feature-spec/contract.md": "A different contract.\n",
        },
    )
    bundles[1] = replacement
    evidence = copy.deepcopy(series_evidence(series))
    evidence["chunks"][1]["bundle_sha256"] = replacement["bundle_sha256"]
    evidence["chunks"][1]["bundle_bytes"] = len(canonical_json(replacement))
    core = {
        key: value
        for key, value in evidence.items()
        if key not in {"series_sha256", "max_bundle_bytes"}
    }
    evidence["series_sha256"] = fingerprint(core)

    assert verify_series(evidence, bundles) == ["candidate bundle series chunk 1 is invalid"]


def test_missing_chunk_result_is_incomplete_not_clear() -> None:
    result = aggregate_series(_series("x" * 4_000), [])

    assert result["status"] == "advisory_incomplete"
    assert result["complete"] is False
    assert result["incomplete_reasons"] == ["chunk result count does not match bundle count"]

    partial = aggregate_series(_series(), [_clear_result()])
    assert partial["status"] == "advisory_incomplete"
    assert partial["complete"] is False
    blocked = aggregate_series(_series(), [_clear_result(status="advisory_blocked")])
    assert blocked["status"] == "advisory_blocked"


def test_chunk_blockers_dissent_and_provider_intersection_propagate() -> None:
    series = _series("x" * 4_000)
    results = []
    for index, _chunk in enumerate(series["chunks"]):
        results.append(
            {
                "status": "advisory_blocked" if index == 0 else "advisory_clear",
                "complete": True,
                "provider_groups": ["shared", f"group-{index}"],
                "covered_roles": ["requirements_behavior", "test_evidence"],
                "blockers": [{"id": "F-1"}] if index == 0 else [],
                "dissent": {"present": index == 1},
                "incomplete_reasons": [],
                "result_sha256": f"sha256:{index:064x}",
            }
        )

    result = aggregate_series(series, results)

    assert result["status"] == "advisory_blocked"
    assert result["complete"] is True
    assert result["provider_groups"] == ["shared"]
    assert result["blockers"] == [{"chunk_index": 0, "id": "F-1"}]
    assert result["dissent"] == {"present": True, "chunk_indexes": [1]}


def test_clear_aggregate_contract_is_exact() -> None:
    series = build_bundle_series(
        scope=_scope(),
        evidence_manifest_sha256="sha256:" + "3" * 64,
        inputs={"current.diff.patch": "α" * 100},
        max_bundle_bytes=800,
    )

    result = aggregate_series(series, [_clear_result() for _chunk in series["chunks"]])

    assert result == {
        "schema_version": 1,
        "kind": "aqg-council-series-result",
        "advisory_only": True,
        "authority": (
            "Agent advisory only; this does not constitute human approval, code-owner "
            "approval, policy approval, or release authority."
        ),
        "series_sha256": series["series_sha256"],
        "status": "advisory_clear",
        "complete": True,
        "provider_groups": ["other", "shared"],
        "covered_roles": ["requirements_behavior"],
        "blockers": [],
        "dissent": {"present": False, "chunk_indexes": []},
        "incomplete_reasons": [],
        "chunk_result_sha256s": ["sha256:" + "4" * 64] * 3,
        "summary": (
            "Agent advisory only: advisory_clear across 3 bounded bundle(s); "
            "no human approval or release authority is granted."
        ),
        "result_sha256": "sha256:a2a9bd9a2830501c1d4f17c0f546d1ce08921356a7e126859435821b4b983c62",
    }


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("advisory_clear", "advisory_clear"),
        ("advisory_concerns", "advisory_concerns"),
        ("advisory_dissent", "advisory_dissent"),
        ("advisory_incomplete", "advisory_incomplete"),
        ("advisory_blocked", "advisory_blocked"),
    ],
)
def test_each_chunk_status_propagates(status: str, expected: str) -> None:
    series = _series("")
    result = aggregate_series(series, [_clear_result(status=status)])

    assert result["status"] == expected


def test_unknown_chunk_status_is_conservatively_incomplete() -> None:
    series = _series("")
    result = aggregate_series(series, [_clear_result(status="unknown")])

    assert result["status"] == "advisory_incomplete"


def test_shared_context_that_exceeds_cap_fails_without_dropping_material() -> None:
    with pytest.raises(ConfigurationError) as error:
        build_bundle_series(
            scope=_scope(),
            evidence_manifest_sha256="sha256:" + "3" * 64,
            inputs={"current.diff.patch": "small", "requirements.md": "x" * 3_000},
            max_bundle_bytes=1_000,
        )
    assert str(error.value) == "council context excluding the diff exceeds the bundle cap"


@pytest.mark.parametrize(
    ("inputs", "maximum", "message"),
    [
        ({"current.diff.patch": "x"}, 0, "council bundle size cap must be positive"),
        (
            {"current.diff.patch": "x"},
            1,
            "council context excluding the diff exceeds the bundle cap",
        ),
        (
            {"requirements.md": "x"},
            2_000,
            "council inputs are missing current.diff.patch",
        ),
        ({"current.diff.patch": b"\xff"}, 2_000, "council materials must be UTF-8 text"),
        (
            {"current.diff.patch": "x"},
            724,
            "council bundle cap cannot hold one diff character",
        ),
    ],
)
def test_invalid_series_inputs_fail_closed(
    inputs: dict[str, str | bytes], maximum: int, message: str
) -> None:
    with pytest.raises(ConfigurationError) as error:
        build_bundle_series(
            scope=_scope(),
            evidence_manifest_sha256="sha256:" + "3" * 64,
            inputs=inputs,
            max_bundle_bytes=maximum,
        )
    assert str(error.value) == message
