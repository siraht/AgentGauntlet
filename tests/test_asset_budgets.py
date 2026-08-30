from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path

import pytest

from aqg.asset_budgets import measure_asset_budgets
from aqg.errors import ConfigurationError, InfrastructureError


def _limits(value: int = 10_000) -> dict[str, int]:
    return {
        f"max_{kind}_{scope}_{encoding}_bytes": value
        for kind in ("javascript", "css")
        for scope in ("file", "total")
        for encoding in ("raw", "gzip")
    }


def _measure(root: Path, **overrides: object) -> dict[str, object]:
    options: dict[str, object] = {
        "build_roots": ["dist"],
        "limits": _limits(),
        "warning_ratio": 0.8,
    }
    options.update(overrides)
    return measure_asset_budgets(root, **options)  # type: ignore[arg-type]


def test_measures_stably_sorted_javascript_and_css_with_complete_evidence(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "z.css").write_bytes(b"a{color:red}\n")
    (dist / "a.mjs").write_bytes(b"export default 1\n")
    (dist / "b.cjs").write_bytes(b"module.exports=2\n")

    report = _measure(tmp_path)

    assert [item["path"] for item in report["artifacts"]] == [
        "dist/a.mjs",
        "dist/b.cjs",
        "dist/z.css",
    ]
    assert report["totals"]["javascript"]["artifact_count"] == 2
    assert report["totals"]["css"]["artifact_count"] == 1
    assert report["summary"] == {
        "status": "pass",
        "artifact_count": 3,
        "failure_count": 0,
        "warning_count": 0,
    }
    first = report["artifacts"][0]
    assert first["sha256"].startswith("sha256:")
    assert first["mtime_ns"] > 0
    assert first["build_root"] == "dist"
    assert report["evidence_sha256"].startswith("sha256:")
    json.dumps(report, sort_keys=True)
    assert report == _measure(tmp_path)
    core = {key: value for key, value in report.items() if key != "evidence_sha256"}
    encoded = json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert report["evidence_sha256"] == "sha256:" + hashlib.sha256(encoded).hexdigest()


