#!/usr/bin/env python3
"""Build deterministic AQG zipapp and portable distribution artifacts."""

from __future__ import annotations

import argparse
import hashlib
import re
import stat
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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


def _write_portable(target: Path, zipapp: Path, zipapp_checksum: str) -> None:
    installer = ROOT / "install-aqg.sh"
    files = [
        ("aqg.pyz", zipapp.read_bytes(), 0o755),
        ("install-aqg.sh", installer.read_bytes(), 0o755),
        ("README.md", (ROOT / "README.md").read_bytes(), 0o644),
        ("LICENSE", (ROOT / "LICENSE").read_bytes(), 0o644),
        ("aqg.pyz.sha256", f"{zipapp_checksum}  aqg.pyz\n".encode(), 0o644),
    ]
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content, mode in files:
            archive.writestr(_info(name, mode), content)


def build(output: Path) -> dict[str, str]:
    version = _version()
    output.mkdir(parents=True, exist_ok=True)
    zipapp = output / "aqg.pyz"
    portable = output / f"agent-quality-gauntlet-{version}-portable.zip"
    _write_zipapp(zipapp)
    zipapp_hash = _sha256(zipapp)
    _write_portable(portable, zipapp, zipapp_hash)
    portable_hash = _sha256(portable)
    (output / "aqg.pyz.sha256").write_text(f"{zipapp_hash}  aqg.pyz\n", encoding="utf-8")
    (output / f"{portable.name}.sha256").write_text(
        f"{portable_hash}  {portable.name}\n",
        encoding="utf-8",
    )
    (output / "SHA256SUMS").write_text(
        f"{zipapp_hash}  aqg.pyz\n{portable_hash}  {portable.name}\n",
        encoding="utf-8",
    )
    return {
        "version": version,
        "zipapp": str(zipapp),
        "zipapp_sha256": zipapp_hash,
        "portable": str(portable),
        "portable_sha256": portable_hash,
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
