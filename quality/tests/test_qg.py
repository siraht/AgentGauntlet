from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ProjectLauncherCompatibilityTests(unittest.TestCase):
    def test_project_launcher_reports_v2(self) -> None:
        result = subprocess.run(
            [sys.executable, "quality/qg.py", "--version"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("2.0.0", result.stdout)

    def test_risk_card_is_valid_and_high_assurance(self) -> None:
        result = subprocess.run(
            [sys.executable, "quality/qg.py", "risk-card", "--json"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["minimum_risk_profile"], "high_assurance")
        self.assertEqual(payload["selected_risk_profile"], "high_assurance")

    def test_doctor_has_no_configuration_errors(self) -> None:
        result = subprocess.run(
            [sys.executable, "quality/qg.py", "doctor", "--json"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["counts"]["error"], 0)


if __name__ == "__main__":
    unittest.main()
