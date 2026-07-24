"""Multi-repository registration and evidence aggregation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .errors import ConfigurationError
from .project import load_project
from .runner import list_runs
from .util import read_json, utc_now, write_json


def config_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "aqg" / "portfolio.json"


def load_portfolio() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {"schema_version": 1, "projects": []}
    payload = read_json(path)
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ConfigurationError(f"invalid portfolio config: {path}")
    return payload


def save_portfolio(payload: dict[str, Any]) -> None:
    write_json(config_path(), payload)


def add_project(root: Path, *, name: str | None = None, tags: list[str] | None = None) -> dict[str, Any]:
    root = root.resolve()
    project = load_project(root)
    payload = load_portfolio()
    projects = [item for item in payload.get("projects", []) if Path(item.get("path", "")).resolve() != root]
    entry = {"name": name or project["name"], "path": str(root), "tags": sorted(set(tags or [])), "added_at": utc_now()}
    projects.append(entry)
    payload["projects"] = sorted(projects, key=lambda item: item["name"].lower())
    save_portfolio(payload)
    return entry


def remove_project(value: str) -> bool:
    payload = load_portfolio()
    before = len(payload.get("projects", []))
    target = Path(value).expanduser().resolve()
    payload["projects"] = [
        item for item in payload.get("projects", [])
        if item.get("name") != value and Path(item.get("path", "")).expanduser().resolve() != target
    ]
    changed = len(payload["projects"]) != before
    if changed:
        save_portfolio(payload)
    return changed


def project_roots() -> list[Path]:
    roots: list[Path] = []
    for item in load_portfolio().get("projects", []):
        path = Path(item.get("path", "")).expanduser().resolve()
        if (path / "quality" / "project.json").exists():
            roots.append(path)
    return roots


def scan_portfolio() -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for entry in load_portfolio().get("projects", []):
        root = Path(entry.get("path", "")).expanduser().resolve()
        if not root.exists():
            items.append({**entry, "status": "missing", "error": "path no longer exists"})
            continue
        try:
            project = load_project(root)
            runs = list_runs(root, 1)
            latest = runs[0] if runs else None
            review_path = root / ".aqg" / "review" / "review.json"
            review = read_json(review_path, default={}) if review_path.exists() else {}
            items.append(
                {
                    **entry,
                    "project": project,
                    "status": latest.get("status", "no_evidence") if latest else "no_evidence",
                    "latest": latest,
                    "review_summary": review.get("summary"),
                }
            )
        except Exception as exc:
            items.append({**entry, "status": "error", "error": str(exc)})
    return {"schema_version": 1, "generated_at": utc_now(), "projects": items}
