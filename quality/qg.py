#!/usr/bin/env python3
"""Agent Quality Gauntlet source-checkout launcher."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from aqg.cli import main

raise SystemExit(main())