def test_gzip_measurement_is_deterministic_and_uses_zero_mtime(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    content = b"const repeated = 'xxxxxxxxxxxxxxxxxxxxxxxx';\n" * 10
    artifact = dist / "app.js"
    artifact.write_bytes(content)

    first = _measure(tmp_path)
    os.utime(artifact, ns=(artifact.stat().st_atime_ns, artifact.stat().st_mtime_ns + 1_000_000))
    second = _measure(tmp_path)

    assert first["artifacts"][0]["gzip_bytes"] == len(
        gzip.compress(content, compresslevel=9, mtime=0)
    )
    assert first["artifacts"][0]["gzip_bytes"] == second["artifacts"][0]["gzip_bytes"]
    assert first["compression"]["mtime"] == 0


def test_exact_limit_passes_but_warning_boundary_is_inclusive(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "app.js").write_bytes(b"12345678")
    limits = _limits(1_000)
    limits["max_javascript_file_raw_bytes"] = 10
    limits["max_javascript_total_raw_bytes"] = 8

    report = _measure(tmp_path, limits=limits)

    artifact_budget = report["artifacts"][0]["budgets"]["raw_bytes"]
    total_budget = report["totals"]["javascript"]["budgets"]["raw_bytes"]
    assert artifact_budget["status"] == "warning"
    assert artifact_budget["warning_at"] == 8
    assert total_budget["status"] == "warning"
    assert total_budget["remaining"] == 0
    assert report["summary"]["failure_count"] == 0


def test_one_byte_over_individual_limit_is_a_failure(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "app.css").write_bytes(b"123456789")
    limits = _limits(1_000)
    limits["max_css_file_raw_bytes"] = 8

    report = _measure(tmp_path, limits=limits)

    assert report["summary"]["status"] == "failure"
    assert any(
        item["scope"] == "dist/app.css"
        and item["metric"] == "file_raw_bytes"
        and item["observed"] == 9
        for item in report["findings"]
    )


def test_aggregate_budgets_prevent_file_splitting_evasion(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "one.css").write_bytes(b"123456")
    (dist / "two.css").write_bytes(b"abcdef")
    limits = _limits(1_000)
    limits["max_css_file_raw_bytes"] = 10
    limits["max_css_total_raw_bytes"] = 10

    report = _measure(tmp_path, limits=limits)

    assert all(item["budgets"]["raw_bytes"]["status"] != "failure" for item in report["artifacts"])
    assert report["totals"]["css"]["raw_bytes"] == 12
    assert report["totals"]["css"]["budgets"]["raw_bytes"]["status"] == "failure"
    assert any(item["scope"] == "css:aggregate" for item in report["findings"])


def test_javascript_and_css_aggregate_budgets_are_independent(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "app.js").write_bytes(b"j" * 8)
    (dist / "app.css").write_bytes(b"c" * 5)
    limits = _limits(1_000)
    limits["max_javascript_total_raw_bytes"] = 7
    limits["max_css_total_raw_bytes"] = 6

    report = _measure(tmp_path, limits=limits)

    assert report["totals"]["javascript"]["budgets"]["raw_bytes"]["status"] == "failure"
    assert report["totals"]["css"]["budgets"]["raw_bytes"]["status"] == "warning"


@pytest.mark.parametrize(
    ("limits", "warning_ratio", "fresh_after_ns", "message"),
    [
        ({}, 0.8, None, "missing limits"),
        ({**_limits(), "extra": 1}, 0.8, None, "unknown limits"),
        ({**_limits(), "max_css_file_raw_bytes": 0}, 0.8, None, "positive integer"),
        ({**_limits(), "max_css_file_raw_bytes": True}, 0.8, None, "positive integer"),
        (_limits(), 1.0, None, "less than 1"),
        (_limits(), float("nan"), None, "greater than 0"),
        (_limits(), 0.8, -1, "non-negative integer"),
    ],
)
def test_invalid_limits_and_measurement_configuration_fail_closed(
    tmp_path: Path,
    limits: dict[str, object],
    warning_ratio: float,
    fresh_after_ns: int | None,
    message: str,
) -> None:
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist" / "app.js").write_text("x", encoding="utf-8")

    with pytest.raises(ConfigurationError, match=message):
        _measure(
            tmp_path,
            limits=limits,
            warning_ratio=warning_ratio,
            fresh_after_ns=fresh_after_ns,
        )


@pytest.mark.parametrize("build_roots", [[], ["missing"], ["../outside"]])
def test_missing_or_escaping_build_roots_fail_closed(
    tmp_path: Path, build_roots: list[str]
) -> None:
    error = ConfigurationError if not build_roots or ".." in build_roots[0] else InfrastructureError
    with pytest.raises(error):
        _measure(tmp_path, build_roots=build_roots)


def test_malformed_build_root_collection_fails_as_configuration(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="sequence"):
        _measure(tmp_path, build_roots={"dist": "unexpected"})
    with pytest.raises(ConfigurationError, match="string or Path"):
        _measure(tmp_path, build_roots=[123])


def test_empty_or_inapplicable_build_roots_fail_closed(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<p>hello</p>", encoding="utf-8")

    with pytest.raises(InfrastructureError, match="no JavaScript or CSS"):
        _measure(tmp_path)


def test_overlapping_build_roots_are_rejected(tmp_path: Path) -> None:
    (tmp_path / "dist" / "nested").mkdir(parents=True)
    with pytest.raises(ConfigurationError, match="must not overlap"):
        _measure(tmp_path, build_roots=["dist", "dist/nested"])


def test_symlink_file_and_root_are_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "app.js").write_text("x", encoding="utf-8")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "linked.js").symlink_to(outside / "app.js")

    with pytest.raises(ConfigurationError, match="symlink file"):
        _measure(tmp_path)

    (dist / "linked.js").unlink()
    (tmp_path / "linked-dist").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ConfigurationError, match="traverses symlink"):
        _measure(tmp_path, build_roots=["linked-dist"])


def test_freshness_accepts_boundary_and_rejects_stale_artifact(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    artifact = dist / "app.js"
    artifact.write_text("x", encoding="utf-8")
    modified = artifact.stat().st_mtime_ns

    report = _measure(tmp_path, fresh_after_ns=modified)
    assert report["fresh_after_ns"] == modified

    with pytest.raises(InfrastructureError, match="stale"):
        _measure(tmp_path, fresh_after_ns=modified + 1)


def test_unreadable_artifact_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    artifact = dist / "app.js"
    artifact.write_text("x", encoding="utf-8")
    original = Path.read_bytes

    def fail_read(path: Path) -> bytes:
        if path == artifact:
            raise PermissionError("deliberate denial")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", fail_read)
    with pytest.raises(InfrastructureError, match="cannot read built artifact"):
        _measure(tmp_path)
