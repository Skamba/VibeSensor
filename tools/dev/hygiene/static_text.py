# ruff: noqa: F403,F405
"""Static docs/config text hygiene checks."""

from __future__ import annotations

import re
import shlex

from ._shared import *
from .ci_workflow import _load_ci_manifest_module

_AI_TEMPLATE = ROOT / ".github" / "ISSUE_TEMPLATE" / "ai_change_request.md"
_FENCED_BASH_RE = re.compile(r"```bash\n(?P<body>.*?)\n```", re.DOTALL)
_STAGE_RUN_TEMPLATE = (
    ROOT
    / "infra/pi-image/pi-gen/templates/stage-vibesensor/00-vibesensor/00-run.sh.template"
)
_STANDARD_LICENSE_MARKERS = (
    "mit license",
    "apache license",
    "gnu general public license",
    "bsd 2-clause license",
    "bsd 3-clause license",
    "mozilla public license",
)
_UNLICENSED_NOTICE_MARKERS = (
    "not currently distributed under an open-source license",
    "all rights reserved",
    "no additional permission is granted",
)


def _template_shell_commands(template_text: str) -> list[list[str]]:
    commands: list[list[str]] = []
    for match in _FENCED_BASH_RE.finditer(template_text):
        for raw_line in match.group("body").splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#"):
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


def _ignore_patterns(path: str) -> set[str]:
    return {
        line.strip()
        for line in (ROOT / path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def _has_standard_license(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    return any(marker in normalized for marker in _STANDARD_LICENSE_MARKERS)


def _has_explicit_unlicensed_notice(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    return all(marker in normalized for marker in _UNLICENSED_NOTICE_MARKERS)


def _check_contributing_config_presets() -> list[str]:
    contributing_text = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    try:
        preset_table = contributing_text.split(
            "Preset files ship with the repo", maxsplit=1
        )[1].split("**Quick start for local dev:**", maxsplit=1)[0]
    except IndexError:
        return [
            "CONTRIBUTING.md must keep the backend config preset table before the local-dev quick start."
        ]

    documented_presets = set(re.findall(r"`(config\.[a-z0-9_-]+\.yaml)`", preset_table))
    shipped_presets = {
        preset_path.name
        for preset_path in (ROOT / "apps" / "server").glob("config.*.yaml")
    }
    missing = sorted(shipped_presets - documented_presets)
    if missing:
        return [
            f"CONTRIBUTING.md must document shipped backend config presets: {missing}"
        ]
    return []


def _check_ai_template_commands() -> list[str]:
    commands = _template_shell_commands(_AI_TEMPLATE.read_text(encoding="utf-8"))
    errors: list[str] = []
    if not commands:
        return [
            ".github/ISSUE_TEMPLATE/ai_change_request.md must include bash validation examples."
        ]

    for required in (
        ["make", "lint"],
        ["make", "typecheck-backend"],
        ["make", "test-all"],
    ):
        if required not in commands:
            errors.append(
                ".github/ISSUE_TEMPLATE/ai_change_request.md must keep validation examples for "
                + " ".join(required)
                + "."
            )

    valid_ci_jobs = set(_load_ci_manifest_module().all_job_names())
    for tokens in commands:
        for path_token in _repo_path_tokens(tokens):
            if not (ROOT / path_token).exists():
                errors.append(
                    ".github/ISSUE_TEMPLATE/ai_change_request.md validation example references "
                    f"missing path {path_token!r}."
                )
        if "tools/tests/run_ci_parallel.py" in tokens:
            jobs = _run_ci_jobs(tokens)
            if not jobs:
                errors.append(
                    ".github/ISSUE_TEMPLATE/ai_change_request.md run_ci_parallel.py example must include --job arguments."
                )
            unknown_jobs = sorted(set(jobs) - valid_ci_jobs)
            if unknown_jobs:
                errors.append(
                    ".github/ISSUE_TEMPLATE/ai_change_request.md run_ci_parallel.py example references "
                    f"unknown jobs: {unknown_jobs}."
                )
    return errors


def _check_dockerignore_runtime_data() -> list[str]:
    gitignore_patterns = _ignore_patterns(".gitignore")
    dockerignore_patterns = _ignore_patterns(".dockerignore")
    server_runtime_patterns = {
        pattern
        for pattern in gitignore_patterns
        if pattern.startswith("apps/server/data/")
        or pattern == "apps/server/wifi-secrets.env"
    }
    if not server_runtime_patterns:
        return [
            ".gitignore must list server runtime data patterns so Docker context hygiene can mirror them."
        ]
    missing = sorted(server_runtime_patterns - dockerignore_patterns)
    if missing:
        return [
            f".dockerignore must mirror server runtime data ignore patterns: {missing}"
        ]
    return []


def _check_license_notice() -> list[str]:
    errors: list[str] = []
    license_path = ROOT / "LICENSE"
    if not license_path.exists():
        errors.append(
            "Public repos must keep LICENSE or an explicit unlicensed notice."
        )
    else:
        license_text = license_path.read_text(encoding="utf-8")
        if not (
            _has_standard_license(license_text)
            or _has_explicit_unlicensed_notice(license_text)
        ):
            errors.append(
                "LICENSE must be a standard license or explicit unlicensed notice."
            )

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    if "## License" not in readme or "[LICENSE](LICENSE)" not in readme:
        errors.append("README.md must link to LICENSE from a License section.")
    return errors


def _check_pi_baseline_firmware_script() -> list[str]:
    text = _STAGE_RUN_TEMPLATE.read_text(encoding="utf-8")
    match = re.search(
        r"cat >/tmp/vibesensor-fw-baseline\.sh <<'FW_BASELINE_EOF'\n(?P<body>.*?)\nFW_BASELINE_EOF",
        text,
        re.DOTALL,
    )
    if match is None:
        return [
            "Pi image stage template must keep the /tmp/vibesensor-fw-baseline.sh heredoc."
        ]
    body = match.group("body")
    venv_python_assignment = (
        'VENV_PYTHON="/opt/VibeSensor/apps/server/.venv/bin/python"'
    )
    metadata_patch = '"${VENV_PYTHON}" -c "'
    if venv_python_assignment not in body or metadata_patch not in body:
        return [
            "Pi image baseline-firmware helper must use VENV_PYTHON for metadata patching."
        ]
    if body.index(venv_python_assignment) > body.index(metadata_patch):
        return [
            "Pi image baseline-firmware helper must define VENV_PYTHON before metadata patching."
        ]
    return []


def check_static_text_hygiene() -> list[str]:
    errors: list[str] = []
    errors.extend(_check_contributing_config_presets())
    errors.extend(_check_ai_template_commands())
    errors.extend(_check_dockerignore_runtime_data())
    errors.extend(_check_license_notice())
    errors.extend(_check_pi_baseline_firmware_script())
    return errors
