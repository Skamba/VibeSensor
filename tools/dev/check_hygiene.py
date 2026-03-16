"""Repository hygiene checks: line endings (LF-only), path indirection, and CI job sync."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

TEXT_EXTS = {
    ".py",
    ".js",
    ".css",
    ".html",
    ".md",
    ".yml",
    ".yaml",
    ".sh",
    ".service",
    ".toml",
    ".cpp",
    ".h",
}

_RELATIVE_POINTER_RE = re.compile(r"^(?:\./|\.\./)\S+$")
_PY_PATH_HACK_RE = re.compile(r"sys\.path\.(?:insert|append)\(|PYTHONPATH=")


def _git_tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=False,
    ).stdout
    return [ROOT / p.decode("utf-8", errors="replace") for p in out.split(b"\x00") if p]


def check_line_endings() -> list[str]:
    offenders: list[str] = []
    for path in _git_tracked_files():
        if path.suffix.lower() not in TEXT_EXTS:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if b"\r\n" in data:
            offenders.append(str(path.relative_to(ROOT)))
    return offenders


def _is_pointer_file(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return len(lines) == 1 and bool(_RELATIVE_POINTER_RE.fullmatch(lines[0]))


def check_path_indirections() -> tuple[list[str], list[str]]:
    pointer_files: list[str] = []
    python_path_hacks: list[str] = []
    for path in _git_tracked_files():
        if ".git" in path.parts:
            continue
        rel = str(path.relative_to(ROOT))
        if _is_pointer_file(path):
            pointer_files.append(rel)
        if path.suffix == ".py" and rel != "tools/dev/check_hygiene.py":
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if _PY_PATH_HACK_RE.search(text):
                python_path_hacks.append(rel)
    return pointer_files, python_path_hacks


_CI_JOB_RE = re.compile(r"^  (\w[\w-]*):\s*$")
_PARALLEL_JOB_RE = re.compile(r'"([^"]+)":\s*\[')


def check_ci_job_sync() -> list[str]:
    """Verify run_ci_parallel.py job names match ci.yml job names."""
    ci_yml = ROOT / ".github" / "workflows" / "ci.yml"
    parallel_py = ROOT / "tools" / "tests" / "run_ci_parallel.py"
    errors: list[str] = []
    if not ci_yml.exists() or not parallel_py.exists():
        return errors

    ci_jobs: set[str] = set()
    in_jobs = False
    for line in ci_yml.read_text().splitlines():
        if line.rstrip() == "jobs:":
            in_jobs = True
            continue
        if in_jobs:
            m = _CI_JOB_RE.match(line)
            if m:
                ci_jobs.add(m.group(1))

    parallel_jobs: set[str] = set()
    py_text = parallel_py.read_text()
    for m in _PARALLEL_JOB_RE.finditer(py_text):
        parallel_jobs.add(m.group(1))

    only_ci = ci_jobs - parallel_jobs
    only_parallel = parallel_jobs - ci_jobs
    if only_ci:
        errors.append(f"CI jobs not mirrored in run_ci_parallel.py: {sorted(only_ci)}")
    if only_parallel:
        errors.append(f"run_ci_parallel.py jobs not in ci.yml: {sorted(only_parallel)}")
    return errors


def main() -> int:
    failures = 0

    crlf = check_line_endings()
    if crlf:
        print("CRLF line endings found:")
        for item in crlf:
            print(f"  - {item}")
        failures += 1
    else:
        print("Line ending check passed (LF-only for tracked text files).")

    pointer_files, path_hacks = check_path_indirections()
    if pointer_files or path_hacks:
        if pointer_files:
            print("Pointer-style files found:")
            for item in pointer_files:
                print(f"  - {item}")
        if path_hacks:
            print("sys.path/PYTHONPATH hacks found in Python files:")
            for item in path_hacks:
                print(f"  - {item}")
        failures += 1
    else:
        print("No path-indirection files or sys.path/PYTHONPATH hacks found.")

    ci_sync_errors = check_ci_job_sync()
    if ci_sync_errors:
        print("CI job sync drift detected:")
        for item in ci_sync_errors:
            print(f"  - {item}")
        failures += 1
    else:
        print("CI job names in sync between ci.yml and run_ci_parallel.py.")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
