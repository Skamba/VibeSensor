"""Shared constants and helpers for repository hygiene checks."""

from __future__ import annotations

import importlib.util
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def _load_repo_tooling_support():
    helper_path = ROOT / "tools" / "repo_tooling_support.py"
    spec = importlib.util.spec_from_file_location("repo_tooling_support", helper_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load repo tooling helpers from {helper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_repo_tooling_support = _load_repo_tooling_support()

_UI_BOOTSTRAP_HELPER_WORKFLOW_CMD = "node ../../tools/ui/ensure_ui_bootstrap.mjs"

_UI_DERIVATIVE_SETUP_WORKFLOW_CMD = "npm run setup:generated-contracts"

_UI_MANUAL_CHUNK_PACKAGE_RE = re.compile(r'"/(?!node_modules/)((?:@[^/]+/)?[^/]+)/"')

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

_PY_PATH_HACK_RE = re.compile(
    "|".join((r"sys\.path\.(?:insert|append)\(", "PYTHON" + "PATH="))
)

_BACKEND_TEST_MATRIX_JOB = "backend-tests"

_CI_SCOPE_JOB = "ci-scope"

_FRONTEND_QUALITY_JOB = "frontend-quality"

_FRONTEND_TYPECHECK_JOB = "frontend-typecheck"

_UI_BUILD_ARTIFACT_JOB = "ui-build-artifact"

_BACKEND_QUALITY_JOBS = (
    "backend-lint",
    "repo-hygiene",
    "backend-static-guards",
    "backend-preflight",
    "docs-lint",
    "backend-contract-drift",
)

_CI_SCOPE_ONLY_NEEDS = (_CI_SCOPE_JOB,)

_RELEASE_SMOKE_QUALITY_NEEDS = (
    _CI_SCOPE_JOB,
    *_BACKEND_QUALITY_JOBS,
    "backend-typecheck",
    _FRONTEND_QUALITY_JOB,
    _FRONTEND_TYPECHECK_JOB,
    _UI_BUILD_ARTIFACT_JOB,
)

_UI_SMOKE_NEEDS = (_CI_SCOPE_JOB, _FRONTEND_TYPECHECK_JOB)

_UI_BUILD_ARTIFACT_NEEDS = (_CI_SCOPE_JOB, _FRONTEND_TYPECHECK_JOB)

_BACKEND_TEST_SHARD_COUNT = 5

_BACKEND_TEST_XDIST_WORKERS = "3"

_BACKEND_TEST_SHARD_JOBS = tuple(
    f"backend-tests-{index}" for index in range(1, _BACKEND_TEST_SHARD_COUNT + 1)
)

_BACKEND_SETUP_JOBS = (
    "backend-lint",
    "repo-hygiene",
    "backend-static-guards",
    "backend-preflight",
    "backend-contract-drift",
    "backend-typecheck",
    _BACKEND_TEST_MATRIX_JOB,
    "e2e",
)

_FIRMWARE_INSTALL_JOB = "firmware-native-tests"

_FIRMWARE_NEEDS = (_CI_SCOPE_JOB, *_BACKEND_QUALITY_JOBS)

_LOCAL_PYTHON_SETUP_ACTION = "./.github/actions/setup-python"

_LOCAL_BACKEND_SETUP_ACTION = "./.github/actions/setup-backend"

_DOCKER_NODE_RE = re.compile(r"^FROM node:(\S+) AS ui-build$", re.MULTILINE)

_DOCKER_PYTHON_RE = re.compile(r"^FROM python:(\S+)$", re.MULTILINE)

_UI_SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".mjs"}

_UI_FRONTEND_BOUNDARY_IMPORTERS: dict[str, frozenset[str]] = {
    "apps/ui/src/generated/http_api_contracts.ts": frozenset(
        {"apps/ui/src/api/types.ts"}
    ),
    "apps/ui/src/contracts/ws_payload_types.ts": frozenset(
        {
            "apps/ui/src/server_payload.ts",
            "apps/ui/src/transport/live_models.ts",
            "apps/ui/src/ws.ts",
            "apps/ui/src/ws_payload_validator.ts",
        }
    ),
    "apps/ui/src/contracts/ws_payload_schema.generated.ts": frozenset(
        {"apps/ui/src/ws_payload_validator.ts"}
    ),
}

_UI_OPTIONAL_GENERATED_TARGETS = frozenset(_UI_FRONTEND_BOUNDARY_IMPORTERS)

_RUNTIME_SUPPORT_MATRIX_PATH = ROOT / "docs" / "runtime_support_matrix.md"

_CONTRIBUTING_PATH = ROOT / "CONTRIBUTING.md"

_INSTALL_PI_PATH = ROOT / "apps" / "server" / "scripts" / "install_pi.sh"

_UI_README_PATH = ROOT / "apps" / "ui" / "README.md"

_SERVER_README_PATH = ROOT / "apps" / "server" / "README.md"

_UI_PACKAGE_JSON_PATH = ROOT / "apps" / "ui" / "package.json"

_IMAGE_VALIDATION_PATH = (
    ROOT / "infra" / "pi-image" / "pi-gen" / "lib" / "image_validation.sh"
)

_UI_DERIVATIVE_GENERATED_ARTIFACTS = (
    "apps/ui/src/constants.ts",
    "apps/ui/src/generated/http_api_contracts.ts",
    "apps/ui/src/contracts/ws_payload_schema.generated.ts",
    "apps/ui/src/contracts/ws_payload_types.ts",
)

_NATIVE_RUNTIME_ROW = "Native development, local tooling, and simulator runs"

_GITHUB_ACTIONS_RUNTIME_ROW = "GitHub Actions CI and release builders"

_DOCKER_RUNTIME_ROW = "Docker / container build path"

_PACKAGE_RUNTIME_ROW = "Installable backend package / wheel compatibility"

_MANUAL_PI_RUNTIME_ROW = "Manual Raspberry Pi install and on-device runtime"

_PI_IMAGE_RUNTIME_ROW = "Prebuilt Pi image build"


@dataclass(frozen=True)
class RuntimeSupportMatrixRow:
    environment: str
    python_policy: str
    node_policy: str
    notes: str


@dataclass(frozen=True)
class TextRequirement:
    needle: str
    error_message: str


@dataclass(frozen=True)
class WorkflowStepRequirement:
    error_message: str
    uses: str | None = None
    uses_prefix: str | None = None
    run: str | None = None
    working_directory: str | None = None
    step_id: str | None = None
    forbidden: bool = False


@dataclass(frozen=True)
class ListCheckSpec:
    runner: Callable[[], list[str]]
    failure_heading: str
    success_message: str


_UI_ALLOWED_RAW_HTML_PREFIX = "apps/ui/src/app/views/"

_UI_DOM_REGISTRY_PATH = ROOT / "apps" / "ui" / "src" / "app" / "ui_dom_registry.ts"

_UI_DOM_REGISTRY_TOKENS = ("UiDomRegistry", "ui_dom_registry")

_UI_LEGACY_TEST_DOM_TOKENS = (
    "createPanel(",
    "installFakeDomGlobals(",
    "FakeElement",
    "FakeHTMLElement",
)

_UI_COMPONENT_USE_COMPUTED_TOKEN = "useComputed"

_OVERSIZED_TEST_ALLOWLIST_PATH = ROOT / "tools" / "dev" / "oversized_test_allowlist.yml"

_OVERSIZED_TEST_DEFAULT_LIMIT = 700

_OVERSIZED_TEST_DEFAULT_REPORT_LIMIT = 10

_OVERSIZED_TEST_UI_SUFFIXES = {".ts", ".tsx", ".js", ".jsx"}

_OVERSIZED_TEST_IGNORED_PARTS = {"snapshots", "test-results"}

_TEST_INVENTORY_ALLOWLIST_PATH = ROOT / "tools" / "dev" / "test_inventory_allowlist.yml"

_TEST_MARKER_POLICY_ALLOWLIST_PATH = (
    ROOT / "tools" / "dev" / "test_marker_policy_allowlist.yml"
)

_UI_ROOT = ROOT / "apps" / "ui"

_UI_TESTS_DIR = _UI_ROOT / "tests"

_UI_VITEST_CONFIG = _UI_ROOT / "vitest.config.ts"

_UI_PLAYWRIGHT_SMOKE_CONFIG = _UI_ROOT / "playwright.smoke.config.ts"

_UI_PLAYWRIGHT_REGRESSION_CONFIG = _UI_ROOT / "playwright.regression.config.ts"

_UI_PLAYWRIGHT_MOCK_SMOKE_CONFIG = _UI_ROOT / "playwright.smoke.msw.config.ts"

_UI_PLAYWRIGHT_VISUAL_CONFIG = _UI_ROOT / "playwright.config.ts"

_MARKER_POLICY_NODE_MODULE = "__module__"

_MARKER_POLICY_MARKERS = ("smoke", "e2e", "long_sim", "benchmark")

_IMPORT_FROM_RE = re.compile(r"""\bfrom\s+["']([^"']+)["']""")

_SIDE_EFFECT_IMPORT_RE = re.compile(r"""\bimport\s+["']([^"']+)["']""")

_EMPTY_INNERHTML_ASSIGNMENT_RE = re.compile(
    r"""\.innerHTML\s*=\s*(?:""|''|`{2})\s*;?"""
)


def _load_yaml_mapping(path: Path) -> dict[str, object]:
    loaded = yaml.safe_load(path.read_text())
    return loaded if isinstance(loaded, dict) else {}


def _read_required_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


__all__ = [name for name in globals() if not name.startswith("__")]
