"""Command-line control surface for Agent Quality Gauntlet."""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shlex
import sys
from collections.abc import Callable
from contextvars import ContextVar
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

ACTIVE_ARGV: ContextVar[tuple[str, ...]] = ContextVar("aqg_active_argv", default=())

CONVENTIONAL_COMMANDS: dict[str, tuple[str, ...]] = {
    "docs": ("robot-docs", "guide"),
    "health": ("doctor",),
    "inspect": ("status",),
    "scan": ("review", "--no-evidence"),
    "test": ("check", "fast"),
    "verify": ("check-risk", "--keep-going"),
}

GLOBAL_FLAGS = ("--help", "--json", "--root", "--version", "-h")

ROBOT_GUIDE: dict[str, Any] = {
    "schema_version": 1,
    "guide_version": "1.0",
    "purpose": "Operate AQG safely from setup through reviewed release.",
    "workflows": {
        "discover": ["qg capabilities --json", "qg robot-docs guide --json"],
        "setup": [
            "qg setup . --owner @your-org/quality --mode auto",
            "qg doctor",
            "qg onboarding next",
        ],
        "daily": ["qg status", "qg check fast", "qg review"],
        "pull_request": [
            "qg risk-card",
            "qg check pr --keep-going",
            "qg review --write --sarif",
        ],
        "high_assurance": [
            "qg check-risk --keep-going",
            "qg approval validate --risk-profile high_assurance",
        ],
    },
    "safety_rules": [
        "Do not weaken policy, thresholds, tests, or evidence to obtain a pass.",
        "Treat missing, stale, timed-out, and crashed evidence as failure.",
        "Do not approve your own policy, golden, waiver, or High-assurance review.",
        "Use AQG_POLICY_MAINTENANCE=1 only for an explicitly reviewed policy task.",
    ],
    "exit_codes": {
        "0": "pass",
        "1": "quality defect",
        "2": "configuration or input error",
        "3": "infrastructure or evidence failure",
    },
}


def _invalid_token(message: str) -> str | None:
    for expression in (
        r"invalid choice: '([^']+)'",
        r"unrecognized arguments?:\s+(\S+)",
    ):
        match = re.search(expression, message)
        if match:
            return match.group(1)
    return None


def _candidate_tokens(parser: argparse.ArgumentParser, token: str) -> list[str]:
    if token.startswith("-"):
        options = {option for action in parser._actions for option in action.option_strings}
        return sorted(options | set(GLOBAL_FLAGS))
    return sorted(_subparser_choices(parser))


def _flag_catalog(
    parser: argparse.ArgumentParser, path: tuple[str, ...] = ()
) -> list[tuple[str, tuple[str, ...], argparse.Action]]:
    entries = [
        (option, path, action) for action in parser._actions for option in action.option_strings
    ]
    for name, child in _subparser_choices(parser).items():
        entries.extend(_flag_catalog(child, (*path, name)))
    return entries


def _flag_value(action: argparse.Action) -> list[str]:
    if action.nargs == 0 or action.nargs == "?":
        return []
    if action.choices:
        return [str(next(iter(action.choices)))]
    return [str(action.metavar or action.dest).upper()]


def _flag_correction(parser: argparse.ArgumentParser, token: str) -> str | None:
    catalog = _flag_catalog(parser)
    matches = difflib.get_close_matches(
        token, sorted({option for option, _, _ in catalog}), n=1, cutoff=0.55
    )
    if not matches:
        return None
    flag = matches[0]
    if flag in {"--help", "-h"}:
        return "qg --help"
    if flag == "--version":
        return "qg --version"
    if flag == "--json":
        return "qg capabilities --json"
    if flag == "--root":
        return "qg --root PATH status"
    owners = sorted(
        ((path, action) for option, path, action in catalog if option == flag),
        key=lambda item: (len(item[0]), item[0]),
    )
    path, action = owners[0]
    return shlex.join(["qg", *path, flag, *_flag_value(action)])


def _missing_command_correction(parser: argparse.ArgumentParser, message: str) -> str | None:
    if "the following arguments are required: COMMAND" not in message:
        return None
    token = next((value for value in ACTIVE_ARGV.get() if value.startswith("-")), None)
    return _flag_correction(parser, token) if token else None


def _replacement(parser: argparse.ArgumentParser, token: str) -> tuple[str, ...] | None:
    if parser.prog == "qg" and token in CONVENTIONAL_COMMANDS:
        return CONVENTIONAL_COMMANDS[token]
    matches = difflib.get_close_matches(token, _candidate_tokens(parser, token), n=1, cutoff=0.55)
    return (matches[0],) if matches else None


def _suggested_command(token: str, replacement: tuple[str, ...]) -> str:
    argv = list(ACTIVE_ARGV.get())
    if token in argv:
        index = argv.index(token)
        argv[index : index + 1] = replacement
    else:
        argv.extend(replacement)
    return shlex.join(["qg", *argv])


