# Feature-Spec: AgentQualityGauntlet.Retrospective AQG-RETRO-003 AQG-RETRO-004 AQG-RETRO-005
"""Unit tests for the pure reviewed debt-baseline core."""

from __future__ import annotations

import copy
import math
import unittest

from aqg.debt import (
    DebtError,
    compare,
    document_fingerprint,
    normalize_inventory,
    validate_baseline,
)


def _item(
    fingerprint: str,
    *,
    category: str = "coverage",
    path: str = "src/app.py",
    severity: str = "medium",
    location: str | None = "line:10",
    value: float | int | None = 10,
    direction: str | None = "higher_is_worse",
) -> dict:
    payload: dict = {
        "fingerprint": fingerprint,
        "category": category,
        "path": path,
        "severity": severity,
    }
    if location is not None:
        payload["location"] = location
    if value is not None:
        payload["value"] = value
        payload["direction"] = direction
    return payload


def _baseline(
    inventory: list[dict],
    *,
    state: str = "reviewed",
    reviewer: str | None = "alice",
    reviewed_at: str | None = "2026-07-28T00:00:00+00:00",
) -> dict:
    document: dict = {
        "schema_version": 1,
        "state": state,
        "source_revision": "abc123",
        "policy_fingerprint": "sha256:policy",
        "control_fingerprint": "sha256:control",
        "created_at": "2026-07-27T12:00:00+00:00",
        "measurement": {
            "run_id": "20260727-audit",
            "profile": "shadow",
            "measured_at": "2026-07-27T11:59:00Z",
        },
        "inventory": inventory,
    }
    if reviewer is not None:
        document["reviewer"] = reviewer
    if reviewed_at is not None:
        document["reviewed_at"] = reviewed_at
    return document


class NormalizeInventoryTests(unittest.TestCase):
    def test_deterministic_ordering_and_path_normalization(self) -> None:
        items = [
            _item("b", path="./src/z.py", location="L2", category="structure"),
            _item("a", path="src\\a.py", location="L1", category="coverage"),
            _item("c", path="src/m.py", location=None, value=None, severity="low"),
        ]
        first = normalize_inventory(items)
        second = normalize_inventory(list(reversed(items)))
        self.assertEqual(first, second)
        self.assertEqual([item["fingerprint"] for item in first], ["a", "b", "c"])
        self.assertEqual(first[0]["path"], "src/a.py")
        self.assertEqual(first[1]["path"], "src/z.py")
        self.assertNotIn("location", first[2])
        self.assertNotIn("value", first[2])

    def test_rejects_duplicate_fingerprints(self) -> None:
        with self.assertRaises(DebtError) as ctx:
            normalize_inventory([_item("same"), _item("same", path="other.py")])
        self.assertIn("duplicate", str(ctx.exception).lower())

    def test_rejects_malformed_items_and_inventory(self) -> None:
        with self.assertRaises(DebtError):
            normalize_inventory("not-a-list")  # type: ignore[arg-type]
        with self.assertRaises(DebtError):
            normalize_inventory([{"fingerprint": "x"}])
        with self.assertRaises(DebtError):
            normalize_inventory([_item("x", severity="apocalyptic")])
        with self.assertRaises(DebtError):
            normalize_inventory([_item("x", value="high")])  # type: ignore[arg-type]
        with self.assertRaises(DebtError):
            normalize_inventory([_item("x", value=True)])  # type: ignore[arg-type]
        with self.assertRaises(DebtError):
            normalize_inventory([_item("x", value=math.inf)])
        with self.assertRaises(DebtError):
            normalize_inventory([_item("x", direction=None)])
        with self.assertRaises(DebtError):
            normalize_inventory([_item("x", path="../escape.py")])


class ValidateBaselineTests(unittest.TestCase):
    def test_document_fingerprint_is_deterministic(self) -> None:
        inventory = [
            _item("z", path="src/z.py"),
            _item("a", path="src/a.py"),
        ]
        left = _baseline(inventory)
        right = _baseline(list(reversed(copy.deepcopy(inventory))))
        self.assertEqual(document_fingerprint(left), document_fingerprint(right))
        self.assertTrue(document_fingerprint(left).startswith("sha256:"))
        # Provenance change must change the fingerprint.
        mutated = validate_baseline(left)
        mutated["source_revision"] = "other"
        self.assertNotEqual(document_fingerprint(left), document_fingerprint(mutated))

    def test_proposed_baseline_omits_reviewer_requirement(self) -> None:
        document = _baseline([_item("a")], state="proposed", reviewer=None, reviewed_at=None)
        validated = validate_baseline(document)
        self.assertEqual(validated["state"], "proposed")
        self.assertNotIn("reviewer", validated)
        self.assertNotIn("reviewed_at", validated)

    def test_rejects_invalid_state_and_missing_identity(self) -> None:
        with self.assertRaises(DebtError):
            validate_baseline(_baseline([_item("a")], state="draft"))
        for field in (
            "source_revision",
            "policy_fingerprint",
            "control_fingerprint",
            "created_at",
        ):
            broken = _baseline([_item("a")])
            broken[field] = ""
            with self.assertRaises(DebtError):
                validate_baseline(broken)
        with self.assertRaises(DebtError):
            validate_baseline({**_baseline([_item("a")]), "schema_version": 2})
        with self.assertRaises(DebtError):
            validate_baseline({**_baseline([_item("a")]), "inventory": "bad"})
        with self.assertRaises(DebtError):
            validate_baseline({**_baseline([_item("a")]), "created_at": "not-a-time"})
        with self.assertRaises(DebtError):
            validate_baseline({**_baseline([_item("a")]), "measurement": {}})

    def test_reviewed_requires_reviewer_and_reviewed_at(self) -> None:
        with self.assertRaises(DebtError):
            validate_baseline(
                _baseline([_item("a")], reviewer=None, reviewed_at="2026-07-28T00:00:00Z")
            )
        with self.assertRaises(DebtError):
            validate_baseline(_baseline([_item("a")], reviewer="alice", reviewed_at=None))
        with self.assertRaises(DebtError):
            validate_baseline(
                _baseline([_item("a")], reviewer="  ", reviewed_at="2026-07-28T00:00:00Z")
            )
        with self.assertRaises(DebtError):
            validate_baseline(_baseline([_item("a")], reviewed_at="yesterday"))
        proposed = _baseline([_item("a")], state="proposed")
        with self.assertRaises(DebtError):
            validate_baseline(proposed)


