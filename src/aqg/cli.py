"""Command-line control surface for Agent Quality Gauntlet."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Never

from .acceptance import run_acceptance_mutation
from .adapters import HANDLERS, run_adapter
from .approvals import KINDS, validate_approval, validate_required_approvals, write_template
from .authoring import create_feature_spec, create_gherkin_feature, create_qa_procedure
from .checks import lint_features, scan_test_integrity, write_test_integrity_baseline
from .conformance import run_conformance
from .constants import CONFIGURATION_ERROR, INFRASTRUCTURE_ERROR, PASS, QUALITY_FAILURE, __version__
from .dashboard import serve_dashboard
from .detect import detect_project
from .doctor import diagnose
from .errors import AQGError, ConfigurationError, InfrastructureError, QualityFailure
from .golden import run_goldens
from .guidance import guides, read_guide, search_guides
from .hooks import hook_pretool, hook_stop
from .policy import load_policy, policy_override_enabled, risk_summary
from .portfolio import add_project, load_portfolio, project_roots, remove_project, scan_portfolio
from .project import load_project
from .reporting import latest_evidence_bundle, write_github_summary, write_review_sarif
from .review import analyze_review, review_exit_code, write_review_packet
from .runner import list_runs, run_gate, run_profile
from .scaffold import (
    build_project_config,
    current_onboarding,
    initialize_project,
    install_toolchains,
    refresh_onboarding,
    upgrade_runtime,
)
from .tui import run_tui
from .util import (
    find_project_root,
    git_changed_files,
    human_duration,
    utc_now,
    write_json,
)
from .wizard import run_wizard


class ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        self.print_usage(sys.stderr)
        raise ConfigurationError(message)


def _json_dump(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _root(value: str | None, *, require_initialized: bool = True) -> Path:
    if value:
        root = Path(value).expanduser().resolve()
        if require_initialized and not (root / "quality" / "policy.toml").exists():
            raise ConfigurationError(f"{root} is not initialized; run `qg setup {root}`")
        return root
    if require_initialized:
        return find_project_root()
    return Path.cwd().resolve()


def _comparison_base(root: Path, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    override = os.environ.get("AQG_DIFF_BASE")
    if override:
        return override
    return str(load_project(root).get("enforcement", {}).get("base_ref", "HEAD"))


def _print_doctor(report: dict[str, Any]) -> None:
    print(f"AQG doctor · {report['status']} · {report['root']}")
    for item in report["diagnostics"]:
        symbol = {"pass": "✓", "warning": "!", "error": "✗"}.get(item["status"], "·")
        print(f"  {symbol} {item['message']}")
        if item.get("remediation") and item["status"] != "pass":
            print(f"      {item['remediation']}")
    counts = report["counts"]
    print(f"{counts['pass']} passed · {counts['warning']} warning(s) · {counts['error']} error(s)")


def _print_status(root: Path, payload: dict[str, Any]) -> None:
    project = payload["project"]
    latest = payload.get("latest")
    print(f"AQG {project['name']} · {root}")
    stacks = (
        ", ".join(name for name, enabled in project.get("stacks", {}).items() if enabled) or "none"
    )
    print(f"Stacks: {stacks}")
    print(
        f"Risk: {payload['risk']['selected_risk_profile']} → {', '.join(payload['risk']['required_execution_profiles'])}"
    )
    if latest:
        print(
            f"Latest: {latest['status']} · {latest['profile']} · {human_duration(latest['duration_ms'])} · {latest['run_id']}"
        )
        for gate in latest.get("gates", []):
            symbol = "✓" if gate["status"] == "pass" else "✗"
            print(
                f"  {symbol} {gate['name']:<24} {gate['status']:<22} {human_duration(gate['duration_ms'])}"
            )
    else:
        print("Latest: no evidence run")


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="qg", description="Constraint-first quality control for agentic coding"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--root", help="repository root; auto-detected for initialized projects")
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON where supported"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    wizard = sub.add_parser("wizard", help="guided one-command setup for non-specialists")
    wizard.add_argument("path", nargs="?", default=".")

    setup = sub.add_parser("setup", help="one-command initialize, install, diagnose, and verify")
    setup.add_argument("path", nargs="?", default=".")
    setup.add_argument("--owner")
    setup.add_argument("--mode", choices=("auto", "adopt", "greenfield"), default="auto")
    setup.add_argument("--base-url")
    setup.add_argument("--start-command")
    setup.add_argument("--no-install", action="store_true")
    setup.add_argument(
        "--browsers",
        action="store_true",
        help="install Playwright Chromium when browser gates apply",
    )
    setup.add_argument("--no-ci", action="store_true")
    setup.add_argument("--no-verify", action="store_true")
    setup.add_argument("--register", action="store_true")
    setup.add_argument("--force", action="store_true")

    init = sub.add_parser(
        "init", help="initialize repository files without necessarily installing tools"
    )
    init.add_argument("path", nargs="?", default=".")
    init.add_argument("--owner")
    init.add_argument("--mode", choices=("auto", "adopt", "greenfield"), default="auto")
    init.add_argument("--base-url")
    init.add_argument("--start-command")
    init.add_argument("--install", action="store_true")
    init.add_argument(
        "--browsers", action="store_true", help="install Playwright Chromium when --install is used"
    )
    init.add_argument("--no-ci", action="store_true")
    init.add_argument("--force", action="store_true")

    detect = sub.add_parser("detect", help="inspect repository stacks and inferred commands")
    detect.add_argument(
        "--write",
        action="store_true",
        help="rewrite quality/project.json; policy-maintenance task only",
    )
    detect.add_argument("--base-url")
    detect.add_argument("--start-command")

    sub.add_parser("status", help="show risk, latest evidence, and gate status")
    doctor = sub.add_parser(
        "doctor", help="validate configuration, toolchains, locks, and governance"
    )
    doctor.add_argument("--strict-tools", action="store_true")

    tools = sub.add_parser("tools", help="manage isolated project quality toolchains")
    tools_sub = tools.add_subparsers(dest="tools_command", required=True)
    install = tools_sub.add_parser("install")
    install.add_argument("--ci", action="store_true")
    install.add_argument(
        "--browsers",
        action="store_true",
        help="install Playwright Chromium when browser gates apply",
    )
    tools_sub.add_parser("status")

    check = sub.add_parser("check", help="run an execution profile")
    check.add_argument("profile", choices=("fast", "pr", "deep", "release"))
    check.add_argument("--keep-going", action="store_true")
    check.add_argument("--quiet", action="store_true")

    gate = sub.add_parser("gate", help="run one policy gate with normalized evidence")
    gate.add_argument("name")

    adapter = sub.add_parser("adapter", help=argparse.SUPPRESS)
    adapter.add_argument("name", choices=sorted(HANDLERS))

    check_risk = sub.add_parser(
        "check-risk", help="resolve the risk card and run every required profile"
    )
    check_risk.add_argument("--card", default="quality/change-risk.json")
    check_risk.add_argument("--keep-going", action="store_true")
    check_risk.add_argument("--quiet", action="store_true")

    risk = sub.add_parser("risk-card", help="validate and resolve the change-risk card")
    risk.add_argument("--card", default="quality/change-risk.json")

    review = sub.add_parser(
        "review", help="classify the current diff and generate review artifacts"
    )
    review.add_argument(
        "--base", help="comparison ref; defaults to quality/project.json or AQG_DIFF_BASE"
    )
    review.add_argument("--write", action="store_true")
    review.add_argument("--no-evidence", action="store_true")
    review.add_argument("--sarif", action="store_true")
    review.add_argument("--github-summary", nargs="?", const="")

    changed = sub.add_parser("changed-files", help="print files in the current review scope")
    changed.add_argument(
        "--base", help="comparison ref; defaults to quality/project.json or AQG_DIFF_BASE"
    )

    guidance = sub.add_parser(
        "guidance", help="read or search the embedded agent test-writing playbooks"
    )
    guidance.add_argument("topic", nargs="?")
    guidance.add_argument("--list", action="store_true")
    guidance.add_argument("--search")

    onboarding = sub.add_parser(
        "onboarding", help="show, refresh, or advance the generated setup control flow"
    )
    onboarding_sub = onboarding.add_subparsers(dest="onboarding_command", required=True)
    onboarding_sub.add_parser("show")
    onboarding_sub.add_parser("refresh")
    onboarding_sub.add_parser("next")

    golden = sub.add_parser("golden", help="run or explicitly update deterministic golden sessions")
    golden.add_argument("--update", action="store_true")
    golden.add_argument("--scenario")

    acceptance = sub.add_parser("acceptance", help="lint Gherkin or run acceptance mutation")
    acceptance_sub = acceptance.add_subparsers(dest="acceptance_command", required=True)
    acceptance_sub.add_parser("lint")
    acceptance_sub.add_parser("mutate")

    baseline = sub.add_parser("baseline", help="create a narrow, reviewable legacy-debt baseline")
    baseline_sub = baseline.add_subparsers(dest="baseline_command", required=True)
    baseline_test = baseline_sub.add_parser("test-integrity")
    baseline_test.add_argument(
        "--confirm", action="store_true", help="required to write the baseline"
    )

    approval = sub.add_parser(
        "approval", help="create templates or validate human approval records"
    )
    approval_sub = approval.add_subparsers(dest="approval_command", required=True)
    approval_template = approval_sub.add_parser("template")
    approval_template.add_argument("kind", choices=sorted(KINDS))
    approval_template.add_argument("--reviewer")
    approval_template.add_argument("--force", action="store_true")
    approval_validate = approval_sub.add_parser("validate")
    approval_validate.add_argument("kind", nargs="?", choices=sorted(KINDS))
    approval_validate.add_argument(
        "--risk-profile", choices=("experiment", "standard", "high_assurance", "critical")
    )

    new = sub.add_parser("new", help="create behavior and QA authoring templates")
    new_sub = new.add_subparsers(dest="new_command", required=True)
    spec = new_sub.add_parser("spec")
    spec.add_argument("name")
    spec.add_argument("--todo", action="store_true")
    spec.add_argument("--force", action="store_true")
    gherkin = new_sub.add_parser("feature")
    gherkin.add_argument("name")
    gherkin.add_argument("--force", action="store_true")
    qa = new_sub.add_parser("qa")
    qa.add_argument("name")
    qa.add_argument("--force", action="store_true")

    conf = sub.add_parser(
        "conformance", help="prove AQG and optionally installed tools fail on known defects"
    )
    conf.add_argument("--tools", action="store_true")

    report = sub.add_parser("report", help="emit the latest evidence bundle")
    report.add_argument("--output")

    dash = sub.add_parser("dashboard", help="serve the local web control surface")
    dash.add_argument("--host", default="127.0.0.1")
    dash.add_argument("--port", type=int, default=8765)
    dash.add_argument("--open", action="store_true")
    dash.add_argument("--allow-actions", action="store_true")
    dash.add_argument("--portfolio", action="store_true")
    dash.add_argument("--verbose", action="store_true")

    sub.add_parser("tui", help="open the terminal control surface")

    portfolio = sub.add_parser("portfolio", help="register and aggregate multiple repositories")
    portfolio_sub = portfolio.add_subparsers(dest="portfolio_command", required=True)
    port_add = portfolio_sub.add_parser("add")
    port_add.add_argument("path", nargs="?", default=".")
    port_add.add_argument("--name")
    port_add.add_argument("--tag", action="append", default=[])
    port_remove = portfolio_sub.add_parser("remove")
    port_remove.add_argument("value")
    portfolio_sub.add_parser("list")
    portfolio_sub.add_parser("scan")

    upgrade = sub.add_parser("upgrade", help="replace the vendored runtime and managed templates")
    upgrade.add_argument("--install", action="store_true")

    hook_pre = sub.add_parser("hook-pretool", help=argparse.SUPPRESS)
    hook_pre.set_defaults(hidden=True)
    hook_stop_parser = sub.add_parser("hook-stop", help=argparse.SUPPRESS)
    hook_stop_parser.set_defaults(hidden=True)

    return parser


def _initialize(args: argparse.Namespace, *, setup: bool) -> int:
    root = Path(args.path).expanduser().resolve()
    result = initialize_project(
        root,
        owner=args.owner,
        force=args.force,
        install=(not args.no_install) if setup else args.install,
        ci=not args.no_ci,
        base_url=args.base_url,
        start_command=args.start_command,
        mode=args.mode,
        browsers=args.browsers,
    )
    verification: dict[str, Any] = {}
    if setup and not args.no_verify:
        verification["doctor"] = diagnose(root, strict_tools=not args.no_install)
        code, conformance = run_conformance(root, tools=not args.no_install)
        verification["conformance"] = conformance
    if setup and args.register:
        verification["portfolio"] = add_project(root)
    payload = {**result, "verification": verification}
    if args.json:
        _json_dump(payload)
    else:
        stacks = (
            ", ".join(name for name, enabled in result["project"]["stacks"].items() if enabled)
            or "none"
        )
        print(f"AQG initialized {root}")
        print(f"Detected stacks: {stacks}")
        print(
            "Toolchains installed."
            if result["installed"]
            else "Toolchains not installed; run `qg tools install`."
        )
        if verification.get("doctor"):
            _print_doctor(verification["doctor"])
        if verification.get("conformance"):
            summary = verification["conformance"]["internal"]["summary"]
            print(
                f"Conformance: {verification['conformance']['status']} · {summary['passed']}/{summary['total']} internal cases passed"
            )
        print(
            "Next: review QUALITY.md and quality/onboarding.json, then have an agent implement the project-specific behavior contracts and tests."
        )
    if setup and verification.get("doctor", {}).get("counts", {}).get("error", 0):
        return CONFIGURATION_ERROR
    if setup and verification.get("conformance", {}).get("status") == "fail":
        return QUALITY_FAILURE
    return PASS


def _status_payload(root: Path) -> dict[str, Any]:
    policy = load_policy(root)
    errors, risk = risk_summary(root, policy, "quality/change-risk.json")
    runs = list_runs(root, 20)
    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        "project": load_project(root),
        "risk": risk,
        "risk_errors": errors,
        "latest": runs[0] if runs else None,
        "runs": runs,
    }


def _check_risk(args: argparse.Namespace, root: Path) -> int:
    policy = load_policy(root)
    errors, risk = risk_summary(root, policy, args.card)
    if errors:
        if args.json:
            _json_dump(risk)
        else:
            for error in errors:
                print(error, file=sys.stderr)
        return CONFIGURATION_ERROR
    final = PASS
    summaries: list[dict[str, Any]] = []
    for profile in risk["required_execution_profiles"]:
        code, summary = run_profile(
            root, policy, str(profile), keep_going=args.keep_going, quiet=args.quiet or args.json
        )
        summaries.append(summary)
        final = max(final, code)
        if code != PASS and not args.keep_going:
            break
    payload = {"risk": risk, "runs": summaries, "exit_code": final}
    if args.json:
        _json_dump(payload)
    return final


def dispatch(args: argparse.Namespace) -> int:
    command = args.command
    payload: Any
    path: Any
    if command == "wizard":
        code, payload = run_wizard(Path(args.path))
        if args.json:
            _json_dump(payload)
        return code
    if command == "setup":
        return _initialize(args, setup=True)
    if command == "init":
        return _initialize(args, setup=False)

    root = _root(args.root)

    if command == "detect":
        detection = detect_project(root)
        payload = detection.as_dict()
        if args.write:
            policy = load_policy(root)
            if not policy_override_enabled(policy):
                raise ConfigurationError(
                    "detect --write requires AQG_POLICY_MAINTENANCE=1 and an explicit policy-maintenance review"
                )
            project = build_project_config(
                root, detection, base_url=args.base_url, start_command=args.start_command
            )
            write_json(root / "quality" / "project.json", project)
            payload = {"detection": payload, "project": project, "written": True}
        _json_dump(payload) if args.json else print(json.dumps(payload, indent=2))
        return PASS

    if command == "status":
        payload = _status_payload(root)
        _json_dump(payload) if args.json else _print_status(root, payload)
        return CONFIGURATION_ERROR if payload["risk_errors"] else PASS

    if command == "doctor":
        report = diagnose(root, strict_tools=args.strict_tools)
        _json_dump(report) if args.json else _print_doctor(report)
        return CONFIGURATION_ERROR if report["counts"]["error"] else PASS

    if command == "tools":
        if args.tools_command == "install":
            result = install_toolchains(root, ci=args.ci, browsers=args.browsers)
            _json_dump(result) if args.json else print(
                "\n".join(f"{key}: {value}" for key, value in result.items())
                or "No toolchains were applicable."
            )
            return PASS
        report = diagnose(root, strict_tools=False)
        filtered = [
            item
            for item in report["diagnostics"]
            if "tool" in item["code"] or item["code"].startswith(("node", "python-version"))
        ]
        payload = {"status": report["status"], "diagnostics": filtered}
        _json_dump(payload) if args.json else [
            print(f"{item['status']}: {item['message']}") for item in filtered
        ]
        return PASS

    if command == "check":
        code, summary = run_profile(
            root,
            load_policy(root),
            args.profile,
            keep_going=args.keep_going,
            quiet=args.quiet or args.json,
        )
        if args.json:
            _json_dump(summary)
        return code

    if command == "gate":
        policy = load_policy(root)
        run_id = (
            os.environ.get("AQG_RUN_ID")
            or f"manual-{utc_now().replace(':', '').replace('+00:00', 'Z')}"
        )
        code, evidence = run_gate(root, policy, args.name, run_id)
        if args.json:
            _json_dump(evidence)
        else:
            print(f"{args.name}: {evidence['status']}")
            if evidence.get("stdout"):
                print(evidence["stdout"], end="" if evidence["stdout"].endswith("\n") else "\n")
            if evidence.get("stderr"):
                print(evidence["stderr"], file=sys.stderr)
        return code

    if command == "adapter":
        code, report = run_adapter(root, args.name)
        if args.json:
            _json_dump(report)
        return code

    if command == "check-risk":
        return _check_risk(args, root)

    if command == "risk-card":
        errors, payload = risk_summary(root, load_policy(root), args.card)
        _json_dump(payload) if args.json else print(
            f"Selected: {payload['selected_risk_profile']}\nMinimum: {payload['minimum_risk_profile']}\nRequired execution: {', '.join(payload['required_execution_profiles'])}\n"
            + ("Errors:\n- " + "\n- ".join(errors) if errors else "Risk card is valid.")
        )
        return CONFIGURATION_ERROR if errors else PASS

    if command == "review":
        packet = analyze_review(
            root,
            load_policy(root),
            base=_comparison_base(root, args.base),
            require_evidence=not args.no_evidence,
        )
        artifacts: dict[str, str] = {}
        if args.write:
            artifacts.update(write_review_packet(root, packet))
        if args.sarif:
            artifacts["sarif"] = str(write_review_sarif(root, packet))
        if args.github_summary is not None:
            destination = Path(args.github_summary).expanduser() if args.github_summary else None
            artifacts["github_summary"] = str(write_github_summary(root, packet, destination))
        if args.json:
            _json_dump({"packet": packet, "artifacts": artifacts})
        else:
            summary = packet["summary"]
            print(
                f"Review: {summary['blockers']} blocker(s), {summary['human_review']} human review prompt(s), {summary['changed']} changed file(s)"
            )
            for finding in packet["findings"]:
                print(f"  {finding['severity'].upper():8} {finding['title']}")
            for kind, path in artifacts.items():
                print(f"{kind}: {path}")
        return review_exit_code(packet)

    if command == "changed-files":
        base = _comparison_base(root, args.base)
        files = git_changed_files(root, base)
        _json_dump({"base": base, "files": files}) if args.json else print("\n".join(files))
        return PASS

    if command == "guidance":
        if args.search:
            payload = search_guides(args.search)
            _json_dump(payload) if args.json else [
                print(f"{item['topic']}: {item['title']}\n  " + "\n  ".join(item["snippets"]))
                for item in payload
            ]
        elif args.list or not args.topic:
            payload = guides()
            _json_dump(payload) if args.json else [
                print(
                    f"{item['topic']:<32} {item['title']}"
                    + (f" — {item['summary']}" if item["summary"] else "")
                )
                for item in payload
            ]
        else:
            content = read_guide(args.topic)
            _json_dump({"topic": args.topic, "content": content}) if args.json else print(content)
        return PASS

    if command == "onboarding":
        if args.onboarding_command == "refresh":
            payload = refresh_onboarding(root)
            wrapped = {"stored": payload, "current": payload, "stale": False}
        else:
            wrapped = current_onboarding(root)
            payload = wrapped["current"]
        if args.json:
            _json_dump(wrapped if args.onboarding_command != "refresh" else payload)
        elif args.onboarding_command == "next":
            action = payload["next_action"]
            print(f"{action['severity'].upper()}: {action['message']}")
            print(action["next_step"])
            if wrapped.get("stale"):
                print(
                    "Stored onboarding state is stale; run `python3 quality/qg.py onboarding refresh`."
                )
        else:
            summary = payload["summary"]
            print(
                f"Onboarding: {summary['blockers']} blocker(s), {summary['review']} review item(s), {summary['info']} informational item(s)"
            )
            print(
                f"State: {'stale' if wrapped.get('stale') else 'current'} · guarded use: {'ready' if summary['ready_for_guarded_use'] else 'blocked'}"
            )
            for stage in payload["stages"]:
                symbol = (
                    "✓"
                    if stage["status"] == "complete"
                    else "!"
                    if stage["status"] == "needs_review"
                    else "×"
                    if stage["status"] == "blocked"
                    else "·"
                )
                print(f"  {symbol} {stage['title']:<34} {stage['status']}")
            action = payload["next_action"]
            print(f"Next: {action['next_step']}")
        return CONFIGURATION_ERROR if payload["summary"]["blockers"] else PASS

    if command == "golden":
        code, report = run_goldens(root, update=args.update, scenario_name=args.scenario)
        _json_dump(report) if args.json else print(
            f"Golden sessions: {report.get('status', 'unknown')} · {report.get('summary', report)}"
        )
        return code

    if command == "acceptance":
        if args.acceptance_command == "lint":
            report = lint_features(root)
            _json_dump(report) if args.json else print(
                f"Features: {report['feature_files']} · errors: {report['errors']} · warnings: {report['warnings']}"
            )
            return QUALITY_FAILURE if report["errors"] else PASS
        code, report = run_acceptance_mutation(root)
        _json_dump(report) if args.json else print(
            f"Acceptance mutation: {report.get('status', 'unknown')} · {report.get('summary', {})}"
        )
        return code

    if command == "baseline" and args.baseline_command == "test-integrity":
        report = scan_test_integrity(root, load_project(root))
        if not args.confirm:
            _json_dump(report) if args.json else print(json.dumps(report, indent=2))
            print(
                "Refusing to write a baseline without --confirm; review every warning first.",
                file=sys.stderr,
            )
            return CONFIGURATION_ERROR
        policy = load_policy(root)
        if not policy_override_enabled(policy):
            raise ConfigurationError("writing a baseline requires AQG_POLICY_MAINTENANCE=1")
        path = write_test_integrity_baseline(root, report)
        _json_dump({"path": str(path), "report": report}) if args.json else print(path)
        return PASS

    if command == "approval":
        if args.approval_command == "template":
            path = write_template(root, args.kind, reviewer=args.reviewer, force=args.force)
            _json_dump({"path": str(path)}) if args.json else print(
                f"Created {path}. Complete it as a human review record and commit it through CODEOWNERS review."
            )
            return PASS
        if args.risk_profile:
            report = validate_required_approvals(root, args.risk_profile)
        elif args.kind:
            errors = validate_approval(root, args.kind)
            report = {
                "kind": args.kind,
                "errors": errors,
                "exit_code": QUALITY_FAILURE if errors else PASS,
            }
        else:
            raise ConfigurationError("approval validate requires a kind or --risk-profile")
        _json_dump(report) if args.json else print(
            "Valid." if not report["errors"] else "\n".join(report["errors"])
        )
        return int(report["exit_code"])

    if command == "new":
        if args.new_command == "spec":
            path = create_feature_spec(root, args.name, todo=args.todo, force=args.force)
        elif args.new_command == "feature":
            path = create_gherkin_feature(root, args.name, force=args.force)
        else:
            path = create_qa_procedure(root, args.name, force=args.force)
        _json_dump({"path": str(path)}) if args.json else print(path)
        return PASS

    if command == "conformance":
        code, report = run_conformance(root, tools=args.tools)
        if args.json:
            _json_dump(report)
        else:
            for suite_name in ("internal", "tools"):
                if suite_name in report:
                    summary = report[suite_name]["summary"]
                    print(
                        f"{suite_name}: {report[suite_name]['status']} · {summary['passed']}/{summary['total']} passed"
                        + (
                            f" · {summary.get('skipped', 0)} skipped"
                            if summary.get("skipped")
                            else ""
                        )
                    )
                    for case in report[suite_name]["cases"]:
                        print(f"  {case['status']:<5} {case['name']}")
        return code

    if command == "report":
        payload = latest_evidence_bundle(root)
        if args.output:
            path = Path(args.output).expanduser()
            write_json(path, payload)
            print(path)
        else:
            _json_dump(payload)
        return PASS

    if command == "dashboard":
        roots = project_roots() if args.portfolio else [root]
        if not roots:
            raise ConfigurationError("no registered projects; use `qg portfolio add <path>`")
        serve_dashboard(
            roots,
            host=args.host,
            port=args.port,
            open_browser=args.open,
            allow_actions=args.allow_actions,
            verbose=args.verbose,
        )
        return PASS

    if command == "tui":
        run_tui(root)
        return PASS

    if command == "portfolio":
        if args.portfolio_command == "add":
            payload = add_project(Path(args.path), name=args.name, tags=args.tag)
        elif args.portfolio_command == "remove":
            payload = {"removed": remove_project(args.value), "value": args.value}
        elif args.portfolio_command == "list":
            payload = load_portfolio()
        else:
            payload = scan_portfolio()
        _json_dump(payload) if args.json else print(json.dumps(payload, indent=2))
        return PASS

    if command == "upgrade":
        policy = load_policy(root)
        if not policy_override_enabled(policy):
            raise ConfigurationError(
                "upgrade rewrites protected runtime files and requires AQG_POLICY_MAINTENANCE=1"
            )
        upgrade_runtime(root)
        result = install_toolchains(root) if args.install else {}
        payload = {"upgraded": True, "version": __version__, "tools": result}
        _json_dump(payload) if args.json else print(
            f"Upgraded vendored runtime to AQG {__version__}."
        )
        return PASS

    if command == "hook-pretool":
        return hook_pretool(root)
    if command == "hook-stop":
        return hook_stop(root)

    raise ConfigurationError(f"unknown command {command!r}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw = list(sys.argv[1:] if argv is None else argv)
    # Accept global control flags before or after the subcommand for shell ergonomics.
    if "--json" in raw:
        raw = [item for item in raw if item != "--json"]
        raw.insert(0, "--json")
    if "--root" in raw:
        index = raw.index("--root")
        if index + 1 >= len(raw):
            raise ConfigurationError("--root requires a path")
        value = raw[index + 1]
        del raw[index : index + 2]
        raw[0:0] = ["--root", value]
    try:
        args = parser.parse_args(raw)
        return int(dispatch(args))
    except QualityFailure as exc:
        print(f"quality failure: {exc}", file=sys.stderr)
        return QUALITY_FAILURE
    except (ConfigurationError, ValueError) as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return CONFIGURATION_ERROR
    except InfrastructureError as exc:
        print(f"infrastructure error: {exc}", file=sys.stderr)
        return INFRASTRUCTURE_ERROR
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return INFRASTRUCTURE_ERROR
    except AQGError as exc:
        print(str(exc), file=sys.stderr)
        return INFRASTRUCTURE_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