def _augment_parse_error(parser: argparse.ArgumentParser, message: str) -> str:
    if "the following arguments are required: profile" in message:
        return f"{message}. Did you mean: qg check fast"
    missing_command = _missing_command_correction(parser, message)
    if missing_command:
        return f"{message}. Did you mean: {missing_command}"
    token = _invalid_token(message)
    replacement = _replacement(parser, token) if token else None
    if token and replacement:
        command = _suggested_command(token, replacement)
        return f"{message}. Did you mean: {command}"
    return message


class StableHelpFormatter(argparse.HelpFormatter):
    """Render help at a deterministic width suitable for humans and discovery tools."""

    def __init__(self, prog: str) -> None:
        super().__init__(prog, max_help_position=30, width=120)


class ArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("formatter_class", StableHelpFormatter)
        super().__init__(*args, **kwargs)

    def error(self, message: str) -> Never:
        self.print_usage(sys.stderr)
        raise ConfigurationError(_augment_parse_error(self, message))


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


def _add_setup_parsers(sub: Any) -> None:
    wizard = sub.add_parser("wizard", help="guided one-command setup for non-specialists")
    wizard.add_argument("path", nargs="?", default=".")

    setup = sub.add_parser("setup", help="initialize and verify a project with optional tools")
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


def _hide_subparser_help(sub: Any, name: str) -> None:
    choices = getattr(sub, "_choices_actions", [])
    sub._choices_actions = [choice for choice in choices if choice.dest != name]


def _nested_subparsers(parser: ArgumentParser, dest: str) -> Any:
    return parser.add_subparsers(dest=dest, required=True, title="commands", metavar="COMMAND")


def _add_execution_parsers(sub: Any) -> None:
    sub.add_parser("status", help="show risk plus latest evidence and gate status")
    sub.add_parser("triage", help="show readiness, risk, evidence, and exact next commands")
    doctor = sub.add_parser("doctor", help="validate project readiness and governance")
    doctor.add_argument("--strict-tools", action="store_true")

    tools = sub.add_parser("tools", help="manage isolated project quality toolchains")
    tools_sub = _nested_subparsers(tools, "tools_command")
    install = tools_sub.add_parser("install", help="install protected quality toolchains")
    install.add_argument("--ci", action="store_true")
    install.add_argument(
        "--browsers",
        action="store_true",
        help="install Playwright Chromium when browser gates apply",
    )
    tools_sub.add_parser("status", help="show protected quality toolchain readiness")

    check = sub.add_parser("check", help="run an execution profile")
    check.add_argument("profile", choices=("fast", "pr", "deep", "release"))
    check.add_argument("--keep-going", action="store_true")
    check.add_argument("--quiet", action="store_true")

    gate = sub.add_parser("gate", help="run one policy gate with normalized evidence")
    gate.add_argument("name")

    adapter = sub.add_parser("adapter", help=argparse.SUPPRESS)
    adapter.add_argument("name", choices=sorted(HANDLERS))
    _hide_subparser_help(sub, "adapter")

    check_risk = sub.add_parser(
        "check-risk", help="resolve the risk card and run every required profile"
    )
    check_risk.add_argument("--card", default="quality/change-risk.json")
    check_risk.add_argument("--keep-going", action="store_true")
    check_risk.add_argument("--quiet", action="store_true")

    risk = sub.add_parser("risk-card", help="validate and resolve the change-risk card")
    risk.add_argument("--card", default="quality/change-risk.json")


def _add_review_parsers(sub: Any) -> None:
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
    guidance.add_argument(
        "terms",
        nargs="*",
        help="additional natural-language search terms",
    )
    guidance.add_argument("--list", action="store_true")
    guidance.add_argument("--search")

    onboarding = sub.add_parser("onboarding", help="show or refresh guided setup progress")
    onboarding_sub = _nested_subparsers(onboarding, "onboarding_command")
    onboarding_sub.add_parser("show", help="show the complete onboarding state")
    onboarding_sub.add_parser("refresh", help="recompute and store onboarding state")
    onboarding_sub.add_parser("next", help="show the next recommended setup action")