class CompareTests(unittest.TestCase):
    def test_classifies_every_comparison_bucket(self) -> None:
        baseline = _baseline(
            [
                _item("keep", value=10, severity="medium"),
                _item("gone", value=4, severity="low"),
                _item("worse-num", value=5, severity="medium"),
                _item("worse-sev", value=3, severity="low"),
            ]
        )
        current = [
            _item("keep", value=10, severity="medium"),  # inherited
            _item("worse-num", value=9, severity="medium"),  # numeric regression
            _item("worse-sev", value=3, severity="high"),  # severity regression
            _item("fresh", value=1, severity="info"),  # new
            {"fingerprint": "broken"},  # invalid
        ]
        result = compare(current, baseline)
        self.assertEqual([item["fingerprint"] for item in result["inherited"]], ["keep"])
        self.assertEqual([item["fingerprint"] for item in result["resolved"]], ["gone"])
        self.assertEqual(
            sorted(item["fingerprint"] for item in result["regressed"]),
            ["worse-num", "worse-sev"],
        )
        self.assertEqual([item["fingerprint"] for item in result["new"]], ["fresh"])
        self.assertEqual(
            result["invalid"],
            [{"index": 4, "error": "category must be a non-empty string"}],
        )

    def test_numeric_worsening_and_improvement(self) -> None:
        baseline = _baseline([_item("metric", value=20, severity="medium")])
        regressed = compare([_item("metric", value=21, severity="medium")], baseline)
        improved = compare([_item("metric", value=5, severity="medium")], baseline)
        self.assertEqual([item["fingerprint"] for item in regressed["regressed"]], ["metric"])
        self.assertEqual(regressed["inherited"], [])
        self.assertEqual([item["fingerprint"] for item in improved["inherited"]], ["metric"])
        self.assertEqual(improved["regressed"], [])

    def test_severity_worsening_and_stable_equal_severity(self) -> None:
        baseline = _baseline([_item("sev", value=2, severity="low")])
        regressed = compare([_item("sev", value=2, severity="critical")], baseline)
        same = compare([_item("sev", value=2, severity="low")], baseline)
        softer = compare([_item("sev", value=2, severity="info")], baseline)
        self.assertEqual([item["fingerprint"] for item in regressed["regressed"]], ["sev"])
        self.assertEqual([item["fingerprint"] for item in same["inherited"]], ["sev"])
        self.assertEqual([item["fingerprint"] for item in softer["inherited"]], ["sev"])

    def test_lower_is_worse_and_fingerprint_collision_are_not_misclassified(self) -> None:
        baseline = _baseline(
            [_item("coverage", value=85, direction="lower_is_worse", severity="medium")]
        )
        regressed = compare(
            [_item("coverage", value=84, direction="lower_is_worse", severity="medium")],
            baseline,
        )
        improved = compare(
            [_item("coverage", value=90, direction="lower_is_worse", severity="medium")],
            baseline,
        )
        collision = compare(
            [
                _item(
                    "coverage",
                    path="src/other.py",
                    value=85,
                    direction="lower_is_worse",
                )
            ],
            baseline,
        )
        self.assertEqual([item["fingerprint"] for item in regressed["regressed"]], ["coverage"])
        self.assertEqual([item["fingerprint"] for item in improved["inherited"]], ["coverage"])
        self.assertEqual(collision["inherited"], [])
        self.assertEqual(
            collision["invalid"],
            [{"fingerprint": "coverage", "error": "fingerprint identity fields changed"}],
        )

    def test_rejects_proposed_and_invalid_baselines(self) -> None:
        proposed = _baseline([_item("a")], state="proposed", reviewer=None, reviewed_at=None)
        with self.assertRaises(DebtError) as ctx:
            compare([_item("a")], proposed)
        self.assertIn("reviewed", str(ctx.exception).lower())
        invalid = _baseline([_item("a")], reviewer="")
        with self.assertRaises(DebtError):
            compare([_item("a")], invalid)
        with self.assertRaises(DebtError):
            compare("not-list", _baseline([_item("a")]))  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
