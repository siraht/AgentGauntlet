from __future__ import annotations

import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from scripts import dogfood_control_surfaces as _DOGFOOD


class FunctionalRehearsalContractTests(unittest.TestCase):
    @pytest.mark.mutation_incompatible
    def test_full_rehearsal_proves_public_surfaces_rollback_and_cleanup(self) -> None:
        """AQG-CORE-025 and AQG-RETRO-013: executable QA and rollback replace claims."""
        payload = _DOGFOOD.dogfood()

        _DOGFOOD._validate_payload(payload)
        self.assertEqual(payload["schema_version"], 2)
        self.assertEqual(payload["status"], "pass")
        self.assertTrue(payload["cleanup_verified"])
        self.assertEqual(payload["functional_qa"]["status"], "pass")
        self.assertEqual(
            payload["functional_qa"]["procedure"]["execution_mode"],
            "agent-operated executable procedure",
        )
        self.assertEqual(
            set(payload["functional_qa"]["checks"]),
            set(payload["functional_qa"]["evidence"]),
        )
        self.assertEqual(payload["rollback"]["status"], "pass")
        self.assertTrue(payload["rollback"]["restored_matches_before"])

    def test_result_identity_rejects_evidence_tampering_but_not_timing_variance(self) -> None:
        """AQG-CORE-024: evidence identity covers results but excludes measurements."""
        payload = _valid_payload()
        payload["result_identity"] = _DOGFOOD._result_identity(payload)
        _DOGFOOD._validate_payload(payload)

        timing_changed = deepcopy(payload)
        timing_changed["durations_ms"]["total"] += 10
        _DOGFOOD._validate_payload(timing_changed)

        tampered = deepcopy(payload)
        tampered["rollback"]["operation_outputs_equal"] = False
        with self.assertRaisesRegex(_DOGFOOD.DogfoodFailure, "rollback did not prove"):
            _DOGFOOD._validate_payload(tampered)

        malformed = deepcopy(payload)
        malformed["candidate"]["revision"] = None
        with self.assertRaisesRegex(_DOGFOOD.DogfoodFailure, "candidate revision"):
            _DOGFOOD._validate_payload(malformed)

        contradictory = deepcopy(payload)
        contradictory["rollback"]["restored_identity"] = f"sha256:{'e' * 64}"
        contradictory["result_identity"] = _DOGFOOD._result_identity(contradictory)
        with self.assertRaisesRegex(_DOGFOOD.DogfoodFailure, "before identity"):
            _DOGFOOD._validate_payload(contradictory)

        wrong_procedure = deepcopy(payload)
        wrong_procedure["functional_qa"]["procedure"]["executor"] = "unrecorded operator"
        wrong_procedure["result_identity"] = _DOGFOOD._result_identity(wrong_procedure)
        with self.assertRaises(_DOGFOOD.DogfoodFailure) as raised:
            _DOGFOOD._validate_payload(wrong_procedure)
        self.assertEqual(
            str(raised.exception),
            "functional QA procedure identity or execution mode is invalid",
        )

        extra_qa_key = deepcopy(payload)
        extra_qa_key["functional_qa"]["extra"] = True
        extra_qa_key["result_identity"] = _DOGFOOD._result_identity(extra_qa_key)
        with self.assertRaises(_DOGFOOD.DogfoodFailure) as raised:
            _DOGFOOD._validate_payload(extra_qa_key)
        self.assertEqual(
            str(raised.exception),
            "functional_qa keys differ: expected=['checks', 'evidence', 'procedure', 'status'], "
            "actual=['checks', 'evidence', 'extra', 'procedure', 'status']",
        )

    def test_rollback_restores_exact_tree_and_application_output(self) -> None:
        """AQG-RETRO-013: recovery restores bytes, modes, and observed behavior."""
        with tempfile.TemporaryDirectory(prefix="aqg-rollback-contract-") as temporary:
            workspace = Path(temporary)
            project = workspace / "project"
            _DOGFOOD._seed_project(project)
            before_output = _DOGFOOD._run_seed_operation(project)
            before_snapshot = _DOGFOOD._capture_tree(project)
            before_manifest = _DOGFOOD._tree_manifest(project)
            (project / "candidate.txt").write_text("candidate\n", encoding="utf-8")
            (project / "aqg").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

            evidence = _DOGFOOD._rehearse_rollback(
                project, before_snapshot, before_manifest, before_output
            )

            _DOGFOOD._validate_rollback(evidence)
            self.assertFalse((project / "candidate.txt").exists())
            self.assertEqual(_DOGFOOD._run_seed_operation(project), before_output)

    def test_main_writes_the_same_validated_payload_it_prints(self) -> None:
        """AQG-RETRO-010: the evidence file exactly matches the emitted result."""
        payload = _valid_payload()
        payload["result_identity"] = _DOGFOOD._result_identity(payload)
        with tempfile.TemporaryDirectory(prefix="aqg-dogfood-output-") as temporary:
            output = Path(temporary) / "evidence.json"
            with (
                patch.object(_DOGFOOD, "dogfood", return_value=payload),
                patch.object(sys, "argv", ["dogfood_control_surfaces.py", "--output", str(output)]),
                patch("builtins.print") as printed,
            ):
                self.assertEqual(_DOGFOOD.main(), 0)

            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), payload)
            self.assertEqual(json.loads(printed.call_args.args[0]), payload)

    def test_nested_cli_does_not_inherit_outer_gauntlet_authority(self) -> None:
        completed = _DOGFOOD.subprocess.CompletedProcess([str(_DOGFOOD.QG)], 0, "", "")
        with (
            patch.dict(_DOGFOOD.os.environ, {"AQG_DIFF_BASE": "outer-base"}),
            patch.object(_DOGFOOD.subprocess, "run", return_value=completed) as run,
        ):
            _DOGFOOD._run(["status"], cwd=Path("/tmp"))

        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["AQG_DIFF_BASE"], "")
        self.assertEqual(environment["AQG_POLICY_MAINTENANCE"], "")