def _add_evidence_parsers(sub: Any) -> None:
    golden = sub.add_parser("golden", help="run or explicitly update deterministic golden sessions")
    golden.add_argument("--update", action="store_true")
    golden.add_argument("--scenario")

    acceptance = sub.add_parser("acceptance", help="lint Gherkin or run acceptance mutation")
    acceptance_sub = _nested_subparsers(acceptance, "acceptance_command")
    acceptance_sub.add_parser("lint", help="validate strict Gherkin feature files")
    acceptance_sub.add_parser("mutate", help="mutate examples to prove behavioral wiring")

    baseline = sub.add_parser("baseline", help="create a narrow, reviewable legacy-debt baseline")
    baseline_sub = _nested_subparsers(baseline, "baseline_command")
    baseline_test = baseline_sub.add_parser(
        "test-integrity", help="review and record current test-integrity debt"
    )
    baseline_test.add_argument(
        "--confirm", action="store_true", help="required to write the baseline"
    )

    approval = sub.add_parser(
        "approval", help="create templates or validate human approval records"
    )
    approval_sub = _nested_subparsers(approval, "approval_command")
    approval_template = approval_sub.add_parser(
        "template", help="create an unapproved human-review template"
    )
    approval_template.add_argument("kind", choices=sorted(KINDS))
    approval_template.add_argument("--reviewer")
    approval_template.add_argument("--force", action="store_true")
    approval_validate = approval_sub.add_parser(
        "validate", help="validate approval records for a risk profile"
    )
    approval_validate.add_argument("kind", nargs="?", choices=sorted(KINDS))
    approval_validate.add_argument(
        "--risk-profile", choices=("experiment", "standard", "high_assurance", "critical")
    )

    new = sub.add_parser("new", help="create behavior and QA authoring templates")
    new_sub = _nested_subparsers(new, "new_command")
    spec = new_sub.add_parser("spec", help="create a feature specification")
    spec.add_argument("name")
    spec.add_argument("--todo", action="store_true")
    spec.add_argument("--force", action="store_true")
    gherkin = new_sub.add_parser("feature", help="create a Gherkin feature")
    gherkin.add_argument("name")
    gherkin.add_argument("--force", action="store_true")
    qa = new_sub.add_parser("qa", help="create a manual QA procedure")
    qa.add_argument("name")
    qa.add_argument("--force", action="store_true")


def _add_control_parsers(sub: Any) -> None:
    sub.add_parser(
        "capabilities",
        help="describe the machine-readable command and output contract",
    )
    robot_docs = sub.add_parser("robot-docs", help="read the embedded agent operating guide")
    robot_docs_sub = _nested_subparsers(robot_docs, "robot_docs_command")
    robot_docs_sub.add_parser("guide", help="show safe setup and review workflows")
    help_parser = sub.add_parser("help", help="show help for any command path")
    help_parser.add_argument("path", nargs="*", help="command path such as onboarding refresh")
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
    portfolio_sub = _nested_subparsers(portfolio, "portfolio_command")
    port_add = portfolio_sub.add_parser("add", help="register a project")
    port_add.add_argument("path", nargs="?", default=".")
    port_add.add_argument("--name")
    port_add.add_argument("--tag", action="append", default=[])
    port_remove = portfolio_sub.add_parser("remove", help="remove a registered project")
    port_remove.add_argument("value")
    portfolio_sub.add_parser("list", help="list registered projects")
    portfolio_sub.add_parser("scan", help="aggregate registered project status")

    upgrade = sub.add_parser("upgrade", help="replace the vendored runtime and managed templates")
    upgrade.add_argument("--install", action="store_true")

    hook_pre = sub.add_parser("hook-pretool", help=argparse.SUPPRESS)
    hook_pre.set_defaults(hidden=True)
    _hide_subparser_help(sub, "hook-pretool")
    hook_stop_parser = sub.add_parser("hook-stop", help=argparse.SUPPRESS)
    hook_stop_parser.set_defaults(hidden=True)
    _hide_subparser_help(sub, "hook-stop")


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(
        prog="qg", description="Constraint-first quality control for agentic coding"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--root", help="repository root; auto-detected for initialized projects")
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON where supported"
    )
    sub = parser.add_subparsers(dest="command", required=True, title="commands", metavar="COMMAND")
    for builder in (
        _add_setup_parsers,
        _add_execution_parsers,
        _add_review_parsers,
        _add_evidence_parsers,
        _add_control_parsers,
    ):
        builder(sub)
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


def _triage_payload(root: Path) -> dict[str, Any]:
    policy = load_policy(root)
    risk_errors, risk = risk_summary(root, policy, "quality/change-risk.json")
    onboarding = current_onboarding(root)
    current = onboarding["current"]
    runs = list_runs(root, 1)
    project = load_project(root)
    return {
        "schema_version": 1,
        "project": {
            "name": project["name"],
            "stacks": sorted(name for name, enabled in project["stacks"].items() if enabled),
            "enforcement": project["enforcement"],
        },
        "readiness": {
            "summary": current["summary"],
            "stale": onboarding["stale"],
            "next_action": current["next_action"],
        },
        "risk": {
            "selected": risk["selected_risk_profile"],
            "minimum": risk["minimum_risk_profile"],
            "required_execution_profiles": risk["required_execution_profiles"],
            "errors": risk_errors,
        },
        "latest": runs[0] if runs else None,
        "commands": [
            "qg onboarding next",
            "qg doctor",
            "qg check fast",
            "qg review",
            "qg check-risk --keep-going",
        ],
    }


