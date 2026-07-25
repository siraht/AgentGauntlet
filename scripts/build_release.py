#!/usr/bin/env python3
"""Build deterministic AQG zipapp and portable distribution artifacts."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

FIXED_TIME = (1980, 1, 1, 0, 0, 0)
MAIN = b"from aqg.cli import main\nraise SystemExit(main())\n"


def _version() -> str:
    text = (ROOT / "src" / "aqg" / "constants.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', text, re.MULTILINE)
    if not match:
        raise SystemExit("Could not resolve AQG version")
    return match.group(1)


def _info(name: str, mode: int = 0o644) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | mode) << 16
    return info


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _git(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _source_timestamp() -> str:
    raw = os.environ.get("SOURCE_DATE_EPOCH") or _git("show", "-s", "--format=%ct", "HEAD") or "0"
    timestamp = dt.datetime.fromtimestamp(int(raw), tz=dt.UTC)
    return timestamp.isoformat().replace("+00:00", "Z")


def _source_materials() -> list[dict[str, Any]]:
    paths = [
        ROOT / "LICENSE",
        ROOT / "README.md",
        ROOT / "docs" / "BUILD_TYPE.md",
        ROOT / "install-aqg.sh",
        ROOT / "pyproject.toml",
        ROOT / "scripts" / "build_release.py",
        ROOT / "quality" / "tools" / "js" / "package.json",
        ROOT / "quality" / "tools" / "js" / "package-lock.json",
        ROOT / "quality" / "tools" / "python" / "requirements.lock.txt",
        *sorted((ROOT / "src" / "aqg").rglob("*")),
    ]
    return [
        {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": _sha256(path),
        }
        for path in paths
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    ]


def _write_sbom(path: Path, root: Path, inventory: Any) -> None:
    from aqg.sbom import cyclonedx_document, validate_cyclonedx_document

    document = cyclonedx_document(root, inventory)
    errors = validate_cyclonedx_document(document)
    if errors or not inventory.complete:
        detail = "; ".join([inventory.reason, *errors]).strip("; ")
        raise SystemExit(f"Cannot build complete {path.name}: {detail}")
    _write_json(path, document)


def _write_sboms(output: Path) -> list[Path]:
    from aqg.sbom import Inventory, javascript_inventory, python_inventory

    runtime = Inventory(
        ecosystem="python",
        source=ROOT / "pyproject.toml",
        components=[],
        complete=True,
        reason="AQG runtime has no third-party dependencies",
        dependency_input_present=True,
    )
    values = [
        (output / "aqg-runtime.cdx.json", ROOT, runtime),
        (
            output / "aqg-javascript-toolchain.cdx.json",
            ROOT / "quality" / "tools" / "js",
            javascript_inventory(ROOT / "quality" / "tools" / "js"),
        ),
        (
            output / "aqg-python-toolchain.cdx.json",
            ROOT / "quality" / "tools" / "python",
            python_inventory(ROOT / "quality" / "tools" / "python"),
        ),
    ]
    for path, source_root, inventory in values:
        _write_sbom(path, source_root, inventory)
    return [item[0] for item in values]


def _write_zipapp(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"#!/usr/bin/env python3\n")
    with zipfile.ZipFile(target, "a", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr(_info("__main__.py"), MAIN)
        package = ROOT / "src" / "aqg"
        for path in sorted(package.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            name = (Path("aqg") / path.relative_to(package)).as_posix()
            archive.writestr(_info(name), path.read_bytes())
    target.chmod(0o755)


def _write_portable(
    target: Path,
    zipapp: Path,
    zipapp_checksum: str,
    runtime_sbom: Path,
) -> None:
    installer = ROOT / "install-aqg.sh"
    files = [
        ("aqg.pyz", zipapp.read_bytes(), 0o755),
        ("install-aqg.sh", installer.read_bytes(), 0o755),
        ("README.md", (ROOT / "README.md").read_bytes(), 0o644),
        ("LICENSE", (ROOT / "LICENSE").read_bytes(), 0o644),
        ("aqg.pyz.sha256", f"{zipapp_checksum}  aqg.pyz\n".encode(), 0o644),
        ("aqg-runtime.cdx.json", runtime_sbom.read_bytes(), 0o644),
    ]
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content, mode in files:
            archive.writestr(_info(name, mode), content)


def _provenance_subject(path: Path) -> dict[str, Any]:
    return {"name": path.name, "digest": {"sha256": _sha256(path)}}


def _write_provenance(output: Path, subjects: list[Path], version: str) -> Path:
    path = output / "provenance.intoto.json"
    source_uri = _git("config", "--get", "remote.origin.url")
    revision = os.environ.get("AQG_SOURCE_REVISION") or _git("rev-parse", "HEAD")
    repository = source_uri or "local:AgentGauntlet"
    materials = [
        {
            "name": item["path"],
            "uri": f"{repository}@{revision}#{item['path']}" if revision else item["path"],
            "digest": {"sha256": item["sha256"]},
        }
        for item in _source_materials()
    ]
    payload = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [_provenance_subject(item) for item in sorted(subjects)],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": (
                    "https://github.com/siraht/AgentGauntlet/blob/main/"
                    "docs/BUILD_TYPE.md#portable-v1"
                ),
                "externalParameters": {
                    "version": version,
                    "archive_timestamp": "1980-01-01T00:00:00Z",
                    "compression": "deflate-9",
                },
                "internalParameters": {
                    "sourceDirty": bool(_git("status", "--porcelain", "--untracked-files=no"))
                },
                "resolvedDependencies": [
                    {
                        "uri": repository,
                        "digest": {"gitCommit": revision} if revision else {},
                    },
                    *materials,
                ],
            },
            "runDetails": {
                "builder": {
                    "id": "https://github.com/siraht/AgentGauntlet/scripts/build_release.py"
                },
                "metadata": {
                    "invocationId": revision or "unversioned-source",
                    "startedOn": _source_timestamp(),
                    "finishedOn": _source_timestamp(),
                },
                "byproducts": [],
            },
        },
    }
    _write_json(path, payload)
    return path


def build(output: Path) -> dict[str, str]:
    version = _version()
    output.mkdir(parents=True, exist_ok=True)
    zipapp = output / "aqg.pyz"
    portable = output / f"agent-quality-gauntlet-{version}-portable.zip"
    _write_zipapp(zipapp)
    zipapp_hash = _sha256(zipapp)
    sboms = _write_sboms(output)
    _write_portable(portable, zipapp, zipapp_hash, sboms[0])
    portable_hash = _sha256(portable)
    provenance = _write_provenance(output, [zipapp, portable, *sboms], version)
    (output / "aqg.pyz.sha256").write_text(f"{zipapp_hash}  aqg.pyz\n", encoding="utf-8")
    (output / f"{portable.name}.sha256").write_text(
        f"{portable_hash}  {portable.name}\n",
        encoding="utf-8",
    )
    checksummed = [zipapp, portable, *sboms, provenance]
    (output / "SHA256SUMS").write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in sorted(checksummed)),
        encoding="utf-8",
    )
    return {
        "version": version,
        "zipapp": str(zipapp),
        "zipapp_sha256": zipapp_hash,
        "portable": str(portable),
        "portable_sha256": portable_hash,
        "runtime_sbom": str(sboms[0]),
        "javascript_toolchain_sbom": str(sboms[1]),
        "python_toolchain_sbom": str(sboms[2]),
        "provenance": str(provenance),
        "checksums": str(output / "SHA256SUMS"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    result = build(args.output.resolve())
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
