#!/usr/bin/env python3
"""Run AQG against disposable real projects spanning supported test adapters."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from aqg.adapters import run_adapter
from aqg.scaffold import initialize_project

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = (
    "npm-jest",
    "pnpm-mocha",
    "yarn-ava",
    "npm-node",
    "python-pytest",
    "python-tox",
)
ALL_CASES = (*DEFAULT_CASES, "bun-node", "browser-static", "typescript-web")
JS_CASES = {
    "npm-jest": ("npm", "jest", "30.4.2"),
    "pnpm-mocha": ("pnpm", "mocha", "11.7.6"),
    "yarn-ava": ("yarn", "ava", "8.0.1"),
    "npm-node": ("npm", "node", None),
    "bun-node": ("bun", "node", None),
}


def _run(
    command: list[str],
    *,
    cwd: Path,
    timeout: int = 900,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(env or {})
    result = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        detail = "\n".join(
            stream
            for stream in (
                f"stdout:\n{result.stdout.strip()}" if result.stdout.strip() else "",
                f"stderr:\n{result.stderr.strip()}" if result.stderr.strip() else "",
            )
            if stream
        )
        raise RuntimeError(f"{' '.join(command)} failed with {result.returncode}: {detail}")
    return result


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _initialize_git(root: Path) -> None:
    _run(["git", "init", "-q"], cwd=root)
    _run(["git", "config", "user.email", "matrix@aqg.invalid"], cwd=root)
    _run(["git", "config", "user.name", "AQG Matrix"], cwd=root)
    _run(["git", "add", "."], cwd=root)
    _run(["git", "commit", "-qm", "fixture baseline"], cwd=root)


def _link(source: Path, destination: Path) -> None:
    if not source.exists():
        raise RuntimeError(f"required shared toolchain is missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.symlink_to(source, target_is_directory=True)


def _link_toolchains(project: Path, *, javascript: bool, python: bool) -> None:
    if javascript:
        _link(
            REPOSITORY_ROOT / "quality" / "tools" / "js" / "node_modules",
            project / "quality" / "tools" / "js" / "node_modules",
        )
    if python:
        _link(REPOSITORY_ROOT / ".aqg" / "venv", project / ".aqg" / "venv")


def _corepack_shim(project: Path, manager: str) -> None:
    if manager not in {"yarn", "pnpm"} and shutil.which(manager):
        return
    if manager not in {"yarn", "pnpm"} or not shutil.which("npm"):
        raise RuntimeError(f"{manager} is required for this matrix case")
    tools = project.parent / ".manager-tools"
    _run(
        [
            "npm",
            "install",
            "--prefix",
            str(tools),
            "--ignore-scripts",
            "--no-audit",
            "--fund=false",
            "corepack@0.34.0",
        ],
        cwd=project,
    )
    corepack = tools / "node_modules" / ".bin" / "corepack"
    discovered_node = Path(shutil.which("node") or "")
    system_node = Path("/usr/bin/node")
    node = (
        system_node
        if ".bun" in discovered_node.as_posix() and system_node.exists()
        else discovered_node
    )
    if not node.exists():
        raise RuntimeError("a real Node.js executable is required for the Yarn matrix case")
    shim = project.parent / ".manager-bin"
    shim.mkdir(exist_ok=True)
    _run([str(node), str(corepack), "install"], cwd=project)
    _run(
        [str(node), str(corepack), "enable", "--install-directory", str(shim), manager],
        cwd=project,
    )
    os.environ["PATH"] = os.pathsep.join((str(shim), str(node.parent), os.environ["PATH"]))


def _javascript_source(runner: str) -> tuple[str, str, str]:
    if runner == "ava":
        source = "export function classify(value) { return value > 0 ? 'positive' : 'other'; }\n"
        test = (
            "import test from 'ava';\n"
            "import { classify } from '../src/classify.mjs';\n"
            "test('covers both classes', t => { t.is(classify(2), 'positive'); "
            "t.is(classify(0), 'other'); });\n"
        )
        return "src/classify.mjs", "test/classify.test.mjs", source + "\0" + test
    source = "exports.classify = value => value > 0 ? 'positive' : 'other';\n"
    if runner == "node":
        test = (
            "const test = require('node:test');\n"
            "const assert = require('node:assert/strict');\n"
            "const { classify } = require('../src/classify.cjs');\n"
            "test('covers both classes', () => { assert.equal(classify(2), 'positive'); "
            "assert.equal(classify(0), 'other'); });\n"
        )
    elif runner == "mocha":
        test = (
            "const assert = require('node:assert/strict');\n"
            "const { classify } = require('../src/classify.cjs');\n"
            "it('covers both classes', () => { assert.equal(classify(2), 'positive'); "
            "assert.equal(classify(0), 'other'); });\n"
        )
    else:
        test = (
            "const assert = require('node:assert/strict');\n"
            "const { classify } = require('../src/classify.cjs');\n"
            "test('covers both classes', () => { assert.equal(classify(2), 'positive'); "
            "assert.equal(classify(0), 'other'); });\n"
        )
    return "src/classify.cjs", "test/classify.test.cjs", source + "\0" + test


def _manager_install(project: Path, manager: str) -> None:
    commands = {
        "npm": ["npm", "install", "--ignore-scripts", "--no-audit", "--fund=false"],
        "pnpm": ["pnpm", "install", "--ignore-scripts"],
        "yarn": ["yarn", "install", "--mode=skip-build"],
        "bun": ["bun", "install", "--ignore-scripts"],
    }
    if manager == "yarn":
        _run(
            commands[manager],
            cwd=project,
            timeout=1200,
            env={
                "YARN_ENABLE_HARDENED_MODE": "false",
                "YARN_ENABLE_IMMUTABLE_INSTALLS": "false",
            },
        )
        _run(
            ["yarn", "install", "--immutable", "--mode=skip-build"],
            cwd=project,
            timeout=1200,
            env={"YARN_ENABLE_HARDENED_MODE": "true"},
        )
    else:
        _run(commands[manager], cwd=project, timeout=1200)


def _prepare_javascript(project: Path, case: str) -> list[str]:
    manager, runner, version = JS_CASES[case]
    source_path, test_path, combined = _javascript_source(runner)
    source, test = combined.split("\0", 1)
    _write(project / source_path, source)
    _write(project / test_path, test)
    package: dict[str, Any] = {
        "name": f"aqg-matrix-{case}",
        "private": True,
        "packageManager": {
            "npm": "npm@10.9.8",
            "pnpm": "pnpm@10.23.0",
            "yarn": "yarn@4.10.3",
            "bun": "bun@1.3.14",
        }[manager],
    }
    if version:
        package["devDependencies"] = {runner: version}
    if manager == "yarn":
        _write(project / ".yarnrc.yml", "nodeLinker: node-modules\n")
    if runner == "node":
        package["scripts"] = {"check": "node --test"}
    _write(project / "package.json", json.dumps(package, indent=2) + "\n")
    _corepack_shim(project, manager)
    _manager_install(project, manager)
    return ["test_integrity", "unit", "structure", "coverage"]


def _prepare_python(project: Path, case: str) -> list[str]:
    _write(project / "src" / "__init__.py", "")
    _write(
        project / "src" / "classifier.py",
        "def classify(value: int) -> str:\n    return 'positive' if value > 0 else 'other'\n",
    )
    _write(
        project / "tests" / "test_classifier.py",
        "from src.classifier import classify\n\n"
        "def test_both_classes() -> None:\n"
        "    assert classify(2) == 'positive'\n"
        "    assert classify(0) == 'other'\n",
    )
    _write(project / "requirements.txt", "pytest==9.1.1\n")
    if case == "python-tox":
        interpreter = REPOSITORY_ROOT / ".aqg" / "venv" / "bin" / "python"
        _write(
            project / "tox.ini",
            "[tox]\nenv_list = py\n\n[testenv]\npackage = skip\n"
            f"allowlist_externals = {interpreter}\n"
            f"commands = {interpreter} -m pytest {{posargs}}\n",
        )
    return ["test_integrity", "unit", "structure", "coverage"]


def _prepare_browser(project: Path) -> list[str]:
    _write(
        project / "index.html",
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<title>AQG matrix</title></head><body><main><h1>Ready</h1></main></body></html>\n",
    )
    _write(project / "styles.css", "body { font-family: sans-serif; }\n")
    return ["acceptance"]


def _write_typescript_web_app(project: Path) -> None:
    _write(
        project / "src" / "counter.ts",
        "export type Counter = { value: number };\n\n"
        "export function increment(counter: Counter, amount: number): Counter {\n"
        "  if (!Number.isSafeInteger(amount) || amount < 1) {\n"
        "    throw new Error('amount must be a positive safe integer');\n"
        "  }\n"
        "  return { value: counter.value + amount };\n"
        "}\n",
    )
    _write(
        project / "src" / "main.ts",
        "import { increment } from './counter';\n\n"
        "type CounterDocument = Pick<Document, 'querySelector'>;\n\n"
        "export function mountCounter(counterDocument: CounterDocument): void {\n"
        "  const value = counterDocument.querySelector<HTMLOutputElement>('#count');\n"
        "  const button = counterDocument.querySelector<HTMLButtonElement>('#increment');\n"
        "  if (!value || !button) throw new Error('counter controls are missing');\n"
        "  button.addEventListener('click', () => {\n"
        "    const next = increment({ value: Number(value.value) }, 1);\n"
        "    value.value = String(next.value);\n"
        "    value.textContent = value.value;\n"
        "  });\n"
        "}\n\n"
        "if (typeof document !== 'undefined') mountCounter(document);\n",
    )
    _write(
        project / "index.html",
        '<!doctype html>\n<html lang="en">\n  <head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1.0" /><title>Counter pilot</title></head>\n'
        '  <body><main><h1>Counter pilot</h1><output id="count" role="status" aria-live="polite" value="0">0</output><button id="increment" type="button" aria-label="Increment count">Increment</button></main><script type="module" src="/src/main.ts"></script></body>\n'
        "</html>\n",
    )
    _write(project / "src" / "styles.css", "button:focus-visible { outline: 3px solid #005fcc; }\n")


def _write_typescript_web_unit_tests(project: Path) -> None:
    _write(
        project / "tests" / "counter.test.ts",
        "import { describe, expect, it } from 'vitest';\n"
        "import fc from 'fast-check';\n"
        "import { increment } from '../src/counter';\n\n"
        "// Feature-Spec: Counter CTP-WEB-001 CTP-WEB-002\n"
        "describe('increment', () => {\n"
        "  it('adds a positive amount without mutating the input', () => {\n"
        "    const current = { value: 2 };\n"
        "    expect(increment(current, 3)).toEqual({ value: 5 });\n"
        "    expect(current).toEqual({ value: 2 });\n"
        "  });\n\n"
        "  it('adds every positive safe integer', () => {\n"
        "    fc.assert(fc.property(fc.integer(), fc.integer({ min: 1, max: 1000 }), (value, amount) =>\n"
        "      increment({ value }, amount).value === value + amount,\n"
        "    ));\n"
        "  });\n\n"
        "  it('rejects an unsafe or non-positive amount', () => {\n"
        "    expect(() => increment({ value: 0 }, 0)).toThrow('positive safe integer');\n"
        "    expect(() => increment({ value: 0 }, Number.MAX_SAFE_INTEGER + 1)).toThrow();\n"
        "  });\n"
        "});\n",
    )
    _write(
        project / "tests" / "main.test.ts",
        "import { describe, expect, it } from 'vitest';\n"
        "import { mountCounter } from '../src/main';\n\n"
        "// Feature-Spec: Counter CTP-WEB-001 CTP-WEB-002\n"
        "describe('counter browser wiring', () => {\n"
        "  it('connects the visible control to the accessible status', () => {\n"
        "    const output = { value: '0', textContent: '0' };\n"
        "    let activate = () => {};\n"
        "    const button = { addEventListener: (_name: string, handler: () => void) => { activate = handler; } };\n"
        "    const counterDocument = { querySelector: (selector: string) => selector === '#count' ? output : button };\n"
        "    mountCounter(counterDocument as unknown as Pick<Document, 'querySelector'>);\n"
        "    activate();\n"
        "    expect(output).toEqual({ value: '1', textContent: '1' });\n"
        "  });\n\n"
        "  it('fails clearly when the public controls are missing', () => {\n"
        "    const missing = { querySelector: () => null };\n"
        "    expect(() => mountCounter(missing as unknown as Pick<Document, 'querySelector'>)).toThrow('controls are missing');\n"
        "  });\n"
        "});\n",
    )


def _write_typescript_web_browser_test(project: Path) -> None:
    _write(
        project / "e2e" / "counter.spec.mjs",
        "import { createRequire } from 'node:module';\n\n"
        "const requireFromAqg = createRequire(new URL('../quality/tools/js/package.json', import.meta.url));\n"
        "const { expect, test } = requireFromAqg('@playwright/test');\n"
        "const AxeBuilder = requireFromAqg('@axe-core/playwright').default;\n\n"
        "// Feature-Spec: Counter CTP-WEB-001 CTP-WEB-002\n"
        "test('increments with keyboard-accessible controls and has no serious axe findings', async ({ page }) => {\n"
        "  await page.goto('/');\n"
        "  await page.getByRole('button', { name: 'Increment count' }).press('Enter');\n"
        "  await expect(page.getByRole('status')).toHaveText('1');\n"
        "  const results = await new AxeBuilder({ page }).analyze();\n"
        "  expect(results.violations.filter(({ impact }) => impact === 'serious' || impact === 'critical')).toEqual([]);\n"
        "});\n",
    )


def _write_typescript_web_contract(project: Path) -> None:
    _write(
        project / "tsconfig.json",
        json.dumps(
            {
                "compilerOptions": {
                    "strict": True,
                    "noUncheckedIndexedAccess": True,
                    "exactOptionalPropertyTypes": True,
                    "useUnknownInCatchVariables": True,
                    "noImplicitOverride": True,
                    "target": "ES2022",
                    "module": "ESNext",
                    "moduleResolution": "bundler",
                    "noEmit": True,
                },
                "include": ["src", "tests", "e2e"],
            },
            indent=2,
        )
        + "\n",
    )
    _write(
        project / "feature-spec" / "Counter.md",
        "# Counter\n\n"
        "- `CTP-WEB-001` The counter MUST increment by one through its visible control.\n"
        "- `CTP-WEB-002` The counter MUST expose its updated value through an accessible status.\n",
    )
    _write(
        project / "features" / "counter.feature",
        "Feature: Counter\n\n"
        "  Scenario: Increment the visible count\n"
        "    Given a counter showing 0\n"
        "    When the increment control is activated\n"
        "    Then the counter shows 1\n",
    )
    _write(
        project / "qa" / "procedures" / "QA-COUNTER.md",
        "# QA-COUNTER · keyboard and zoom check\n\n"
        "Requirements: CTP-WEB-001, CTP-WEB-002\n\n"
        "1. At 200% zoom, use Tab then Enter to activate **Increment**.\n"
        "2. Verify focus remains visible and the status changes from 0 to 1.\n"
        "3. Record browser, OS, revision, result, and any rollback required.\n",
    )


def _typescript_web_package() -> dict[str, Any]:
    return {
        "name": "aqg-typescript-web-pilot",
        "private": True,
        "type": "module",
        "packageManager": "npm@10.9.8",
        "scripts": {"dev": "vite --host 127.0.0.1", "build": "tsc -p tsconfig.json && vite build"},
        "devDependencies": {
            "fast-check": "4.9.0",
            "typescript": "6.0.3",
            "vite": "7.1.7",
            "vitest": "4.1.10",
        },
    }


def _prepare_typescript_web(project: Path) -> list[str]:
    """Write a small, real web application used by the opt-in connected pilot."""
    _write_typescript_web_app(project)
    _write_typescript_web_unit_tests(project)
    _write_typescript_web_browser_test(project)
    _write_typescript_web_contract(project)
    _write(project / "package.json", json.dumps(_typescript_web_package(), indent=2) + "\n")
    return ["test_integrity", "unit", "structure", "coverage", "acceptance"]


def _browser_setup_options() -> dict[str, str]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
    return {
        "base_url": f"http://127.0.0.1:{port}",
        "start_command": (f"{sys.executable} -m http.server {port} --bind 127.0.0.1 --directory ."),
    }


def _typescript_setup_options() -> dict[str, str]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])
    return {
        "base_url": f"http://127.0.0.1:{port}",
        "start_command": (f"npm run dev -- --host 127.0.0.1 --port {port} --strictPort"),
    }


def _execute_case(case: str, workspace: Path) -> dict[str, Any]:
    project = workspace / case
    project.mkdir()
    if case in JS_CASES:
        gates = _prepare_javascript(project, case)
        javascript, python = True, False
    elif case.startswith("python-"):
        gates = _prepare_python(project, case)
        javascript, python = False, True
    elif case == "typescript-web":
        gates = _prepare_typescript_web(project)
        _manager_install(project, "npm")
        javascript, python = True, False
    else:
        gates = _prepare_browser(project)
        javascript, python = True, False
    _initialize_git(project)
    setup_options = (
        _browser_setup_options()
        if case == "browser-static"
        else _typescript_setup_options()
        if case == "typescript-web"
        else {}
    )
    initialize_project(
        project,
        owner="@aqg-matrix",
        install=False,
        ci=False,
        mode="greenfield",
        base_url=setup_options.get("base_url"),
        start_command=setup_options.get("start_command"),
    )
    _link_toolchains(project, javascript=javascript, python=python)
    results = []
    started = time.monotonic()
    for gate in gates:
        code, report = run_adapter(project, gate)
        results.append({"gate": gate, "exit_code": code, "status": report["status"]})
        if code:
            raise RuntimeError(f"{case} gate {gate} returned {code}: {report}")
    return {
        "case": case,
        "duration_seconds": round(time.monotonic() - started, 3),
        "gates": results,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", choices=ALL_CASES, dest="cases")
    parser.add_argument("--output", type=Path, help="write the normalized JSON report here")
    parser.add_argument("--keep-workspace", action="store_true")
    parser.add_argument("--list", action="store_true", help="list case names and exit")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.list:
        print("\n".join(ALL_CASES))
        return 0
    cases = args.cases or list(DEFAULT_CASES)
    workspace = Path(tempfile.mkdtemp(prefix="aqg-project-matrix-"))
    report: dict[str, Any] = {"schema_version": 1, "cases": [], "failures": []}
    try:
        for case in cases:
            try:
                result = _execute_case(case, workspace)
                report["cases"].append(result)
                print(f"PASS {case} ({result['duration_seconds']:.1f}s)")
            except Exception as exc:
                report["failures"].append({"case": case, "error": str(exc)})
                print(f"FAIL {case}: {exc}", file=sys.stderr)
    finally:
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        if args.keep_workspace:
            print(f"workspace: {workspace}")
        else:
            shutil.rmtree(workspace)
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
