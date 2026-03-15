"""Guard: local CI-parallel runner job names match ci.yml workflow jobs."""

from __future__ import annotations

import re

from tests._paths import REPO_ROOT

_CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"
_CI_PARALLEL = REPO_ROOT / "tools" / "tests" / "run_ci_parallel.py"

# Jobs that exist only in local runner (no CI counterpart needed)
_LOCAL_ONLY: set[str] = set()


def _parse_ci_yml_jobs() -> set[str]:
    """Extract top-level job names from ci.yml under the 'jobs:' key."""
    text = _CI_YML.read_text(encoding="utf-8")
    in_jobs = False
    jobs: set[str] = set()
    for line in text.splitlines():
        if line.strip() == "jobs:":
            in_jobs = True
            continue
        if in_jobs:
            match = re.match(r"^  ([a-z][a-z0-9_-]*):\s*$", line)
            if match:
                jobs.add(match.group(1))
    return jobs


def _parse_local_runner_jobs() -> set[str]:
    """Extract job names from the _job_steps dict in run_ci_parallel.py."""
    text = _CI_PARALLEL.read_text(encoding="utf-8")
    return set(re.findall(r'"([a-z][a-z0-9_-]*)":\s*\[', text))


def test_local_runner_job_names_match_ci_yml() -> None:
    ci_jobs = _parse_ci_yml_jobs()
    local_jobs = _parse_local_runner_jobs() - _LOCAL_ONLY
    assert ci_jobs, "Failed to parse any jobs from ci.yml"
    assert local_jobs, "Failed to parse any jobs from run_ci_parallel.py"
    assert local_jobs == ci_jobs, (
        f"CI job drift detected.\n"
        f"  Only in ci.yml: {ci_jobs - local_jobs or 'none'}\n"
        f"  Only in local: {local_jobs - ci_jobs or 'none'}"
    )
