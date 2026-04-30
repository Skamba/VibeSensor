#!/usr/bin/env python3
"""Docs misuse / wrapper hack detector (R0/R1 compliance).

Checks:
1. No docs files contain large code blocks (>30 lines) that look like
   executable logic rather than examples.
2. No source files read/execute docs content at runtime.

Exit 0 if clean, 1 if violations found.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

LARGE_BLOCK_THRESHOLD = 30  # lines
EXCLUDED_DIRS = {
    ".git",
    "node_modules",
    ".pio",
    "dist",
    "__pycache__",
    ".cache",
    "artifacts",
    ".venv",
    ".pytest_cache",
    ".ruff_cache",
}
ALLOWED_AI_GUIDANCE_DOCS = {"docs/ai/repo-map.md"}
AGENTS_CANONICAL_LINK = ".github/copilot-instructions.md"
COPILOT_CANONICAL_MARKER = (
    "This file is the canonical AI guidance entrypoint and short index."
)
REPO_MAP_SCOPE_MARKER = "This file is the repo map, not a workflow or policy guide."
GUIDANCE_SCRIPT_SUFFIXES = (".py", ".sh", ".mjs", ".cjs", ".js")
GUIDANCE_SCRIPT_STARTS = (
    ".githooks/",
    "apps/server/scripts/",
    "apps/ui/dev-docker.sh",
    "infra/pi-image/",
    "tools/",
)
REPO_PATH_PREFIXES = (
    ".github/",
    "apps/",
    "docs/",
    "firmware/",
    "infra/",
    "tools/",
    "AGENTS.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "Makefile",
    "README.md",
    "SECURITY.md",
    "docker-compose.dev.yml",
    "docker-compose.yml",
)
GENERATED_REPO_PATH_REFERENCES = {
    "apps/ui/src/constants.ts",
}
STALE_REPO_PATH_REFERENCES = {
    "infra/processing/fft.py": "apps/server/vibesensor/shared/fft_analysis.py",
}
MAKE_COMMAND_RE = re.compile(r"(?<![\w./-])make\s+(?P<args>[^`#\n]*)")
MAKE_TARGET_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
MAKE_OPTION_ARGS = {"-C", "-f", "--file", "--directory"}
NPM_RUN_RE = re.compile(r"(?<![\w./-])npm\s+run\s+(?P<script>[A-Za-z0-9:._-]+)")
CI_JOB_ARG_RE = re.compile(r"(?<!\S)(?:-j|--job)\s+(?P<job>[A-Za-z0-9_-]+)")
DIRECT_SHELL_SCRIPT_RE = re.compile(
    r"(?:^|[`;\s])(?:[A-Z_][A-Z0-9_]*=[^`\s]+\s+)*(?:sudo\s+)?\./"
    r"(?P<path>(?:apps/server/scripts/|infra/|tools/)[A-Za-z0-9._~/-]+\.sh)\b"
)
DESIGN_DOC_STATUS_RE = re.compile(
    r"^\s*>?\s*\*\*Status:\*\*\s*(Active|Historical|Superseded)\s*$",
    re.MULTILINE,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_repo_tooling_support():
    helper_path = REPO_ROOT / "tools" / "repo_tooling_support.py"
    spec = importlib.util.spec_from_file_location("repo_tooling_support", helper_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load repo tooling helpers from {helper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_repo_tooling_support = _load_repo_tooling_support()


def _walk_files(repo_root: Path) -> list[str]:
    return _repo_tooling_support.walk_files(repo_root, EXCLUDED_DIRS)


def _tracked_files(repo_root: Path) -> list[str]:
    return _repo_tooling_support.tracked_files(repo_root, EXCLUDED_DIRS)


def _check_large_code_blocks(docs_files: list[str]) -> list[str]:
    """Flag docs files with code blocks exceeding threshold."""
    issues: list[str] = []
    fence_re = re.compile(r"^```")
    for path in docs_files:
        try:
            with open(path) as fh:
                lines = fh.readlines()
        except (OSError, UnicodeDecodeError):
            continue
        in_block = False
        block_start = 0
        block_lines = 0
        for i, line in enumerate(lines, 1):
            if fence_re.match(line):
                if in_block:
                    if block_lines > LARGE_BLOCK_THRESHOLD:
                        issues.append(
                            f"{path}:{block_start}-{i}: code block "
                            f"({block_lines} lines) exceeds {LARGE_BLOCK_THRESHOLD}-line threshold"
                        )
                    in_block = False
                    block_lines = 0
                else:
                    in_block = True
                    block_start = i
                    block_lines = 0
            elif in_block:
                block_lines += 1
    return issues


def _check_runtime_docs_reading(source_files: list[str]) -> list[str]:
    """Flag source files that open/read/exec docs content."""
    issues: list[str] = []
    patterns = [
        re.compile(r"""open\s*\(\s*['"].*docs/"""),
        re.compile(r"""Path\s*\(\s*['"].*docs/"""),
        re.compile(r"""exec\s*\(.*docs"""),
        re.compile(r"""subprocess.*docs/"""),
    ]
    source_exts = {".py", ".ts", ".js", ".sh"}
    for path in source_files:
        if Path(path).suffix not in source_exts:
            continue
        if "docs/" in path or "tools/dev/" in path:
            continue
        try:
            with open(path) as fh:
                content = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        for pat in patterns:
            match = pat.search(content)
            if match:
                issues.append(f"{path}: runtime docs access: {match.group()}")
    return issues


def _check_markdown_links(markdown_files: list[str], repo_root: Path) -> list[str]:
    """Flag broken local markdown links."""
    issues: list[str] = []
    link_re = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
    ignored_prefixes = (
        "http://",
        "https://",
        "mailto:",
        "tel:",
        "data:",
        "javascript:",
    )
    for path in markdown_files:
        md_path = repo_root / path
        try:
            content = md_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in link_re.finditer(content):
            target = match.group(1).strip()
            if (
                not target
                or target.startswith("#")
                or target.startswith(ignored_prefixes)
            ):
                continue
            target = target.strip("<>").split("#", 1)[0].strip()
            if not target:
                continue
            target_path = (
                (repo_root / target.lstrip("/"))
                if target.startswith("/")
                else (md_path.parent / target)
            )
            if not target_path.exists():
                issues.append(f"{path}: broken link target: {target}")
    return issues


def _read_text(repo_root: Path, relative_path: str) -> str | None:
    try:
        return (repo_root / relative_path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _makefile_targets(repo_root: Path) -> set[str]:
    makefile_text = _read_text(repo_root, "Makefile")
    if makefile_text is None:
        return set()
    targets: set[str] = set()
    for line in makefile_text.splitlines():
        if not line or line.startswith(("\t", " ", "#")) or ":" not in line:
            continue
        raw_targets = line.split(":", 1)[0].strip().split()
        for target in raw_targets:
            if MAKE_TARGET_RE.fullmatch(target):
                targets.add(target)
    return targets


def _ui_npm_scripts(repo_root: Path) -> set[str]:
    package_json_text = _read_text(repo_root, "apps/ui/package.json")
    if package_json_text is None:
        return set()
    try:
        payload = json.loads(package_json_text)
    except json.JSONDecodeError:
        return set()
    scripts = payload.get("scripts")
    if not isinstance(scripts, dict):
        return set()
    return {name for name in scripts if isinstance(name, str)}


def _raw_workflow_job_ids(repo_root: Path) -> set[str]:
    workflow_text = _read_text(repo_root, ".github/workflows/ci.yml")
    if workflow_text is None:
        return set()
    job_ids: set[str] = set()
    in_jobs = False
    job_re = re.compile(r"^  (?P<job>[A-Za-z0-9_-]+):(?:\s+#.*)?$")
    for line in workflow_text.splitlines():
        stripped = line.strip()
        if stripped == "jobs:":
            in_jobs = True
            continue
        if not in_jobs or not stripped or stripped.startswith("#"):
            continue
        if not line.startswith(" "):
            break
        match = job_re.match(line)
        if match:
            job_ids.add(match.group("job"))
    return job_ids


def _local_logical_ci_job_ids(repo_root: Path) -> set[str]:
    workflow_text = _read_text(repo_root, ".github/workflows/ci.yml")
    if workflow_text is None:
        return set()

    raw_job_ids = _raw_workflow_job_ids(repo_root)
    local_job_ids = set(raw_job_ids) - {"ci-scope", "ui-build-artifact"}
    matrix_parent_jobs: set[str] = set()
    current_job: str | None = None
    job_re = re.compile(r"^  (?P<job>[A-Za-z0-9_-]+):(?:\s+#.*)?$")
    logical_job_re = re.compile(
        r"^\s+-?\s*logical_job_name:\s*[\"']?(?P<job>[A-Za-z0-9_-]+)"
        r"[\"']?(?:\s+#.*)?$"
    )
    for line in workflow_text.splitlines():
        job_match = job_re.match(line)
        if job_match:
            current_job = job_match.group("job")
            continue
        logical_job_match = logical_job_re.match(line)
        if current_job and logical_job_match:
            local_job_ids.add(logical_job_match.group("job"))
            matrix_parent_jobs.add(current_job)

    return local_job_ids - matrix_parent_jobs


def _markdown_code_snippets(text: str) -> list[str]:
    snippets: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            snippets.append(line)
    snippets.extend(match.group(1) for match in re.finditer(r"`([^`\n]+)`", text))
    return snippets


def _first_make_target(args: str) -> str | None:
    tokens = [token.strip(".,;:)") for token in args.split()]
    skip_next = False
    for token in tokens:
        if not token:
            continue
        if skip_next:
            skip_next = False
            continue
        if token in {"&&", "||", "|"}:
            return None
        if token in MAKE_OPTION_ARGS:
            skip_next = True
            continue
        if token.startswith("-"):
            continue
        if "=" in token or token.startswith("$"):
            continue
        if MAKE_TARGET_RE.fullmatch(token):
            return token
    return None


def _check_make_command_targets(
    markdown_files: list[str], repo_root: Path
) -> list[str]:
    """Flag documented make targets that do not exist in the Makefile."""
    targets = _makefile_targets(repo_root)
    if not targets:
        return ["Makefile targets could not be loaded for docs command lint"]

    issues: list[str] = []
    for path in sorted(markdown_files):
        text = _read_text(repo_root, path)
        if text is None:
            continue
        for snippet in _markdown_code_snippets(text):
            for match in MAKE_COMMAND_RE.finditer(snippet):
                target = _first_make_target(match.group("args"))
                if target is not None and target not in targets:
                    issues.append(
                        f"{path}: documented make target does not exist: {target}"
                    )
    return issues


def _check_npm_run_scripts(markdown_files: list[str], repo_root: Path) -> list[str]:
    """Flag documented UI npm scripts that do not exist in apps/ui/package.json."""
    scripts = _ui_npm_scripts(repo_root)
    if not scripts:
        return [
            "apps/ui/package.json scripts could not be loaded for docs command lint"
        ]

    issues: list[str] = []
    for path in sorted(markdown_files):
        text = _read_text(repo_root, path)
        if text is None:
            continue
        for snippet in _markdown_code_snippets(text):
            for match in NPM_RUN_RE.finditer(snippet):
                script = match.group("script")
                if script not in scripts:
                    issues.append(
                        f"{path}: documented npm script does not exist in apps/ui/package.json: {script}"
                    )
    return issues


def _check_ci_job_examples(
    markdown_files: list[str],
    repo_root: Path,
    *,
    raw_workflow_job_ids: set[str] | None = None,
    local_logical_job_ids: set[str] | None = None,
) -> list[str]:
    """Flag ACT/local runner job examples that use the wrong job-id namespace."""
    raw_job_ids = raw_workflow_job_ids or _raw_workflow_job_ids(repo_root)
    local_job_ids = local_logical_job_ids or _local_logical_ci_job_ids(repo_root)
    if not raw_job_ids:
        return ["CI workflow job ids could not be loaded for docs command lint"]
    if not local_job_ids:
        return ["local CI logical job ids could not be loaded for docs command lint"]

    issues: list[str] = []
    for path in sorted(markdown_files):
        text = _read_text(repo_root, path)
        if text is None:
            continue
        for snippet in _markdown_code_snippets(text):
            if "act " in snippet or "run_ci_with_act.sh" in snippet:
                for match in CI_JOB_ARG_RE.finditer(snippet):
                    job = match.group("job")
                    if job not in raw_job_ids:
                        issues.append(
                            f"{path}: ACT job example must use raw workflow job id: {job}"
                        )
            if "run_ci_parallel.py" in snippet:
                for match in CI_JOB_ARG_RE.finditer(snippet):
                    job = match.group("job")
                    if job not in local_job_ids:
                        issues.append(
                            f"{path}: local CI job example must use logical job id: {job}"
                        )
    return issues


def _check_ai_guidance_stack(markdown_files: list[str], repo_root: Path) -> list[str]:
    """Flag AI guidance drift in the canonical entrypoint stack."""
    issues: list[str] = []
    instruction_files = sorted(
        path
        for path in markdown_files
        if path.startswith(".github/instructions/")
        and path.endswith(".instructions.md")
    )

    docs_ai_files = {path for path in markdown_files if path.startswith("docs/ai/")}
    unexpected_guides = sorted(docs_ai_files - ALLOWED_AI_GUIDANCE_DOCS)
    missing_guides = sorted(ALLOWED_AI_GUIDANCE_DOCS - docs_ai_files)
    for path in unexpected_guides:
        issues.append(f"unexpected docs/ai guidance file: {path}")
    for path in missing_guides:
        issues.append(f"missing expected docs/ai guidance file: {path}")

    agents_text = _read_text(repo_root, "AGENTS.md")
    if agents_text is None:
        issues.append("missing AGENTS.md")
    else:
        agent_links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", agents_text)
        if agent_links != [AGENTS_CANONICAL_LINK]:
            issues.append(
                "AGENTS.md should link only to .github/copilot-instructions.md"
            )

    copilot_text = _read_text(repo_root, ".github/copilot-instructions.md")
    if copilot_text is None:
        issues.append("missing .github/copilot-instructions.md")
    else:
        if COPILOT_CANONICAL_MARKER not in copilot_text:
            issues.append(
                ".github/copilot-instructions.md must declare the canonical AI guidance entrypoint"
            )
        if ".github/instructions/general.instructions.md" not in copilot_text:
            issues.append(
                ".github/copilot-instructions.md must point to general.instructions.md"
            )
        if "docs/ai/repo-map.md" not in copilot_text:
            issues.append(
                ".github/copilot-instructions.md must point to docs/ai/repo-map.md"
            )
        for path in instruction_files:
            if path not in copilot_text:
                issues.append(f".github/copilot-instructions.md must point to {path}")

    repo_map_text = _read_text(repo_root, "docs/ai/repo-map.md")
    if repo_map_text is None:
        issues.append("missing docs/ai/repo-map.md")
    else:
        if REPO_MAP_SCOPE_MARKER not in repo_map_text:
            issues.append("docs/ai/repo-map.md must declare repo-map-only scope")
        if ".github/copilot-instructions.md" not in repo_map_text:
            issues.append(
                "docs/ai/repo-map.md must point back to .github/copilot-instructions.md"
            )

    docs_index_text = _read_text(repo_root, "docs/README.md")
    if docs_index_text is None:
        issues.append("missing docs/README.md")
    else:
        for path in [
            ".github/copilot-instructions.md",
            "docs/ai/repo-map.md",
            *instruction_files,
        ]:
            if path not in docs_index_text:
                issues.append(f"docs/README.md must list {path}")

    return issues


def _check_frontend_guidance_validation(repo_root: Path) -> list[str]:
    frontend_text = _read_text(
        repo_root, ".github/instructions/frontend.instructions.md"
    )
    if frontend_text is None:
        return ["missing .github/instructions/frontend.instructions.md"]

    issues: list[str] = []
    for line in frontend_text.splitlines():
        if "Validation:" in line and "npm run typecheck" in line:
            issues.append(
                ".github/instructions/frontend.instructions.md must use make ui-typecheck "
                "as the primary frontend validation gate"
            )
    return issues


def _check_firmware_guidance_validation(repo_root: Path) -> list[str]:
    firmware_text = _read_text(
        repo_root, ".github/instructions/firmware.instructions.md"
    )
    if firmware_text is None:
        return ["missing .github/instructions/firmware.instructions.md"]
    workflow_text = _read_text(repo_root, ".github/workflows/ci.yml") or ""
    required_commands = [
        "python tools/firmware/generate_protocol_contract_fixtures.py --check",
        "cd firmware/esp && pio test -e native",
    ]
    issues: list[str] = []
    for command in required_commands:
        workflow_command = command.replace("cd firmware/esp && ", "")
        if workflow_command in workflow_text and command not in firmware_text:
            issues.append(
                ".github/instructions/firmware.instructions.md must mention "
                f"CI firmware validation command: {command}"
            )
    return issues


def _check_guidance_script_references(
    markdown_files: list[str], repo_root: Path
) -> list[str]:
    """Flag repo-local script references in guidance files when the target is absent."""
    issues: list[str] = []
    guidance_files = sorted(
        path
        for path in markdown_files
        if path in {"README.md", "CONTRIBUTING.md", "SECURITY.md"}
        or path.startswith("docs/")
        or path.startswith(".github/ISSUE_TEMPLATE/")
        or path.startswith(".github/instructions/")
        or path == ".github/copilot-instructions.md"
        or path == "AGENTS.md"
        or path.endswith("/AGENTS.md")
    )
    script_re = re.compile(
        r"(?P<path>(?:"
        + "|".join(re.escape(prefix) for prefix in GUIDANCE_SCRIPT_STARTS)
        + r")[A-Za-z0-9._~<>/-]+(?:"
        + "|".join(re.escape(suffix) for suffix in GUIDANCE_SCRIPT_SUFFIXES)
        + r"))"
    )

    for path in guidance_files:
        text = _read_text(repo_root, path)
        if text is None:
            continue
        for match in script_re.finditer(text):
            candidate = match.group("path")
            if "<" in candidate or ">" in candidate:
                continue
            if not (repo_root / candidate).is_file():
                issues.append(
                    f"{path}: missing repo-local script reference: {candidate}"
                )

    return issues


def _check_direct_shell_script_commands(
    markdown_files: list[str], repo_root: Path
) -> list[str]:
    issues: list[str] = []
    for path in sorted(markdown_files):
        text = _read_text(repo_root, path)
        if text is None:
            continue
        for snippet in _markdown_code_snippets(text):
            for match in DIRECT_SHELL_SCRIPT_RE.finditer(snippet):
                candidate = match.group("path")
                script_path = repo_root / candidate
                if not script_path.is_file():
                    issues.append(
                        f"{path}: missing executable script command: {candidate}"
                    )
                elif script_path.stat().st_mode & 0o111 == 0:
                    issues.append(
                        f"{path}: documented script command is not executable: {candidate}"
                    )
    return issues


def _check_backticked_repo_paths(
    markdown_files: list[str], repo_root: Path
) -> list[str]:
    """Flag exact repo-local paths in docs when the target does not exist."""
    issues: list[str] = []
    code_span_re = re.compile(r"`([^`\n]+)`")
    for path in sorted(markdown_files):
        text = _read_text(repo_root, path)
        if text is None:
            continue
        for match in code_span_re.finditer(text):
            candidate = match.group(1).strip()
            if not candidate.startswith(REPO_PATH_PREFIXES):
                continue
            if any(
                token in candidate for token in ("*", "...", "<", ">", "$", " ", "\t")
            ):
                continue
            if ":" in candidate or candidate.startswith(("http://", "https://")):
                continue
            candidate = candidate.split("#", 1)[0].strip("/")
            if not candidate:
                continue
            if candidate in GENERATED_REPO_PATH_REFERENCES:
                continue
            if "/out/" in candidate:
                continue
            if not candidate.endswith("/") and not Path(candidate).suffix:
                continue
            if not (repo_root / candidate).exists():
                issues.append(f"{path}: missing repo-local path reference: {candidate}")

    return issues


def _check_stale_repo_path_references(
    markdown_files: list[str], repo_root: Path
) -> list[str]:
    issues: list[str] = []
    for path in sorted(markdown_files):
        text = _read_text(repo_root, path)
        if text is None:
            continue
        for stale_path, replacement in STALE_REPO_PATH_REFERENCES.items():
            if stale_path in text:
                issues.append(
                    f"{path}: stale repo path reference: {stale_path} "
                    f"(use {replacement})"
                )
    return issues


def _check_design_doc_status(markdown_files: list[str], repo_root: Path) -> list[str]:
    issues: list[str] = []
    for path in sorted(markdown_files):
        if not (path.startswith("docs/designs/") and path.endswith(".md")):
            continue
        text = _read_text(repo_root, path)
        if text is None:
            continue
        if not DESIGN_DOC_STATUS_RE.search(text):
            issues.append(
                f"{path}: design doc must declare Status: Active, Historical, or Superseded"
            )
    return issues


def _check_docs_index_complete(markdown_files: list[str], repo_root: Path) -> list[str]:
    docs_index_text = _read_text(repo_root, "docs/README.md")
    if docs_index_text is None:
        return ["missing docs/README.md"]

    issues: list[str] = []
    for path in sorted(
        path
        for path in markdown_files
        if path.startswith("docs/") and path.endswith(".md")
    ):
        if f"`{path}`" not in docs_index_text:
            issues.append(f"docs/README.md must list {path}")
    return issues


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    all_files = _tracked_files(repo_root)
    markdown_files = [f for f in all_files if f.endswith(".md")]
    docs_files = [f for f in markdown_files if f.startswith("docs/")]
    source_files = [
        f for f in all_files if not any(d in f.split("/") for d in EXCLUDED_DIRS)
    ]

    issues: list[str] = []
    issues.extend(_check_large_code_blocks(docs_files))
    issues.extend(_check_runtime_docs_reading(source_files))
    issues.extend(_check_markdown_links(markdown_files, repo_root))
    issues.extend(_check_ai_guidance_stack(markdown_files, repo_root))
    issues.extend(_check_frontend_guidance_validation(repo_root))
    issues.extend(_check_firmware_guidance_validation(repo_root))
    issues.extend(_check_guidance_script_references(markdown_files, repo_root))
    issues.extend(_check_direct_shell_script_commands(markdown_files, repo_root))
    issues.extend(_check_backticked_repo_paths(markdown_files, repo_root))
    issues.extend(_check_stale_repo_path_references(markdown_files, repo_root))
    issues.extend(_check_design_doc_status(markdown_files, repo_root))
    issues.extend(_check_docs_index_complete(markdown_files, repo_root))
    issues.extend(_check_make_command_targets(markdown_files, repo_root))
    issues.extend(_check_npm_run_scripts(markdown_files, repo_root))
    issues.extend(_check_ci_job_examples(markdown_files, repo_root))

    if issues:
        print(f"❌ {len(issues)} docs issue(s):")
        for issue in issues:
            print(f"   {issue}")
        return 1

    print(
        "✅ No docs misuse, runtime docs access, broken local markdown links, stale commands, missing repo paths, or AI guidance stack drift detected."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
