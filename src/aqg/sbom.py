"""Deterministic CycloneDX SBOM generation from committed JavaScript and Python locks.

The generator intentionally reads lock artifacts rather than an ambient installation.
That keeps the result reviewable, reproducible, and bound to repository state. It
produces a conservative component inventory; vulnerability analysis remains a
separate gate because an SBOM is an inventory, not a security verdict.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .util import read_json, sha256_file, utc_now, write_json

_PYPI_NAME = re.compile(r"[-_.]+")
_EXACT_REQUIREMENT = re.compile(
    r"^\s*([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?\s*==\s*([^\s;\\]+)(?:\s*;.*)?$"
)
_SEMVERISH = re.compile(r"^[0-9][A-Za-z0-9.+!_-]*$")


@dataclass(slots=True)
class Inventory:
    ecosystem: str
    source: Path | None
    components: list[dict[str, Any]]
    complete: bool
    reason: str = ""
    dependency_input_present: bool = False

    def as_dict(self, root: Path) -> dict[str, Any]:
        return {
            "ecosystem": self.ecosystem,
            "source": self.source.relative_to(root).as_posix() if self.source else None,
            "component_count": len(self.components),
            "complete": self.complete,
            "reason": self.reason,
            "dependency_input_present": self.dependency_input_present,
        }


def _normalise_python_name(name: str) -> str:
    return _PYPI_NAME.sub("-", name).lower()


def _component(name: str, version: str, ecosystem: str) -> dict[str, Any]:
    if ecosystem == "npm":
        normalized = name.strip()
        purl_name = quote(normalized, safe="/")
        purl = f"pkg:npm/{purl_name}@{quote(version, safe='.+!_-')}"
    else:
        normalized = _normalise_python_name(name)
        purl = f"pkg:pypi/{quote(normalized, safe='-')}@{quote(version, safe='.+!_-')}"
    return {
        "type": "library",
        "bom-ref": purl,
        "name": normalized,
        "version": version,
        "purl": purl,
    }


def _dedupe(components: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for component in components:
        ref = str(component.get("bom-ref", ""))
        if ref:
            unique[ref] = component
    return [unique[key] for key in sorted(unique)]


def _project_identity(root: Path, ecosystem: str) -> tuple[str, str, str]:
    if ecosystem == "npm":
        payload = read_json(root / "package.json", default={})
        name = str(payload.get("name") or root.name)
        version = str(payload.get("version") or "0.0.0")
        kind = "application" if payload.get("private") else "library"
        return name, version, kind
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            project = payload.get("project", {}) if isinstance(payload, dict) else {}
            poetry = payload.get("tool", {}).get("poetry", {}) if isinstance(payload, dict) else {}
            name = str(project.get("name") or poetry.get("name") or root.name)
            version = str(project.get("version") or poetry.get("version") or "0.0.0")
            return name, version, "library"
        except (OSError, tomllib.TOMLDecodeError):
            pass
    return root.name, "0.0.0", "application"


def _has_js_dependencies(root: Path) -> bool:
    payload = read_json(root / "package.json", default={})
    return any(
        isinstance(payload.get(key), dict) and payload[key]
        for key in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")
    )


def _has_python_dependencies(root: Path) -> bool:
    for path in root.glob("requirements*.txt"):
        if path.is_file() and any(
            line.strip() and not line.lstrip().startswith(("#", "-r", "--"))
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        ):
            return True
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        return False
    try:
        payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return True
    project = payload.get("project", {}) if isinstance(payload, dict) else {}
    poetry = payload.get("tool", {}).get("poetry", {}) if isinstance(payload, dict) else {}
    return bool(
        project.get("dependencies")
        or project.get("optional-dependencies")
        or poetry.get("dependencies")
        or poetry.get("group")
    )


def _npm_name_from_package_path(path: str, entry: dict[str, Any]) -> str | None:
    name = entry.get("name")
    if isinstance(name, str) and name:
        return name
    marker = "node_modules/"
    if marker not in path:
        return None
    tail = path.rsplit(marker, 1)[-1]
    parts = tail.split("/")
    if tail.startswith("@") and len(parts) >= 2:
        return "/".join(parts[:2])
    return parts[0] if parts else None


def _parse_package_lock(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path, default={})
    components: list[dict[str, Any]] = []
    packages = payload.get("packages") if isinstance(payload, dict) else None
    if isinstance(packages, dict):
        for package_path, entry in packages.items():
            if not package_path or not isinstance(entry, dict):
                continue
            name = _npm_name_from_package_path(str(package_path), entry)
            version = entry.get("version")
            if name and isinstance(version, str) and version:
                components.append(_component(name, version, "npm"))
    elif isinstance(payload, dict):

        def walk(dependencies: dict[str, Any]) -> None:
            for name, entry in dependencies.items():
                if not isinstance(entry, dict):
                    continue
                version = entry.get("version")
                if isinstance(version, str) and version:
                    components.append(_component(str(name), version, "npm"))
                nested = entry.get("dependencies")
                if isinstance(nested, dict):
                    walk(nested)

        dependencies = payload.get("dependencies")
        if isinstance(dependencies, dict):
            walk(dependencies)
    return _dedupe(components)


def _parse_npm_resolution(value: str) -> tuple[str, str] | None:
    candidate = value.strip().strip("'\"")
    candidate = re.sub(r"\([^)]*\)$", "", candidate)
    if candidate.startswith("/"):
        candidate = candidate[1:]
        if candidate.startswith("@"):
            pieces = candidate.split("/")
            if len(pieces) >= 3:
                return "/".join(pieces[:2]), pieces[2]
        pieces = candidate.rsplit("/", 1)
        if len(pieces) == 2:
            return pieces[0], pieces[1]
    if "@npm:" in candidate:
        name, version = candidate.rsplit("@npm:", 1)
        return name, version
    if "@" not in candidate:
        return None
    name, version = candidate.rsplit("@", 1)
    if not name or not version:
        return None
    return name, version


def _parse_pnpm_lock(path: Path) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    section = ""
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if raw and not raw.startswith(" ") and raw.rstrip().endswith(":"):
            section = raw.strip().rstrip(":")
            continue
        if section not in {"packages", "snapshots"}:
            continue
        match = re.match(r"^\s{2}(['\"]?)(.+?)\1:\s*(?:\{.*)?$", raw)
        if not match:
            continue
        parsed = _parse_npm_resolution(match.group(2))
        if parsed and _SEMVERISH.match(parsed[1]):
            components.append(_component(parsed[0], parsed[1], "npm"))
    return _dedupe(components)


def _selector_name(selector: str) -> str | None:
    candidate = selector.strip().strip("'\"").split(",", 1)[0].strip().strip("'\"")
    if candidate.startswith("@"):
        slash = candidate.find("/")
        if slash < 0:
            return None
        at = candidate.find("@", slash)
        return candidate[:at] if at > slash else candidate
    at = candidate.find("@")
    return candidate[:at] if at > 0 else candidate or None


def _parse_yarn_lock(path: Path) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    current_name: str | None = None
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = raw.strip()
        if raw and not raw[0].isspace() and stripped.endswith(":"):
            current_name = _selector_name(stripped[:-1])
            continue
        version_match = re.match(r"^\s+version\s+[\"']([^\"']+)[\"']", raw)
        if version_match and current_name:
            components.append(_component(current_name, version_match.group(1), "npm"))
            continue
        resolution_match = re.match(r"^\s+resolution:\s*[\"']([^\"']+)[\"']", raw)
        if resolution_match:
            parsed = _parse_npm_resolution(resolution_match.group(1))
            if parsed:
                components.append(_component(parsed[0], parsed[1], "npm"))
    return _dedupe(components)


def _strip_jsonc(text: str) -> str:
    out: list[str] = []
    index = 0
    in_string = False
    quote_char = ""
    escaped = False
    while index < len(text):
        char = text[index]
        nxt = text[index + 1] if index + 1 < len(text) else ""
        if in_string:
            out.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote_char:
                in_string = False
            index += 1
            continue
        if char in {'"', "'"}:
            in_string = True
            quote_char = char
            out.append(char)
            index += 1
            continue
        if char == "/" and nxt == "/":
            while index < len(text) and text[index] != "\n":
                index += 1
            continue
        if char == "/" and nxt == "*":
            index += 2
            while index + 1 < len(text) and not (text[index] == "*" and text[index + 1] == "/"):
                if text[index] == "\n":
                    out.append("\n")
                index += 1
            index += 2
            continue
        out.append(char)
        index += 1
    cleaned = "".join(out)
    while True:
        updated = re.sub(r",\s*([}\]])", r"\1", cleaned)
        if updated == cleaned:
            return cleaned
        cleaned = updated


def _parse_bun_lock(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(_strip_jsonc(path.read_text(encoding="utf-8", errors="replace")))
    packages = payload.get("packages", {}) if isinstance(payload, dict) else {}
    components: list[dict[str, Any]] = []
    if isinstance(packages, dict):
        for key, value in packages.items():
            resolution = value[0] if isinstance(value, list) and value else key
            if not isinstance(resolution, str):
                continue
            parsed = _parse_npm_resolution(resolution)
            if parsed:
                components.append(_component(parsed[0], parsed[1], "npm"))
    return _dedupe(components)


def javascript_inventory(root: Path) -> Inventory:
    dependencies = _has_js_dependencies(root)
    candidates = [
        (root / "package-lock.json", _parse_package_lock),
        (root / "npm-shrinkwrap.json", _parse_package_lock),
        (root / "pnpm-lock.yaml", _parse_pnpm_lock),
        (root / "yarn.lock", _parse_yarn_lock),
        (root / "bun.lock", _parse_bun_lock),
    ]
    for path, parser in candidates:
        if not path.exists():
            continue
        try:
            components = parser(path)
        except (OSError, ValueError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
            return Inventory(
                "javascript", path, [], False, f"could not parse {path.name}: {exc}", dependencies
            )
        if dependencies and not components:
            return Inventory(
                "javascript",
                path,
                [],
                False,
                f"{path.name} contained no resolvable dependency components",
                True,
            )
        return Inventory(
            "javascript", path, components, True, dependency_input_present=dependencies
        )
    if dependencies:
        return Inventory(
            "javascript",
            None,
            [],
            False,
            "package.json declares dependencies but no supported committed lockfile exists",
            True,
        )
    if (root / "package.json").exists():
        return Inventory(
            "javascript", None, [], True, "package.json declares no external dependencies", False
        )
    return Inventory("javascript", None, [], True, "no JavaScript package manifest", False)


def _logical_requirements(path: Path, seen: set[Path] | None = None) -> tuple[list[str], bool]:
    seen = seen or set()
    resolved = path.resolve()
    if resolved in seen:
        return [], False
    seen.add(resolved)
    physical = path.read_text(encoding="utf-8", errors="replace").splitlines()
    logical: list[str] = []
    pending = ""
    for raw in physical:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        pending = f"{pending} {stripped}".strip()
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        logical.append(pending)
        pending = ""
    if pending:
        logical.append(pending)
    lines: list[str] = []
    complete = True
    for line in logical:
        include = re.match(r"^(?:-r|--requirement)\s+(.+)$", line)
        if include:
            child = (path.parent / include.group(1).strip()).resolve()
            if child.exists():
                child_lines, child_complete = _logical_requirements(child, seen)
                lines.extend(child_lines)
                complete = complete and child_complete
            else:
                complete = False
            continue
        if line.startswith(("--", "-f ", "-i ", "--index-url", "--extra-index-url")):
            continue
        lines.append(line)
    return lines, complete


def _parse_requirements(path: Path) -> tuple[list[dict[str, Any]], bool]:
    lines, complete = _logical_requirements(path)
    components: list[dict[str, Any]] = []
    for line in lines:
        without_hashes = re.sub(r"\s+--hash=[^\s]+", "", line).strip()
        match = _EXACT_REQUIREMENT.match(without_hashes)
        if not match:
            complete = False
            continue
        components.append(_component(match.group(1), match.group(2), "pypi"))
    return _dedupe(components), complete


def _parse_toml_packages(path: Path) -> list[dict[str, Any]]:
    payload = tomllib.loads(path.read_text(encoding="utf-8"))
    raw: Any = payload.get("package")
    if raw is None:
        raw = payload.get("packages")
    if isinstance(raw, dict):
        raw = list(raw.values())
    components: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            version = entry.get("version")
            if isinstance(name, str) and isinstance(version, str) and version:
                components.append(_component(name, version, "pypi"))
    return _dedupe(components)


def _parse_pipfile_lock(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path, default={})
    components: list[dict[str, Any]] = []
    for section in ("default", "develop"):
        values = payload.get(section, {}) if isinstance(payload, dict) else {}
        if not isinstance(values, dict):
            continue
        for name, entry in values.items():
            version = entry.get("version") if isinstance(entry, dict) else None
            if isinstance(version, str) and version.startswith("=="):
                components.append(_component(str(name), version[2:], "pypi"))
    return _dedupe(components)


def _python_lock_candidates(root: Path) -> list[tuple[Path, Any]]:
    candidates: list[tuple[Path, Any]] = []
    for path in sorted(root.glob("pylock*.toml")):
        candidates.append((path, _parse_toml_packages))
    for name in ("uv.lock", "poetry.lock", "pdm.lock"):
        path = root / name
        if path.exists():
            candidates.append((path, _parse_toml_packages))
    pipfile = root / "Pipfile.lock"
    if pipfile.exists():
        candidates.append((pipfile, _parse_pipfile_lock))
    preferred = [
        root / "requirements.lock.txt",
        root / "requirements.lock",
        root / "requirements-prod.txt",
        root / "requirements.txt",
    ]
    seen = {path for path, _ in candidates}
    for path in [*preferred, *sorted(root.glob("requirements*.txt"))]:
        if path.exists() and path not in seen:
            candidates.append((path, _parse_requirements))
            seen.add(path)
    return candidates


def python_inventory(root: Path) -> Inventory:
    dependencies = _has_python_dependencies(root)
    candidates = _python_lock_candidates(root)
    for path, parser in candidates:
        try:
            parsed = parser(path)
            if isinstance(parsed, tuple):
                components, complete = parsed
            else:
                components, complete = parsed, True
        except (OSError, ValueError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
            return Inventory(
                "python", path, [], False, f"could not parse {path.name}: {exc}", dependencies
            )
        if dependencies and not components:
            return Inventory(
                "python",
                path,
                [],
                False,
                f"{path.name} contained no exact dependency components",
                True,
            )
        reason = (
            ""
            if complete
            else f"{path.name} contains unpinned, editable, VCS, local, or otherwise unresolved requirements"
        )
        return Inventory("python", path, components, complete, reason, dependencies)
    if dependencies:
        return Inventory(
            "python",
            None,
            [],
            False,
            "Python dependencies are declared but no supported exact lock or pinned requirements file exists",
            True,
        )
    if (root / "pyproject.toml").exists() or any(root.glob("requirements*.txt")):
        return Inventory(
            "python", None, [], True, "Python project declares no external dependencies", False
        )
    return Inventory("python", None, [], True, "no Python dependency manifest", False)


def cyclonedx_document(root: Path, inventory: Inventory) -> dict[str, Any]:
    name, version, kind = _project_identity(
        root, "npm" if inventory.ecosystem == "javascript" else "pypi"
    )
    source_properties: list[dict[str, str]] = [
        {"name": "aqg:ecosystem", "value": inventory.ecosystem},
        {"name": "aqg:inventory-complete", "value": str(inventory.complete).lower()},
    ]
    if inventory.source:
        source_properties.extend(
            [
                {"name": "aqg:source-lock", "value": inventory.source.relative_to(root).as_posix()},
                {"name": "aqg:source-lock-sha256", "value": sha256_file(inventory.source)},
            ]
        )
    if inventory.reason:
        source_properties.append({"name": "aqg:inventory-note", "value": inventory.reason})
    serial_seed = json.dumps(
        {
            "component": {"type": kind, "name": name, "version": version},
            "ecosystem": inventory.ecosystem,
            "source": inventory.source.name if inventory.source else None,
            "source_sha256": sha256_file(inventory.source) if inventory.source else None,
            "components": inventory.components,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    serial_digest = hashlib.sha256(serial_seed).hexdigest()
    return {
        "$schema": "https://cyclonedx.org/schema/bom-1.6.schema.json",
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, serial_digest)}",
        "version": 1,
        "metadata": {
            "tools": {
                "components": [
                    {"type": "application", "name": "agent-quality-gauntlet", "version": "2.0.0"}
                ]
            },
            "component": {"type": kind, "name": name, "version": version},
            "properties": source_properties,
        },
        "components": inventory.components,
    }


def _write_inventory(root: Path, inventory: Inventory, output: Path) -> dict[str, Any]:
    document = cyclonedx_document(root, inventory)
    write_json(output, document)
    return {
        **inventory.as_dict(root),
        "status": "generated" if inventory.complete else "incomplete",
        "artifact": output.relative_to(root).as_posix(),
        "sha256": sha256_file(output),
        "format": "CycloneDX JSON",
        "spec_version": "1.6",
    }


def validate_cyclonedx_document(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if document.get("bomFormat") != "CycloneDX":
        errors.append("bomFormat must be CycloneDX")
    if document.get("specVersion") != "1.6":
        errors.append("specVersion must be 1.6")
    if document.get("version") != 1:
        errors.append("version must be 1")
    serial_number = document.get("serialNumber")
    if not isinstance(serial_number, str) or not re.fullmatch(
        r"urn:uuid:[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        serial_number,
    ):
        errors.append("serialNumber must be a deterministic RFC 4122 UUID URN")
    metadata = document.get("metadata")
    if not isinstance(metadata, dict) or not isinstance(metadata.get("component"), dict):
        errors.append("metadata.component is required")
    components = document.get("components")
    if not isinstance(components, list):
        errors.append("components must be an array")
        return errors
    refs: list[str] = []
    for index, component in enumerate(components):
        if not isinstance(component, dict):
            errors.append(f"components[{index}] must be an object")
            continue
        for key in ("type", "name", "version", "bom-ref", "purl"):
            if not isinstance(component.get(key), str) or not component[key]:
                errors.append(f"components[{index}].{key} must be a non-empty string")
        if isinstance(component.get("bom-ref"), str):
            refs.append(component["bom-ref"])
    if len(refs) != len(set(refs)):
        errors.append("component bom-ref values must be unique")
    if refs != sorted(refs):
        errors.append("components must be sorted by bom-ref")
    return errors


def generate_sboms(
    root: Path,
    project: dict[str, Any],
    *,
    output_dir: Path | None = None,
    include_toolchains: bool = True,
) -> dict[str, Any]:
    output_dir = output_dir or root / ".aqg" / "work" / "supply_chain" / "sbom"
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: list[dict[str, Any]] = []
    errors: list[str] = []

    if project.get("stacks", {}).get("javascript"):
        inventory = javascript_inventory(root)
        artifacts.append(
            _write_inventory(root, inventory, output_dir / "project-javascript.cdx.json")
        )
        if not inventory.complete:
            errors.append(f"JavaScript SBOM incomplete: {inventory.reason}")
    if project.get("stacks", {}).get("python"):
        inventory = python_inventory(root)
        artifacts.append(_write_inventory(root, inventory, output_dir / "project-python.cdx.json"))
        if not inventory.complete:
            errors.append(f"Python SBOM incomplete: {inventory.reason}")

    if include_toolchains:
        js_tool_root = root / "quality" / "tools" / "js"
        if (js_tool_root / "package.json").exists():
            inventory = javascript_inventory(js_tool_root)
            target = output_dir / "aqg-javascript-toolchain.cdx.json"
            document = cyclonedx_document(js_tool_root, inventory)
            write_json(target, document)
            artifacts.append(
                {
                    **inventory.as_dict(js_tool_root),
                    "scope": "quality_toolchain",
                    "status": "generated" if inventory.complete else "incomplete",
                    "artifact": target.relative_to(root).as_posix(),
                    "sha256": sha256_file(target),
                    "format": "CycloneDX JSON",
                    "spec_version": "1.6",
                }
            )
            if not inventory.complete:
                errors.append(f"AQG JavaScript toolchain SBOM incomplete: {inventory.reason}")
        py_lock = root / "quality" / "tools" / "python" / "requirements.lock.txt"
        if py_lock.exists():
            components, complete = _parse_requirements(py_lock)
            inventory = Inventory(
                "python",
                py_lock,
                components,
                complete,
                "" if complete else "quality Python lock was not fully exact",
                True,
            )
            target = output_dir / "aqg-python-toolchain.cdx.json"
            # The root identity remains the repository; scope makes the artifact's purpose explicit.
            artifacts.append(
                _write_inventory(root, inventory, target) | {"scope": "quality_toolchain"}
            )
            if not complete:
                errors.append("AQG Python toolchain SBOM incomplete")

    for artifact in artifacts:
        artifact_path = root / artifact["artifact"]
        document = read_json(artifact_path)
        validation_errors = validate_cyclonedx_document(document)
        artifact["validation_errors"] = validation_errors
        if validation_errors:
            errors.extend(f"{artifact['artifact']}: {message}" for message in validation_errors)

    payload = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "format": "CycloneDX JSON",
        "artifacts": artifacts,
        "errors": errors,
        "complete": not errors,
    }
    write_json(output_dir / "index.json", payload)
    payload["index"] = (output_dir / "index.json").relative_to(root).as_posix()
    return payload


def pinned_python_requirements(inventory: Inventory) -> list[str]:
    """Return exact package pins suitable for pip-audit --no-deps."""
    values: list[str] = []
    for component in inventory.components:
        name = str(component.get("name", ""))
        version = str(component.get("version", ""))
        if name and version:
            values.append(f"{name}=={version}")
    return sorted(set(values), key=str.lower)