def _subparser_choices(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict) and choices:
            return {
                str(name): child
                for name, child in choices.items()
                if isinstance(child, argparse.ArgumentParser)
            }
    return {}


def _parser_arguments(parser: argparse.ArgumentParser) -> list[dict[str, Any]]:
    arguments: list[dict[str, Any]] = []
    for action in parser._actions:
        if action.help is argparse.SUPPRESS or isinstance(getattr(action, "choices", None), dict):
            continue
        names = list(action.option_strings) or [action.dest]
        choices = list(action.choices) if action.choices is not None else None
        arguments.append(
            {
                "names": names,
                "required": bool(action.required),
                "choices": choices,
                "nargs": action.nargs,
                "help": action.help,
            }
        )
    return sorted(arguments, key=lambda item: item["names"][-1])


def _command_descriptions(parser: argparse.ArgumentParser) -> dict[str, str]:
    descriptions = dict.fromkeys(_subparser_choices(parser), "")
    for action in parser._actions:
        choices = getattr(action, "_choices_actions", None)
        if choices is not None:
            for choice in choices:
                if choice.help != argparse.SUPPRESS:
                    descriptions[str(choice.dest)] = str(choice.help or "")
                else:
                    descriptions.pop(str(choice.dest), None)
    return descriptions


def _command_contracts(parser: argparse.ArgumentParser, prefix: str = "") -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    descriptions = _command_descriptions(parser)
    for name, child in sorted(_subparser_choices(parser).items()):
        if name not in descriptions:
            continue
        path = f"{prefix} {name}".strip()
        contracts.append(
            {
                "path": path,
                "description": descriptions[name],
                "arguments": _parser_arguments(child),
            }
        )
        contracts.extend(_command_contracts(child, path))
    return contracts


