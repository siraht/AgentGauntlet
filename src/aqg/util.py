"""Small, dependency-free helpers shared by the CLI and project runtime."""

from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable, Mapping, Sequence

from .constants import CONFIGURATION_ERROR, INFRASTRUCTURE_ERROR, PASS, QUALITY_FAILURE, STATUS_NAMES
from .errors import ConfigurationError, InfrastructureError


@dataclass(slots=True)
class CommandResult:
    command: list[str]
    cwd: str
    code: int
    status: str
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "cwd": self.cwd,
            "code": self.code,
            "status": self.status,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_ms": self.duration_ms,
            "timed_out": self.timed_out,
        }


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def slugify(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "-", value.strip().lower()).strip("-")
    return value or "project"


def read_json(path: Path, *, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if default is not None:
            return default
        raise ConfigurationError(f"missing JSON file: {path}")
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"invalid JSON in {path}: {exc}") from exc


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_paths(root: Path, paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted({p.resolve() for p in paths if p.exists()}):
        try:
            rel = path.relative_to(root.resolve()).as_posix()
        except ValueError:
            rel = str(path)
        digest.update(rel.encode())
        digest.update(b"\0")
        if path.is_file():
            digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def shell_join(parts: Sequence[str]) -> str:
    return shlex.join([str(p) for p in parts])


def run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    timeout: int = 300,
    env: Mapping[str, str] | None = None,
    stream: bool = False,
    quality_exit_codes: Iterable[int] = (1,),
) -> CommandResult:
    argv = [str(value) for value in command]
    merged_env = os.environ.copy()
    if env:
        merged_env.update({str(k): str(v) for k, v in env.items()})
    started = time.monotonic()
    try:
        if stream:
            completed = subprocess.run(argv, cwd=cwd, env=merged_env, timeout=timeout, check=False)
            stdout = ""
            stderr = ""
        else:
            completed = subprocess.run(
                argv,
                cwd=cwd,
                env=merged_env,
                timeout=timeout,
                text=True,
                capture_output=True,
                check=False,
            )
            stdout = completed.stdout
            stderr = completed.stderr
        code = completed.returncode
        if code == 0:
            status = STATUS_NAMES[PASS]
        elif code in set(quality_exit_codes):
            status = STATUS_NAMES[QUALITY_FAILURE]
        else:
            status = STATUS_NAMES[INFRASTRUCTURE_ERROR]
        return CommandResult(
            command=argv,
            cwd=str(cwd),
            code=code,
            status=status,
            stdout=stdout,
            stderr=stderr,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    except FileNotFoundError as exc:
        return CommandResult(
            command=argv,
            cwd=str(cwd),
            code=CONFIGURATION_ERROR,
            status=STATUS_NAMES[CONFIGURATION_ERROR],
            stdout="",
            stderr=f"command not found: {argv[0]} ({exc})",
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return CommandResult(
            command=argv,
            cwd=str(cwd),
            code=INFRASTRUCTURE_ERROR,
            status=STATUS_NAMES[INFRASTRUCTURE_ERROR],
            stdout=stdout,
            stderr=(stderr + f"\ncommand timed out after {timeout}s").strip(),
            duration_ms=int((time.monotonic() - started) * 1000),
            timed_out=True,
        )


def matches_any(path: str, patterns: Iterable[str]) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    for pattern in patterns:
        candidate = str(pattern).replace("\\", "/").lstrip("./")
        if fnmatch.fnmatchcase(normalized, candidate):
            return True
        if candidate.startswith("**/") and fnmatch.fnmatchcase(normalized, candidate[3:]):
            return True
        if candidate.endswith("/**") and normalized == candidate[:-3].rstrip("/"):
            return True
    return False


def iter_files(root: Path, suffixes: Iterable[str], excludes: Iterable[str]) -> list[Path]:
    suffix_set = {suffix.lower() for suffix in suffixes}
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if matches_any(rel, excludes):
            continue
        if path.suffix.lower() in suffix_set:
            files.append(path)
    return sorted(files)


def git_output(root: Path, args: Sequence[str]) -> tuple[int, str, str]:
    if not command_exists("git"):
        return CONFIGURATION_ERROR, "", "git is not installed"
    completed = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)
    return completed.returncode, completed.stdout, completed.stderr


def _status_paths(root: Path) -> set[str]:
    """Return worktree paths, including untracked and renamed files."""
    code, stdout, _ = git_output(root, ["-c", "core.quotepath=false", "status", "--porcelain=v1", "--untracked-files=all"])
    if code != 0:
        return set()
    paths: set[str] = set()
    for line in stdout.splitlines():
        if len(line) < 4:
            continue
        value = line[3:].strip()
        if " -> " in value:
            value = value.rsplit(" -> ", 1)[-1]
        value = value.strip('"')
        if value:
            paths.add(value)
    return paths


def detect_base_ref(root: Path) -> str:
    """Choose the best available comparison ref without assuming a branch name.

    Preference order is the remote default branch, common local/remote mainline
    branches, then HEAD for a newly initialized or single-commit repository.
    """
    code, stdout, _ = git_output(root, ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"])
    if code == 0 and stdout.strip():
        return stdout.strip()
    for candidate in ("origin/main", "main", "origin/master", "master"):
        code, _, _ = git_output(root, ["rev-parse", "--verify", "--quiet", candidate])
        if code == 0:
            return candidate
    code, _, _ = git_output(root, ["rev-parse", "--verify", "--quiet", "HEAD"])
    return "HEAD" if code == 0 else "HEAD"


def git_changed_files(root: Path, base: str = "HEAD", include_worktree: bool = True) -> list[str]:
    candidates = [
        ["diff", "--name-only", f"{base}...HEAD"],
        ["diff", "--name-only", base],
        ["diff", "--name-only", "HEAD~1...HEAD"],
    ]
    for args in candidates:
        code, stdout, _ = git_output(root, args)
        if code == 0:
            files = {line.strip() for line in stdout.splitlines() if line.strip()}
            if include_worktree:
                for extra_args in (["diff", "--name-only"], ["diff", "--name-only", "--cached"]):
                    extra_code, extra_out, _ = git_output(root, extra_args)
                    if extra_code == 0:
                        files.update(line.strip() for line in extra_out.splitlines() if line.strip())
                files.update(_status_paths(root))
            return sorted(files)
    code, stdout, _ = git_output(root, ["status", "--porcelain"])
    if code == 0:
        return sorted({line[3:].strip() for line in stdout.splitlines() if len(line) > 3})
    return []


def git_diff(root: Path, base: str = "HEAD", unified: int = 0) -> str:
    candidates = [
        ["diff", f"--unified={unified}", f"{base}...HEAD"],
        ["diff", f"--unified={unified}", base],
        ["diff", f"--unified={unified}", "HEAD~1...HEAD"],
    ]
    for args in candidates:
        code, stdout, _ = git_output(root, args)
        if code == 0:
            work_code, work_out, _ = git_output(root, ["diff", f"--unified={unified}"])
            staged_code, staged_out, _ = git_output(root, ["diff", "--cached", f"--unified={unified}"])
            return stdout + (work_out if work_code == 0 else "") + (staged_out if staged_code == 0 else "")
    return ""


def git_revision(root: Path) -> str:
    code, stdout, _ = git_output(root, ["rev-parse", "HEAD"])
    return stdout.strip() if code == 0 else "uncommitted"




def change_fingerprint(
    root: Path,
    base: str = "HEAD",
    *,
    exclude_patterns: Iterable[str] = (),
) -> str:
    """Hash the complete current review surface, including untracked and deleted files.

    The fingerprint is independent of generated `.aqg` evidence because those paths are
    excluded by project policy. It changes when the base diff, a tracked worktree file,
    an untracked file, or a deletion changes.
    """
    digest = hashlib.sha256()
    digest.update(base.encode())
    digest.update(b"\0")
    digest.update(git_revision(root).encode())
    digest.update(b"\0")
    diff = git_diff(root, base, unified=3)
    digest.update(diff.encode("utf-8", errors="replace"))
    digest.update(b"\0")
    for rel in git_changed_files(root, base, include_worktree=True):
        if matches_any(rel, exclude_patterns):
            continue
        digest.update(rel.encode("utf-8", errors="replace"))
        digest.update(b"\0")
        path = root / rel
        if path.is_file():
            digest.update(b"file\0")
            try:
                digest.update(path.read_bytes())
            except OSError as exc:
                digest.update(f"unreadable:{exc}".encode())
        elif path.is_dir():
            digest.update(b"dir\0")
        else:
            digest.update(b"deleted\0")
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def control_fingerprint(root: Path) -> str:
    """Hash files that define AQG policy, commands, toolchains, and governance."""
    candidates: list[Path] = []
    explicit = [
        root / "QUALITY.md",
        root / "AGENTS.md",
        root / "CLAUDE.md",
        root / "KEYSTONE.md",
        root / ".github" / "CODEOWNERS",
        root / ".github" / "workflows" / "quality-gauntlet.yml",
    ]
    candidates.extend(path for path in explicit if path.is_file())
    quality = root / "quality"
    if quality.exists():
        for path in quality.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if matches_any(rel, ["quality/approvals/**", "quality/guidance/**"]):
                continue
            candidates.append(path)
    return "sha256:" + sha256_paths(root, candidates)


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / "quality" / "project.json").is_file() or (candidate / "quality" / "policy.toml").is_file():
            return candidate
    raise ConfigurationError("could not find quality/project.json or quality/policy.toml")


def atomic_write(path: Path, content: str, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
        os.replace(temp_name, path)
        if mode is not None:
            path.chmod(mode)
    finally:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass


def merge_gitignore(root: Path, lines: Iterable[str]) -> None:
    path = root / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    existing_lines = set(existing.splitlines())
    additions = [line for line in lines if line not in existing_lines]
    if not additions:
        return
    content = existing.rstrip() + ("\n\n" if existing.strip() else "") + "# Agent Quality Gauntlet\n" + "\n".join(additions) + "\n"
    atomic_write(path, content)


def human_duration(milliseconds: int) -> str:
    seconds = milliseconds / 1000
    if seconds < 1:
        return f"{milliseconds}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{int(seconds // 60)}m {seconds % 60:.0f}s"


def terminal_supports_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
