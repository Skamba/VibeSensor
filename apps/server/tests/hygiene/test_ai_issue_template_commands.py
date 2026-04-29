"""Guard executable command examples in the AI change request template."""

from __future__ import annotations

import importlib.util
import re
import shlex
import sys

from tests._paths import REPO_ROOT

_AI_TEMPLATE = REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "ai_change_request.md"
_CI_MANIFEST = REPO_ROOT / "tools" / "tests" / "ci_workflow_manifest.py"
_FENCED_BASH_RE = re.compile(r"```bash\n(?P<body>.*?)\n```", re.DOTALL)


def _load_ci_manifest_module():
    spec = importlib.util.spec_from_file_location("ci_manifest_for_ai_template_test", _CI_MANIFEST)
    assert spec is not None and spec.loader is not None, f"Unable to load {_CI_MANIFEST}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _template_shell_commands() -> list[list[str]]:
    template = _AI_TEMPLATE.read_text(encoding="utf-8")
    commands: list[list[str]] = []
    for match in _FENCED_BASH_RE.finditer(template):
        for raw_line in match.group("body").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            commands.append(shlex.split(line))
    return commands


def _run_ci_jobs(tokens: list[str]) -> list[str]:
    jobs: list[str] = []
    iterator = iter(tokens)
    for token in iterator:
        if token == "--job":
            jobs.append(next(iterator))
        elif token.startswith("--job="):
            jobs.append(token.removeprefix("--job="))
    return jobs


def _repo_path_tokens(tokens: list[str]) -> set[str]:
    return {
        token
        for token in tokens[1:]
        if "/" in token and not token.startswith("-") and not token.startswith("http")
    }


def test_ai_change_request_validation_examples_reference_real_paths_and_ci_jobs() -> None:
    commands = _template_shell_commands()
    valid_ci_jobs = set(_load_ci_manifest_module().all_job_names())

    assert commands
    assert ["make", "lint"] in commands
    assert ["make", "typecheck-backend"] in commands
    assert ["make", "test-all"] in commands

    for tokens in commands:
        for path_token in _repo_path_tokens(tokens):
            assert (REPO_ROOT / path_token).exists(), f"{path_token} does not exist"
        if "tools/tests/run_ci_parallel.py" in tokens:
            jobs = _run_ci_jobs(tokens)
            assert jobs
            assert set(jobs) <= valid_ci_jobs
