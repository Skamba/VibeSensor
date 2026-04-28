#!/usr/bin/env python3
"""Shared, explicit changed-path rules for CI job gating."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, fields
from pathlib import PurePosixPath

DOC_FILES = {
    "README.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    ".github/copilot-instructions.md",
}
FULL_STACK_TRIGGER_FILES = {
    "Makefile",
    ".python-version",
    ".nvmrc",
    "docker-compose.yml",
    "docker-compose.dev.yml",
    "apps/server/Dockerfile",
    "apps/server/Dockerfile.e2e",
    "tools/tests/ci_changed_scope.py",
    "tools/tests/ci_path_rules.py",
    "tools/tests/ci_workflow_manifest.py",
    "tools/tests/run_ci_parallel.py",
}
FULL_STACK_TRIGGER_PREFIXES = (".github/",)
FIRMWARE_TRIGGER_PREFIXES = ("firmware/", "tools/firmware/")
FIRMWARE_NATIVE_BACKEND_TRIGGER_FILES = {
    "apps/server/vibesensor/adapters/udp/protocol.py",
    "apps/server/vibesensor/adapters/udp/protocol_validator.py",
}
PYTHON_TOOL_PREFIX = "tools/"
DOCS_LINT_TOOL_FILES = {"tools/dev/docs_lint.py"}
REPO_HYGIENE_TOOL_FILES = {"tools/dev/check_hygiene.py"}
BACKEND_STATIC_GUARD_TOOL_FILES = {"tools/dev/verify_backend_static_guards.py"}
BACKEND_TEST_TOOL_FILES = {"tools/tests/run_backend_parallel.py"}
RELEASE_TRIGGER_FILES = {"tools/tests/run_release_smoke.py", "tools/build_ui_static.py"}
E2E_TRIGGER_FILES = {"tools/tests/run_e2e_parallel.py", "apps/server/Dockerfile.e2e"}
CONTRACT_SYNC_TRIGGER_FILES = {
    "apps/ui/package.json",
    "apps/ui/src/contracts/http_api_schema.json",
    "apps/ui/src/contracts/ws_payload_schema.json",
    "docs/protocol.md",
    "tools/config/generate_contract_reference_doc.py",
    "tools/config/generate_ui_shared_constants.py",
    "tools/config/sync_contract_artifacts.mjs",
    "tools/config/sync_shared_contracts_to_ui.mjs",
}


@dataclass(frozen=True)
class WorkflowJobSelection:
    docs_lint: bool = False
    repo_hygiene: bool = False
    backend_lint: bool = False
    backend_static_guards: bool = False
    backend_preflight: bool = False
    backend_contract_drift: bool = False
    backend_typecheck: bool = False
    frontend_typecheck: bool = False
    ui_smoke: bool = False
    backend_tests: bool = False
    release_smoke: bool = False
    firmware_native_tests: bool = False
    e2e: bool = False

    @classmethod
    def full_stack(cls) -> WorkflowJobSelection:
        return cls(**{field.name: True for field in fields(cls)})

    def github_outputs(self) -> dict[str, str]:
        return {
            f"run_{field.name}": "true" if getattr(self, field.name) else "false"
            for field in fields(self)
        }


def normalize_changed_files(changed_files: Iterable[str]) -> tuple[str, ...]:
    normalized = {
        PurePosixPath(path).as_posix().removeprefix("./")
        for path in changed_files
        if path.strip()
    }
    return tuple(sorted(normalized))


def is_markdown_path(path: str) -> bool:
    normalized = PurePosixPath(path).as_posix()
    return (
        normalized.endswith(".md")
        or normalized in DOC_FILES
        or normalized.startswith("docs/")
    )


def _matches_any(
    path: str, *, files: set[str] | None = None, prefixes: tuple[str, ...] = ()
) -> bool:
    return (files is not None and path in files) or any(
        path.startswith(prefix) for prefix in prefixes
    )


def workflow_job_selection(changed_files: Iterable[str]) -> WorkflowJobSelection:
    normalized = normalize_changed_files(changed_files)
    if not normalized:
        return WorkflowJobSelection.full_stack()

    docs_changed = any(is_markdown_path(path) for path in normalized)
    contract_sync_changed = any(
        path in CONTRACT_SYNC_TRIGGER_FILES for path in normalized
    )
    non_docs_paths = tuple(path for path in normalized if not is_markdown_path(path))
    if not non_docs_paths and not contract_sync_changed:
        return WorkflowJobSelection(docs_lint=True)

    full_stack = any(
        _matches_any(
            path,
            files=FULL_STACK_TRIGGER_FILES,
            prefixes=FULL_STACK_TRIGGER_PREFIXES,
        )
        for path in non_docs_paths
    )
    backend_changed = any(path.startswith("apps/server/") for path in non_docs_paths)
    frontend_changed = any(path.startswith("apps/ui/") for path in non_docs_paths)
    firmware_changed = any(
        any(path.startswith(prefix) for prefix in FIRMWARE_TRIGGER_PREFIXES)
        for path in non_docs_paths
    )
    python_tool_changed = any(
        path.startswith(PYTHON_TOOL_PREFIX) and path.endswith(".py")
        for path in non_docs_paths
    )
    docs_lint_tool_changed = any(
        path in DOCS_LINT_TOOL_FILES for path in non_docs_paths
    )
    repo_hygiene_tool_changed = any(
        path in REPO_HYGIENE_TOOL_FILES for path in non_docs_paths
    )
    backend_static_guard_tool_changed = any(
        path in BACKEND_STATIC_GUARD_TOOL_FILES for path in non_docs_paths
    )
    backend_test_tool_changed = any(
        path in BACKEND_TEST_TOOL_FILES for path in non_docs_paths
    )
    release_tool_changed = any(path in RELEASE_TRIGGER_FILES for path in non_docs_paths)
    e2e_tool_changed = any(path in E2E_TRIGGER_FILES for path in non_docs_paths)

    return WorkflowJobSelection(
        docs_lint=full_stack or docs_changed or docs_lint_tool_changed,
        repo_hygiene=full_stack
        or repo_hygiene_tool_changed
        or backend_changed
        or frontend_changed
        or python_tool_changed
        or contract_sync_changed,
        backend_lint=full_stack or backend_changed or python_tool_changed,
        backend_static_guards=full_stack
        or backend_changed
        or backend_static_guard_tool_changed,
        backend_preflight=full_stack or backend_changed,
        backend_contract_drift=full_stack or backend_changed or contract_sync_changed,
        backend_typecheck=full_stack or backend_changed,
        frontend_typecheck=full_stack or frontend_changed,
        ui_smoke=full_stack or frontend_changed,
        backend_tests=full_stack or backend_changed or backend_test_tool_changed,
        release_smoke=full_stack
        or backend_changed
        or frontend_changed
        or release_tool_changed,
        firmware_native_tests=full_stack
        or firmware_changed
        or any(
            path in FIRMWARE_NATIVE_BACKEND_TRIGGER_FILES for path in non_docs_paths
        ),
        e2e=full_stack or backend_changed or frontend_changed or e2e_tool_changed,
    )