def _valid_payload() -> dict[str, Any]:
    evidence = {
        "cold_start": {"bare_help": 0},
        "setup": {"exit_code": 0},
        "review": {"findings": 0},
        "conformance": {"passed": 1},
        "dashboard": {"checks": ["GET /=200"]},
        "tui": {"exit_code": 0},
    }
    return {
        "schema_version": 2,
        "evidence_type": "aqg.functional-rehearsal",
        "status": "pass",
        "candidate": {
            "revision": "a" * 40,
            "dirty": False,
            "source_tree_sha256": "b" * 64,
            "material_count": 1,
        },
        "result_identity": "",
        "durations_ms": {
            "total": 7,
            "cold_start": 1,
            "setup": 1,
            "commands": 1,
            "dashboard": 1,
            "tui": 1,
            "rollback": 1,
        },
        "cleanup": {"method": "TemporaryDirectory", "temporary_workspace_removed": True},
        "cleanup_verified": True,
        "cold_start": evidence["cold_start"],
        "setup": evidence["setup"],
        "functional_qa": {
            "status": "pass",
            "procedure": {
                "id": "QA-AQG-CONTROL-SURFACES-001",
                "path": "qa/procedures/control-surface-rehearsal.md",
                "execution_mode": "agent-operated executable procedure",
                "executor": "aqg deterministic rehearsal",
            },
            "checks": list(evidence),
            "evidence": evidence,
        },
        "rollback": {
            "status": "pass",
            "mechanism": "content-addressed-copy-into-fresh-root",
            "before_identity": f"sha256:{'c' * 64}",
            "candidate_identity": f"sha256:{'d' * 64}",
            "restored_identity": f"sha256:{'c' * 64}",
            "candidate_changed": True,
            "restored_matches_before": True,
            "operation_outputs_equal": True,
        },
    }


if __name__ == "__main__":
    unittest.main()
