#!/usr/bin/env python3
"""Docs misuse / wrapper hack detector (R0/R1 compliance).

Checks:
1. No docs files contain large code blocks (>30 lines) that look like
   executable logic rather than examples.
2. No source files read/execute docs content at runtime.

Exit 0 if clean, 1 if violations found.
"""

from __future__ import annotations

import re
import subprocess
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


def _walk_files(repo_root: Path) -> list[str]:
    files: list[str] = []
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(repo_root)
        if any(part in EXCLUDED_DIRS for part in rel.parts):
            continue
        files.append(rel.as_posix())
    return files


def _tracked_files(repo_root: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "--cached"],
            capture_output=True,
            text=True,
            check=True,
        )
        tracked = [line for line in result.stdout.splitlines() if line]
        if tracked:
            return tracked
    except (OSError, subprocess.CalledProcessError):
        pass
    return _walk_files(repo_root)


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


def _check_guidance_script_references(
    markdown_files: list[str], repo_root: Path
) -> list[str]:
    """Flag repo-local script references in guidance files when the target is absent."""
    issues: list[str] = []
    guidance_files = sorted(
        path
        for path in markdown_files
        if path.startswith(".github/instructions/")
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
            if "/out/" in candidate:
                continue
            if not candidate.endswith("/") and not Path(candidate).suffix:
                continue
            if not (repo_root / candidate).exists():
                issues.append(f"{path}: missing repo-local path reference: {candidate}")

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
    issues.extend(_check_guidance_script_references(markdown_files, repo_root))
    issues.extend(_check_backticked_repo_paths(markdown_files, repo_root))

    if issues:
        print(f"❌ {len(issues)} docs issue(s):")
        for issue in issues:
            print(f"   {issue}")
        return 1

    print(
        "✅ No docs misuse, runtime docs access, broken local markdown links, or AI guidance stack drift detected."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
