"""Repository stack and command detection used by one-command onboarding."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .constants import DEFAULT_EXCLUDES
from .util import command_exists, iter_files

JS_SUFFIXES = {".js", ".jsx", ".mjs", ".cjs"}
TS_SUFFIXES = {".ts", ".tsx", ".mts", ".cts"}
PY_SUFFIXES = {".py", ".pyi"}
HTML_SUFFIXES = {".html", ".htm"}
CSS_SUFFIXES = {".css", ".scss", ".sass", ".less"}
TEST_MARKERS = ("test", "tests", "spec", "specs", "__tests__", "e2e")


@dataclass(slots=True)
class Detection:
    name: str
    javascript: bool
    typescript: bool
    python: bool
    html: bool
    css: bool
    package_manager: str | None
    python_manager: str | None
    frameworks: list[str]
    source_paths: list[str]
    test_paths: list[str]
    html_paths: list[str]
    css_paths: list[str]
    js_test_runner: str | None
    python_test_runner: str | None
    start_command: list[str] | None
    build_command: list[str] | None
    package_scripts: dict[str, str]
    notes: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _safe_package(root: Path) -> dict[str, Any]:
    path = root / "package.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _package_manager(root: Path, package: dict[str, Any]) -> str | None:
    declared = str(package.get("packageManager", ""))
    if declared:
        manager = declared.split("@", 1)[0]
        if manager in {"npm", "pnpm", "yarn", "bun"}:
            return manager
    for filename, manager in (
        ("pnpm-lock.yaml", "pnpm"),
        ("yarn.lock", "yarn"),
        ("bun.lockb", "bun"),
        ("bun.lock", "bun"),
        ("package-lock.json", "npm"),
        ("npm-shrinkwrap.json", "npm"),
    ):
        if (root / filename).exists():
            return manager
    if package:
        for manager in ("pnpm", "yarn", "bun", "npm"):
            if command_exists(manager):
                return manager
        return "npm"
    return None


def _python_manager(root: Path) -> str | None:
    if (root / "uv.lock").exists() or (root / "pyproject.toml").exists() and command_exists("uv"):
        return "uv"
    if (root / "poetry.lock").exists():
        return "poetry"
    if (root / "Pipfile.lock").exists() or (root / "Pipfile").exists():
        return "pipenv"
    if (
        any(root.glob("requirements*.txt"))
        or (root / "setup.py").exists()
        or (root / "setup.cfg").exists()
    ):
        return "pip"
    if (root / "pyproject.toml").exists():
        return "uv" if command_exists("uv") else "pip"
    return None


def _frameworks(package: dict[str, Any], root: Path) -> list[str]:
    deps: dict[str, Any] = {}
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        value = package.get(key, {})
        if isinstance(value, dict):
            deps.update(value)
    mapping = {
        "next": "next",
        "nuxt": "nuxt",
        "react": "react",
        "vue": "vue",
        "svelte": "svelte",
        "@sveltejs/kit": "sveltekit",
        "astro": "astro",
        "vite": "vite",
        "express": "express",
        "fastify": "fastify",
        "nestjs": "nestjs",
        "@nestjs/core": "nestjs",
        "playwright": "playwright",
        "@playwright/test": "playwright",
        "vitest": "vitest",
        "jest": "jest",
        "django": "django",
        "flask": "flask",
        "fastapi": "fastapi",
    }
    found = {label for dependency, label in mapping.items() if dependency in deps}
    pyproject = root / "pyproject.toml"
    requirements = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in [pyproject, *root.glob("requirements*.txt")]
        if path.exists()
    ).lower()
    for token, label in (
        ("django", "django"),
        ("flask", "flask"),
        ("fastapi", "fastapi"),
        ("pytest", "pytest"),
    ):
        if re.search(rf"\b{re.escape(token)}\b", requirements):
            found.add(label)
    return sorted(found)


def _path_roots(root: Path, files: list[Path]) -> list[str]:
    preferred = [
        "src",
        "app",
        "lib",
        "packages",
        "apps",
        "server",
        "client",
        "frontend",
        "backend",
        "public",
        "static",
        "templates",
    ]
    roots: set[str] = set()
    for name in preferred:
        candidate = root / name
        if candidate.exists() and any(
            path == candidate or candidate in path.parents for path in files
        ):
            roots.add(name)
    for path in files:
        rel = path.relative_to(root)
        if len(rel.parts) == 1:
            roots.add(".")
        elif rel.parts[0] not in {"quality", "docs", "ci", ".github"}:
            roots.add(rel.parts[0])
    return sorted(roots)


def _test_paths(root: Path, files: list[Path]) -> list[str]:
    result: set[str] = set()
    for path in files:
        rel = path.relative_to(root)
        lower_parts = [part.lower() for part in rel.parts]
        filename = rel.name.lower()
        if any(marker in lower_parts for marker in TEST_MARKERS) or re.search(
            r"(?:^|[._-])(test|spec)(?:[._-]|$)", filename
        ):
            result.add(rel.parts[0] if len(rel.parts) > 1 else rel.as_posix())
    return sorted(result)


def _js_test_runner(package: dict[str, Any]) -> str | None:
    scripts = package.get("scripts", {}) if isinstance(package.get("scripts"), dict) else {}
    deps: dict[str, Any] = {}
    for key in ("dependencies", "devDependencies"):
        value = package.get(key, {})
        if isinstance(value, dict):
            deps.update(value)
    haystack = " ".join([*map(str, scripts.values()), *deps.keys()]).lower()
    for needle, runner in (
        ("vitest", "vitest"),
        ("jest", "jest"),
        ("mocha", "mocha"),
        ("ava", "ava"),
        ("node --test", "node"),
        ("playwright", "playwright"),
    ):
        if needle in haystack:
            return runner
    return None


def _script_command(manager: str | None, script: str) -> list[str] | None:
    if not manager:
        return None
    if manager == "npm":
        return ["npm", "run", script]
    if manager == "pnpm":
        return ["pnpm", script]
    if manager == "yarn":
        return ["yarn", script]
    if manager == "bun":
        return ["bun", "run", script]
    return None


def detect_project(root: Path) -> Detection:
    excludes = list(DEFAULT_EXCLUDES)
    all_code = iter_files(
        root, JS_SUFFIXES | TS_SUFFIXES | PY_SUFFIXES | HTML_SUFFIXES | CSS_SUFFIXES, excludes
    )
    js_files = [path for path in all_code if path.suffix.lower() in JS_SUFFIXES]
    ts_files = [path for path in all_code if path.suffix.lower() in TS_SUFFIXES]
    py_files = [path for path in all_code if path.suffix.lower() in PY_SUFFIXES]
    html_files = [path for path in all_code if path.suffix.lower() in HTML_SUFFIXES]
    css_files = [path for path in all_code if path.suffix.lower() in CSS_SUFFIXES]

    package = _safe_package(root)
    manager = _package_manager(root, package)
    scripts = (
        {str(k): str(v) for k, v in package.get("scripts", {}).items()}
        if isinstance(package.get("scripts"), dict)
        else {}
    )
    javascript = bool(package or js_files or ts_files)
    typescript = bool(ts_files or (root / "tsconfig.json").exists())
    python = bool(
        py_files or (root / "pyproject.toml").exists() or any(root.glob("requirements*.txt"))
    )
    html = bool(html_files)
    css = bool(css_files)
    files_for_sources = [
        path
        for path in all_code
        if not any(
            marker in [part.lower() for part in path.relative_to(root).parts]
            for marker in TEST_MARKERS
        )
    ]
    source_paths = _path_roots(root, files_for_sources)
    test_paths = _test_paths(root, all_code)
    html_paths = _path_roots(root, html_files)
    css_paths = _path_roots(root, css_files)
    notes: list[str] = []
    if javascript and not package:
        notes.append(
            "JavaScript/TypeScript files found without a root package.json; AQG will use its isolated quality toolchain."
        )
    if files_for_sources and not test_paths:
        notes.append(
            "Production source was found but no test directory or test-named file was detected."
        )
    if typescript and not (root / "tsconfig.json").exists():
        notes.append(
            "TypeScript files were found without tsconfig.json; AQG will generate a strict analysis overlay."
        )

    start_command = None
    for script in ("start", "dev", "serve", "preview"):
        if script in scripts:
            start_command = _script_command(manager, script)
            break
    build_command = _script_command(manager, "build") if "build" in scripts else None

    name = str(package.get("name") or root.name)
    return Detection(
        name=name,
        javascript=javascript,
        typescript=typescript,
        python=python,
        html=html,
        css=css,
        package_manager=manager,
        python_manager=_python_manager(root) if python else None,
        frameworks=_frameworks(package, root),
        source_paths=source_paths or ["."],
        test_paths=test_paths,
        html_paths=html_paths,
        css_paths=css_paths,
        js_test_runner=_js_test_runner(package),
        python_test_runner="pytest" if python else None,
        start_command=start_command,
        build_command=build_command,
        package_scripts=scripts,
        notes=notes,
    )