def capabilities_payload() -> dict[str, Any]:
    parser = build_parser()
    return {
        "schema_version": 1,
        "contract_version": "1.0",
        "tool": {"name": "qg", "version": __version__},
        "commands": _command_contracts(parser),
        "global_arguments": _parser_arguments(parser),
        "exit_codes": {
            "0": "measurement ran and passed",
            "1": "measurement ran and found a quality defect",
            "2": "policy, configuration, or input is invalid",
            "3": "checker, environment, timeout, or evidence failed",
        },
        "environment": {
            "AQG_DIFF_BASE": "override the comparison Git ref",
            "AQG_RUN_ID": "supply a caller-owned gate run identifier",
            "AQG_POLICY_MAINTENANCE": "authorize explicitly reviewed policy maintenance",
            "AQG_ALLOW_GOLDEN_UPDATE": "authorize explicitly reviewed golden updates",
        },
        "output": {
            "json_flag": "--json",
            "json_error_envelope": {
                "schema_version": 1,
                "status": "error",
                "error": {"category": "string", "message": "string", "exit_code": "integer"},
            },
            "stdout": "requested data",
            "stderr": "diagnostics",
        },
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


def _dispatch_detect(args: argparse.Namespace, root: Path) -> int:
    detection = detect_project(root)
    payload: dict[str, Any] = detection.as_dict()
    if args.write:
        if not policy_override_enabled(load_policy(root)):
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


def _dispatch_status(args: argparse.Namespace, root: Path) -> int:
    payload = _status_payload(root)
    _json_dump(payload) if args.json else _print_status(root, payload)
    return CONFIGURATION_ERROR if payload["risk_errors"] else PASS


def _print_triage(payload: dict[str, Any]) -> None:
    summary = payload["readiness"]["summary"]
    latest = payload["latest"]
    print(f"AQG triage · {payload['project']['name']}")
    print(
        f"Readiness: {summary['blockers']} blocker(s) · "
        f"{summary['review']} review item(s) · "
        f"{'stale' if payload['readiness']['stale'] else 'current'}"
    )
    risk = payload["risk"]
    print(f"Risk: {risk['selected']} · required: {', '.join(risk['required_execution_profiles'])}")
    print(
        f"Latest evidence: {latest['status']} ({latest['profile']})"
        if latest
        else "Latest evidence: none"
    )
    print(f"Next: {payload['readiness']['next_action']['next_step']}")
    print("Commands:")
    for command in payload["commands"]:
        print(f"  {command}")


def _dispatch_triage(args: argparse.Namespace, root: Path) -> int:
    payload = _triage_payload(root)
    _json_dump(payload) if args.json else _print_triage(payload)
    blockers = payload["readiness"]["summary"]["blockers"]
    return CONFIGURATION_ERROR if payload["risk"]["errors"] or blockers else PASS


def _dispatch_doctor(args: argparse.Namespace, root: Path) -> int:
    report = diagnose(root, strict_tools=args.strict_tools)
    _json_dump(report) if args.json else _print_doctor(report)
    return CONFIGURATION_ERROR if report["counts"]["error"] else PASS


def _dispatch_tools(args: argparse.Namespace, root: Path) -> int:
    if args.tools_command == "install":
        result = install_toolchains(root, ci=args.ci, browsers=args.browsers)
        if args.json:
            _json_dump(result)
        else:
            print(
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
    if args.json:
        _json_dump(payload)
    else:
        for item in filtered:
            print(f"{item['status']}: {item['message']}")
    return PASS


def _dispatch_check(args: argparse.Namespace, root: Path) -> int:
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


def _print_gate_evidence(name: str, evidence: dict[str, Any]) -> None:
    print(f"{name}: {evidence['status']}")
    if evidence.get("stdout"):
        print(evidence["stdout"], end="" if evidence["stdout"].endswith("\n") else "\n")
    if evidence.get("stderr"):
        print(evidence["stderr"], file=sys.stderr)


def _dispatch_gate(args: argparse.Namespace, root: Path) -> int:
    run_id = (
        os.environ.get("AQG_RUN_ID")
        or f"manual-{utc_now().replace(':', '').replace('+00:00', 'Z')}"
    )
    code, evidence = run_gate(root, load_policy(root), args.name, run_id)
    _json_dump(evidence) if args.json else _print_gate_evidence(args.name, evidence)
    return code


def _dispatch_adapter(args: argparse.Namespace, root: Path) -> int:
    code, report = run_adapter(root, args.name)
    if args.json:
        _json_dump(report)
    return code


def _dispatch_check_risk(args: argparse.Namespace, root: Path) -> int:
    return _check_risk(args, root)


def _dispatch_risk_card(args: argparse.Namespace, root: Path) -> int:
    errors, payload = risk_summary(root, load_policy(root), args.card)
    if args.json:
        _json_dump(payload)
    else:
        print(
            f"Selected: {payload['selected_risk_profile']}\n"
            f"Minimum: {payload['minimum_risk_profile']}\n"
            f"Required execution: {', '.join(payload['required_execution_profiles'])}\n"
            + ("Errors:\n- " + "\n- ".join(errors) if errors else "Risk card is valid.")
        )
    return CONFIGURATION_ERROR if errors else PASS


def _review_artifacts(
    args: argparse.Namespace, root: Path, packet: dict[str, Any]
) -> dict[str, str]:
    artifacts = write_review_packet(root, packet) if args.write else {}
    if args.sarif:
        artifacts["sarif"] = str(write_review_sarif(root, packet))
    if args.github_summary is not None:
        destination = Path(args.github_summary).expanduser() if args.github_summary else None
        artifacts["github_summary"] = str(write_github_summary(root, packet, destination))
    return artifacts


def _print_review(packet: dict[str, Any], artifacts: dict[str, str]) -> None:
    summary = packet["summary"]
    print(
        f"Review: {summary['blockers']} blocker(s), "
        f"{summary['human_review']} human review prompt(s), "
        f"{summary['changed']} changed file(s)"
    )
    for finding in packet["findings"]:
        print(f"  {finding['severity'].upper():8} {finding['title']}")
    for kind, path in artifacts.items():
        print(f"{kind}: {path}")


def _dispatch_review(args: argparse.Namespace, root: Path) -> int:
    packet = analyze_review(
        root,
        load_policy(root),
        base=_comparison_base(root, args.base),
        require_evidence=not args.no_evidence,
    )
    artifacts = _review_artifacts(args, root, packet)
    if args.json:
        _json_dump({"packet": packet, "artifacts": artifacts})
    else:
        _print_review(packet, artifacts)
    return review_exit_code(packet)


def _dispatch_changed_files(args: argparse.Namespace, root: Path) -> int:
    base = _comparison_base(root, args.base)
    files = git_changed_files(root, base)
    _json_dump({"base": base, "files": files}) if args.json else print("\n".join(files))
    return PASS


def _dispatch_capabilities(args: argparse.Namespace, root: Path) -> int:
    del root
    payload = capabilities_payload()
    if args.json:
        _json_dump(payload)
    else:
        print(f"qg {payload['tool']['version']} · contract {payload['contract_version']}")
        print(f"Commands: {len(payload['commands'])}")
        print("Exit codes: 0 pass · 1 quality · 2 configuration · 3 infrastructure")
        print("Run `qg capabilities --json` for the complete machine-readable contract.")
    return PASS


def _robot_guide_text() -> str:
    lines = [
        "# AQG agent operating guide",
        "",
        str(ROBOT_GUIDE["purpose"]),
        "",
        "## Workflows",
        "",
    ]
    for name, commands in ROBOT_GUIDE["workflows"].items():
        lines.extend([f"### {name.replace('_', ' ').title()}", ""])
        lines.extend(f"- `{command}`" for command in commands)
        lines.append("")
    lines.extend(["## Safety rules", ""])
    lines.extend(f"- {rule}" for rule in ROBOT_GUIDE["safety_rules"])
    lines.extend(
        [
            "",
            "Exit codes: `0` pass · `1` quality · `2` configuration · `3` infrastructure",
        ]
    )
    return "\n".join(lines) + "\n"


def _dispatch_robot_docs(args: argparse.Namespace, root: Path) -> int:
    del root
    _json_dump(ROBOT_GUIDE) if args.json else print(_robot_guide_text(), end="")
    return PASS


def _resolve_help_parser(path: list[str]) -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = build_parser()
    resolved: list[str] = []
    for index, segment in enumerate(path):
        choices = _subparser_choices(parser)
        if segment not in choices:
            matches = difflib.get_close_matches(segment, sorted(choices), n=1, cutoff=0.55)
            hint = ""
            if matches:
                suggestion = ["qg", "help", *resolved, matches[0], *path[index + 1 :]]
                hint = f" Try: {shlex.join(suggestion)}"
            raise ConfigurationError(
                f"unknown help command {segment!r} after {' '.join(resolved) or 'qg'}.{hint}"
            )
        parser = choices[segment]
        resolved.append(segment)
    return parser


def _dispatch_help(args: argparse.Namespace, root: Path) -> int:
    del root
    parser = _resolve_help_parser(args.path)
    rendered = parser.format_help()
    if args.json:
        _json_dump(
            {
                "schema_version": 1,
                "path": args.path,
                "usage": parser.format_usage().strip(),
                "help": rendered,
            }
        )
    else:
        print(rendered, end="")
    return PASS


def _print_guide_search(payload: list[dict[str, Any]]) -> None:
    for item in payload:
        print(f"{item['topic']}: {item['title']}\n  " + "\n  ".join(item["snippets"]))


def _print_guide_list(payload: list[dict[str, Any]]) -> None:
    for item in payload:
        suffix = f" — {item['summary']}" if item["summary"] else ""
        print(f"{item['topic']:<32} {item['title']}{suffix}")


def _dispatch_guidance(args: argparse.Namespace, root: Path) -> int:
    del root
    query = args.search or (" ".join([args.topic, *args.terms]) if args.terms else None)
    if query:
        payload = search_guides(query)
        _json_dump(payload) if args.json else _print_guide_search(payload)
    elif args.list or not args.topic:
        payload = guides()
        _json_dump(payload) if args.json else _print_guide_list(payload)
    else:
        content = read_guide(args.topic)
        _json_dump({"topic": args.topic, "content": content}) if args.json else print(content)
    return PASS


def _onboarding_state(
    args: argparse.Namespace, root: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    if args.onboarding_command == "refresh":
        payload = refresh_onboarding(root)
        return payload, {"stored": payload, "current": payload, "stale": False}
    wrapped = current_onboarding(root)
    return wrapped["current"], wrapped


def _print_onboarding_next(payload: dict[str, Any], wrapped: dict[str, Any]) -> None:
    action = payload["next_action"]
    print(f"{action['severity'].upper()}: {action['message']}")
    print(action["next_step"])
    if wrapped.get("stale"):
        print("Stored onboarding state is stale; run `python3 quality/qg.py onboarding refresh`.")


def _stage_symbol(status: str) -> str:
    return {"complete": "✓", "needs_review": "!", "blocked": "×"}.get(status, "·")


def _print_onboarding(payload: dict[str, Any], wrapped: dict[str, Any]) -> None:
    summary = payload["summary"]
    print(
        f"Onboarding: {summary['blockers']} blocker(s), "
        f"{summary['review']} review item(s), {summary['info']} informational item(s)"
    )
    state = "stale" if wrapped.get("stale") else "current"
    readiness = "ready" if summary["ready_for_guarded_use"] else "blocked"
    print(f"State: {state} · guarded use: {readiness}")
    for stage in payload["stages"]:
        print(f"  {_stage_symbol(stage['status'])} {stage['title']:<34} {stage['status']}")
    print(f"Next: {payload['next_action']['next_step']}")


def _dispatch_onboarding(args: argparse.Namespace, root: Path) -> int:
    payload, wrapped = _onboarding_state(args, root)
    if args.json:
        _json_dump(wrapped if args.onboarding_command != "refresh" else payload)
    elif args.onboarding_command == "next":
        _print_onboarding_next(payload, wrapped)
    else:
        _print_onboarding(payload, wrapped)
    return CONFIGURATION_ERROR if payload["summary"]["blockers"] else PASS


def _dispatch_golden(args: argparse.Namespace, root: Path) -> int:
    code, report = run_goldens(root, update=args.update, scenario_name=args.scenario)
    if args.json:
        _json_dump(report)
    else:
        print(
            f"Golden sessions: {report.get('status', 'unknown')} · {report.get('summary', report)}"
        )
    return code


def _dispatch_acceptance(args: argparse.Namespace, root: Path) -> int:
    if args.acceptance_command == "lint":
        report = lint_features(root)
        if args.json:
            _json_dump(report)
        else:
            print(
                f"Features: {report['feature_files']} · errors: {report['errors']} · "
                f"warnings: {report['warnings']}"
            )
        return QUALITY_FAILURE if report["errors"] else PASS
    code, report = run_acceptance_mutation(root)
    if args.json:
        _json_dump(report)
    else:
        print(
            f"Acceptance mutation: {report.get('status', 'unknown')} · {report.get('summary', {})}"
        )
    return code


def _dispatch_baseline(args: argparse.Namespace, root: Path) -> int:
    report = scan_test_integrity(root, load_project(root))
    if not args.confirm:
        _json_dump(report) if args.json else print(json.dumps(report, indent=2))
        print(
            "Refusing to write a baseline without --confirm; review every warning first.",
            file=sys.stderr,
        )
        return CONFIGURATION_ERROR
    if not policy_override_enabled(load_policy(root)):
        raise ConfigurationError("writing a baseline requires AQG_POLICY_MAINTENANCE=1")
    path = write_test_integrity_baseline(root, report)
    _json_dump({"path": str(path), "report": report}) if args.json else print(path)
    return PASS


def _approval_report(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    if args.risk_profile:
        return validate_required_approvals(root, args.risk_profile)
    if args.kind:
        errors = validate_approval(root, args.kind)
        return {
            "kind": args.kind,
            "errors": errors,
            "exit_code": QUALITY_FAILURE if errors else PASS,
        }
    raise ConfigurationError("approval validate requires a kind or --risk-profile")


def _dispatch_approval(args: argparse.Namespace, root: Path) -> int:
    if args.approval_command == "template":
        path = write_template(root, args.kind, reviewer=args.reviewer, force=args.force)
        if args.json:
            _json_dump({"path": str(path)})
        else:
            print(
                f"Created {path}. Complete it as a human review record and "
                "commit it through CODEOWNERS review."
            )
        return PASS
    report = _approval_report(args, root)
    _json_dump(report) if args.json else print(
        "Valid." if not report["errors"] else "\n".join(report["errors"])
    )
    return int(report["exit_code"])


def _dispatch_new(args: argparse.Namespace, root: Path) -> int:
    if args.new_command == "spec":
        path = create_feature_spec(root, args.name, todo=args.todo, force=args.force)
    elif args.new_command == "feature":
        path = create_gherkin_feature(root, args.name, force=args.force)
    else:
        path = create_qa_procedure(root, args.name, force=args.force)
    _json_dump({"path": str(path)}) if args.json else print(path)
    return PASS


def _print_conformance(report: dict[str, Any]) -> None:
    for suite_name in ("internal", "tools"):
        if suite_name not in report:
            continue
        suite = report[suite_name]
        summary = suite["summary"]
        skipped = f" · {summary.get('skipped', 0)} skipped" if summary.get("skipped") else ""
        print(
            f"{suite_name}: {suite['status']} · "
            f"{summary['passed']}/{summary['total']} passed{skipped}"
        )
        for case in suite["cases"]:
            print(f"  {case['status']:<5} {case['name']}")


def _dispatch_conformance(args: argparse.Namespace, root: Path) -> int:
    code, report = run_conformance(root, tools=args.tools)
    _json_dump(report) if args.json else _print_conformance(report)
    return code


def _dispatch_report(args: argparse.Namespace, root: Path) -> int:
    payload = latest_evidence_bundle(root)
    if args.output:
        path = Path(args.output).expanduser()
        write_json(path, payload)
        print(path)
    else:
        _json_dump(payload)
    return PASS


def _dispatch_dashboard(args: argparse.Namespace, root: Path) -> int:
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


def _dispatch_tui(args: argparse.Namespace, root: Path) -> int:
    del args
    run_tui(root)
    return PASS


def _dispatch_portfolio(args: argparse.Namespace, root: Path) -> int:
    del root
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


def _dispatch_upgrade(args: argparse.Namespace, root: Path) -> int:
    if not policy_override_enabled(load_policy(root)):
        raise ConfigurationError(
            "upgrade rewrites protected runtime files and requires AQG_POLICY_MAINTENANCE=1"
        )
    upgrade_runtime(root)
    result = install_toolchains(root) if args.install else {}
    payload = {"upgraded": True, "version": __version__, "tools": result}
    _json_dump(payload) if args.json else print(f"Upgraded vendored runtime to AQG {__version__}.")
    return PASS


def _dispatch_hook_pretool(args: argparse.Namespace, root: Path) -> int:
    del args
    return hook_pretool(root)


def _dispatch_hook_stop(args: argparse.Namespace, root: Path) -> int:
    del args
    return hook_stop(root)


CommandHandler = Callable[[argparse.Namespace, Path], int]

COMMAND_HANDLERS: dict[str, CommandHandler] = {
    "acceptance": _dispatch_acceptance,
    "adapter": _dispatch_adapter,
    "approval": _dispatch_approval,
    "baseline": _dispatch_baseline,
    "capabilities": _dispatch_capabilities,
    "changed-files": _dispatch_changed_files,
    "check": _dispatch_check,
    "check-risk": _dispatch_check_risk,
    "conformance": _dispatch_conformance,
    "dashboard": _dispatch_dashboard,
    "detect": _dispatch_detect,
    "doctor": _dispatch_doctor,
    "gate": _dispatch_gate,
    "golden": _dispatch_golden,
    "guidance": _dispatch_guidance,
    "help": _dispatch_help,
    "hook-pretool": _dispatch_hook_pretool,
    "hook-stop": _dispatch_hook_stop,
    "new": _dispatch_new,
    "onboarding": _dispatch_onboarding,
    "portfolio": _dispatch_portfolio,
    "report": _dispatch_report,
    "review": _dispatch_review,
    "risk-card": _dispatch_risk_card,
    "robot-docs": _dispatch_robot_docs,
    "status": _dispatch_status,
    "triage": _dispatch_triage,
    "tools": _dispatch_tools,
    "tui": _dispatch_tui,
    "upgrade": _dispatch_upgrade,
}


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "wizard":
        code, payload = run_wizard(Path(args.path))
        if args.json:
            _json_dump(payload)
        return code
    if args.command in {"setup", "init"}:
        return _initialize(args, setup=args.command == "setup")
    handler = COMMAND_HANDLERS.get(args.command)
    if handler is None:
        raise ConfigurationError(f"unknown command {args.command!r}")
    rootless = {"capabilities", "help", "robot-docs"}
    return handler(args, _root(args.root, require_initialized=args.command not in rootless))


def _normalize_global_flags(raw: list[str]) -> list[str]:
    normalized = list(raw)
    if "--json" in normalized:
        normalized = [item for item in normalized if item != "--json"]
        normalized.insert(0, "--json")
    if "--root" in normalized:
        index = normalized.index("--root")
        if index + 1 >= len(normalized):
            raise ConfigurationError("--root requires a path")
        value = normalized[index + 1]
        del normalized[index : index + 2]
        normalized[0:0] = ["--root", value]
    return normalized


def _recover_cold_start(raw: list[str]) -> list[str]:
    if not raw:
        return ["help"]
    if raw == ["--json"]:
        return ["capabilities", "--json"]
    return raw


def _emit_cli_failure(category: str, message: str, code: int, *, json_mode: bool) -> int:
    if json_mode:
        _json_dump(
            {
                "schema_version": 1,
                "status": "error",
                "error": {
                    "category": category,
                    "message": message,
                    "exit_code": code,
                },
            }
        )
    print(f"{category.replace('_', ' ')}: {message}", file=sys.stderr)
    return code


def _run_cli(parser: ArgumentParser, raw: list[str], *, json_mode: bool) -> int:
    try:
        args = parser.parse_args(raw)
        return int(dispatch(args))
    except QualityFailure as exc:
        return _emit_cli_failure("quality_failure", str(exc), QUALITY_FAILURE, json_mode=json_mode)
    except (ConfigurationError, ValueError) as exc:
        return _emit_cli_failure(
            "configuration_error", str(exc), CONFIGURATION_ERROR, json_mode=json_mode
        )
    except InfrastructureError as exc:
        return _emit_cli_failure(
            "infrastructure_error", str(exc), INFRASTRUCTURE_ERROR, json_mode=json_mode
        )
    except KeyboardInterrupt:
        return _emit_cli_failure(
            "infrastructure_error",
            "interrupted",
            INFRASTRUCTURE_ERROR,
            json_mode=json_mode,
        )
    except AQGError as exc:
        return _emit_cli_failure(
            "infrastructure_error", str(exc), INFRASTRUCTURE_ERROR, json_mode=json_mode
        )


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    json_mode = "--json" in raw
    try:
        normalized = _normalize_global_flags(_recover_cold_start(raw))
    except ConfigurationError as exc:
        return _emit_cli_failure(
            "configuration_error", str(exc), CONFIGURATION_ERROR, json_mode=json_mode
        )
    context = ACTIVE_ARGV.set(tuple(normalized))
    try:
        return _run_cli(build_parser(), normalized, json_mode=json_mode)
    finally:
        ACTIVE_ARGV.reset(context)


if __name__ == "__main__":
    raise SystemExit(main())
