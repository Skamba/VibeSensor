"""Repository hygiene checks: repo sync, boundary guardrails, and local/CI drift."""

from __future__ import annotations

import importlib.util
import re
import shlex
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

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


_MIRRORED_UI_INSTALL_JOBS = ("frontend-typecheck", "ui-smoke")
_BACKEND_TEST_SHARD_JOBS = (
    "backend-tests-1",
    "backend-tests-2",
    "backend-tests-3",
    "backend-tests-4",
    "backend-tests-5",
)
_MIRRORED_BACKEND_INSTALL_JOBS = (
    "backend-quality",
    "backend-typecheck",
    *_BACKEND_TEST_SHARD_JOBS,
    "e2e",
)
_FIRMWARE_INSTALL_JOB = "firmware-native-tests"
_CI_LITE_EXCLUDED_JOBS = ("e2e",)
_LOCAL_PYTHON_SETUP_ACTION = "./.github/actions/setup-python"
_LOCAL_BACKEND_SETUP_ACTION = "./.github/actions/setup-backend"
_DOCKER_NODE_RE = re.compile(r"^FROM node:(\S+) AS ui-build$", re.MULTILINE)
_DOCKER_PYTHON_RE = re.compile(r"^FROM python:(\S+)$", re.MULTILINE)
_ACTION_INPUT_EQ_RE = re.compile(
    r"^\${{\s*inputs\.([A-Za-z0-9_-]+)\s*==\s*'([^']+)'\s*}}$"
)
_UI_SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".mjs"}
_UI_FRONTEND_BOUNDARY_IMPORTERS: dict[str, frozenset[str]] = {
    "apps/ui/src/generated/http_api_contracts.ts": frozenset(
        {"apps/ui/src/api/types.ts"}
    ),
    "apps/ui/src/api/types.ts": frozenset({"apps/ui/src/transport/http_models.ts"}),
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

_RUNTIME_SUPPORT_MATRIX_PATH = ROOT / "docs" / "runtime_support_matrix.md"
_CONTRIBUTING_PATH = ROOT / "CONTRIBUTING.md"
_INSTALL_PI_PATH = ROOT / "apps" / "server" / "scripts" / "install_pi.sh"
_IMAGE_VALIDATION_PATH = (
    ROOT / "infra" / "pi-image" / "pi-gen" / "lib" / "image_validation.sh"
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


_UI_ALLOWED_RAW_HTML_PREFIX = "apps/ui/src/app/views/"
_UI_DOM_REGISTRY_PATH = ROOT / "apps" / "ui" / "src" / "app" / "ui_dom_registry.ts"
_UI_DOM_REGISTRY_TOKENS = ("UiDomRegistry", "ui_dom_registry")
_IMPORT_FROM_RE = re.compile(r"""\bfrom\s+["']([^"']+)["']""")
_SIDE_EFFECT_IMPORT_RE = re.compile(r"""\bimport\s+["']([^"']+)["']""")
_EMPTY_INNERHTML_ASSIGNMENT_RE = re.compile(
    r"""\.innerHTML\s*=\s*(?:""|''|`{2})\s*;?"""
)


def _load_yaml_mapping(path: Path) -> dict[str, object]:
    loaded = yaml.safe_load(path.read_text())
    return loaded if isinstance(loaded, dict) else {}


def _load_ci_workflow() -> dict[str, object]:
    return _load_yaml_mapping(ROOT / ".github" / "workflows" / "ci.yml")


def _load_action_steps(path: Path) -> list[object]:
    action = _load_yaml_mapping(path)
    runs = action.get("runs")
    if not isinstance(runs, Mapping):
        return []
    steps = runs.get("steps")
    return steps if isinstance(steps, list) else []


def _load_ci_parallel_module():
    module_path = ROOT / "tools" / "tests" / "run_ci_parallel.py"
    spec = importlib.util.spec_from_file_location("ci_parallel_local", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _read_required_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _load_runtime_support_matrix_rows() -> dict[str, RuntimeSupportMatrixRow]:
    rows: dict[str, RuntimeSupportMatrixRow] = {}
    in_table = False
    for raw_line in _RUNTIME_SUPPORT_MATRIX_PATH.read_text(
        encoding="utf-8"
    ).splitlines():
        line = raw_line.strip()
        if (
            line
            == "| Environment / path | Supported Python policy | Supported Node policy | Current source-of-truth files and notes |"
        ):
            in_table = True
            continue
        if not in_table:
            continue
        if not line.startswith("|"):
            if rows:
                break
            continue
        if line.startswith("|---"):
            continue
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if len(cells) != 4:
            continue
        row = RuntimeSupportMatrixRow(
            environment=cells[0],
            python_policy=cells[1],
            node_policy=cells[2],
            notes=cells[3],
        )
        rows[row.environment] = row
    return rows


def _require_runtime_support_row(
    rows: Mapping[str, RuntimeSupportMatrixRow], environment: str, errors: list[str]
) -> RuntimeSupportMatrixRow | None:
    row = rows.get(environment)
    if row is None:
        errors.append(
            "docs/runtime_support_matrix.md must include the "
            f"{environment!r} support-matrix row."
        )
    return row


def _matrix_row_mentions(
    row: RuntimeSupportMatrixRow, expected: str, description: str, errors: list[str]
) -> None:
    if expected not in (row.python_policy + row.node_policy + row.notes):
        errors.append(
            "docs/runtime_support_matrix.md "
            f"{row.environment!r} row must mention {description}."
        )


def _ui_source_files() -> list[Path]:
    return [
        path
        for path in _git_tracked_files()
        if path.is_file()
        and path.suffix in _UI_SOURCE_SUFFIXES
        and path.is_relative_to(ROOT / "apps" / "ui" / "src")
    ]


def _extract_import_specifiers(source_text: str) -> list[str]:
    specifiers = [
        *(_IMPORT_FROM_RE.findall(source_text)),
        *(_SIDE_EFFECT_IMPORT_RE.findall(source_text)),
    ]
    return list(dict.fromkeys(specifiers))


def _resolve_ui_local_import(source_path: Path, specifier: str) -> Path | None:
    if not specifier.startswith("."):
        return None
    base = (source_path.parent / specifier).resolve()
    candidates = [base]
    if not base.suffix:
        candidates.extend(base.with_suffix(ext) for ext in sorted(_UI_SOURCE_SUFFIXES))
        candidates.extend(base / f"index{ext}" for ext in sorted(_UI_SOURCE_SUFFIXES))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _ui_boundary_import_allowed(importer_rel: str, target_rel: str) -> bool:
    if target_rel == "apps/ui/src/api/types.ts":
        return importer_rel == "apps/ui/src/transport/http_models.ts" or (
            importer_rel.startswith("apps/ui/src/api/") and importer_rel != target_rel
        )
    allowed_importers = _UI_FRONTEND_BOUNDARY_IMPORTERS.get(target_rel)
    return allowed_importers is None or importer_rel in allowed_importers


def _ui_boundary_allowed_description(target_rel: str) -> str:
    if target_rel == "apps/ui/src/api/types.ts":
        return "apps/ui/src/api/*.ts and apps/ui/src/transport/http_models.ts"
    allowed_importers = _UI_FRONTEND_BOUNDARY_IMPORTERS.get(target_rel)
    return (
        ", ".join(sorted(allowed_importers))
        if allowed_importers is not None
        else "approved transport boundary files"
    )


def check_frontend_generated_contract_boundaries() -> list[str]:
    errors: list[str] = []
    for path in _ui_source_files():
        rel = str(path.relative_to(ROOT))
        text = path.read_text(encoding="utf-8")
        for specifier in _extract_import_specifiers(text):
            resolved = _resolve_ui_local_import(path, specifier)
            if resolved is None:
                continue
            resolved_rel = str(resolved.relative_to(ROOT))
            if _ui_boundary_import_allowed(rel, resolved_rel):
                continue
            errors.append(
                f"{rel} must not import {resolved_rel}; keep generated transport contracts behind "
                f"{_ui_boundary_allowed_description(resolved_rel)}."
            )
    return errors


def check_frontend_raw_html_boundaries() -> list[str]:
    errors: list[str] = []
    for path in _ui_source_files():
        rel = str(path.relative_to(ROOT))
        if rel.startswith(_UI_ALLOWED_RAW_HTML_PREFIX):
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "insertAdjacentHTML(" in line:
                errors.append(
                    f"{rel}:{lineno} uses insertAdjacentHTML outside app/views/**; "
                    "move the markup into a view helper or DOM builder."
                )
            if "createContextualFragment(" in line:
                errors.append(
                    f"{rel}:{lineno} uses createContextualFragment outside app/views/**; "
                    "move the markup into a view helper or DOM builder."
                )
            if ".innerHTML" not in line or "=" not in line:
                continue
            if _EMPTY_INNERHTML_ASSIGNMENT_RE.search(line):
                continue
            errors.append(
                f"{rel}:{lineno} uses innerHTML outside app/views/**; "
                "move the markup into a view helper or DOM builder."
            )
    return errors


def check_frontend_dom_registry_guardrails() -> list[str]:
    errors: list[str] = []
    if _UI_DOM_REGISTRY_PATH.exists():
        errors.append(
            "apps/ui/src/app/ui_dom_registry.ts must stay deleted; "
            "DOM lookup belongs in app/dom/* locators plus ui_runtime_dom.ts."
        )
    for path in _ui_source_files():
        rel = str(path.relative_to(ROOT))
        if not rel.startswith("apps/ui/src/app/"):
            continue
        text = path.read_text(encoding="utf-8")
        for token in _UI_DOM_REGISTRY_TOKENS:
            if token in text:
                errors.append(
                    f"{rel} references {token!r}; keep page-wide DOM registries out of app/** and "
                    "use feature-scoped locators instead."
                )
                break
    return errors


def _makefile_job_list(var_name: str) -> list[str]:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(var_name)}\s*[:+?]?=\s*(.+)$", text, re.MULTILINE)
    if match is None:
        return []
    tokens = shlex.split(match.group(1))
    jobs: list[str] = []
    index = 0
    while index < len(tokens):
        if tokens[index] != "--job" or index + 1 >= len(tokens):
            return []
        jobs.append(tokens[index + 1])
        index += 2
    return jobs


def _load_server_pyproject() -> dict[str, object]:
    return tomllib.loads((ROOT / "apps" / "server" / "pyproject.toml").read_text())


def _docker_base_tag(pattern: re.Pattern[str], dockerfile_text: str) -> str | None:
    match = pattern.search(dockerfile_text)
    return match.group(1) if match else None


def _version_core(image_tag: str) -> str:
    return image_tag.split("-", 1)[0]


def _major_minor(version: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"\s*(\d+)\.(\d+)(?:\.\d+)?\s*", version)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def _requires_python_floor(spec: str) -> str | None:
    match = re.fullmatch(r"\s*>=\s*(\d+\.\d+)(?:\.\d+)?\s*", spec)
    if match is None:
        return None
    return match.group(1)


def _ruff_target_for_python(version: str) -> str:
    major, minor = version.split(".")
    return f"py{major}{minor}"


def _validate_server_dockerfile(
    *,
    path: Path,
    label: str,
    expected_python: str,
    expected_node: str | None,
    require_ui_stage: bool,
) -> list[str]:
    errors: list[str] = []
    if not path.exists():
        errors.append(f"Missing {label} at {path.relative_to(ROOT)}.")
        return errors

    dockerfile_text = path.read_text(encoding="utf-8")

    docker_python = _docker_base_tag(_DOCKER_PYTHON_RE, dockerfile_text)
    if docker_python is None:
        errors.append(f"{label} is missing the runtime python base image line.")
    elif _version_core(docker_python) != expected_python:
        errors.append(
            f"{label} runtime python tag {docker_python!r} does not match .python-version "
            f"{expected_python!r}."
        )

    docker_node = _docker_base_tag(_DOCKER_NODE_RE, dockerfile_text)
    if require_ui_stage:
        if docker_node is None:
            errors.append(f"{label} is missing the UI node base image line.")
        elif expected_node is not None and _version_core(docker_node) != expected_node:
            errors.append(
                f"{label} UI node tag {docker_node!r} does not match .nvmrc {expected_node!r}."
            )
    elif docker_node is not None:
        errors.append(
            f"{label} must stay backend-only and must not include a ui-build stage."
        )

    if '.get("optional-dependencies", {}).get("esp"' in dockerfile_text:
        errors.append(f"{label} must not install the optional esp dependency group.")
    if "tomllib" in dockerfile_text or "subprocess.check_call" in dockerfile_text:
        errors.append(
            f"{label} must not parse pyproject.toml inline; let pip resolve /app/apps/server directly."
        )
    if "--no-deps /app/apps/server" in dockerfile_text:
        errors.append(f"{label} must not install /app/apps/server with --no-deps.")
    if "python -m pip install --no-cache-dir /app/apps/server" not in dockerfile_text:
        errors.append(f"{label} must install /app/apps/server directly with pip.")

    if not require_ui_stage and (
        "npm ci" in dockerfile_text
        or "npm run build" in dockerfile_text
        or "COPY --from=ui-build" in dockerfile_text
    ):
        errors.append(
            f"{label} must stay backend-only and must not build or copy UI assets."
        )
    if not require_ui_stage and "VIBESENSOR_SERVE_STATIC=0" not in dockerfile_text:
        errors.append(f"{label} must disable static UI serving.")

    return errors


def _validate_ui_dev_compose_node_image(expected_node: str) -> list[str]:
    compose_path = ROOT / "docker-compose.dev.yml"
    if not compose_path.exists():
        return ["Missing Docker dev override at docker-compose.dev.yml."]

    compose = _load_yaml_mapping(compose_path)
    services = compose.get("services")
    if not isinstance(services, Mapping):
        return ["docker-compose.dev.yml is missing its services mapping."]
    ui_service = services.get("vibesensor-ui-dev")
    if not isinstance(ui_service, Mapping):
        return ["docker-compose.dev.yml is missing the vibesensor-ui-dev service."]
    image = ui_service.get("image")
    if not isinstance(image, str):
        return ["docker-compose.dev.yml:vibesensor-ui-dev must declare a node image."]

    match = re.fullmatch(r"node:(\S+)", image.strip())
    if match is None:
        return ["docker-compose.dev.yml:vibesensor-ui-dev must use a node:<tag> image."]
    actual_node = match.group(1)
    if _version_core(actual_node) != expected_node:
        return [
            "docker-compose.dev.yml:vibesensor-ui-dev image "
            f"{actual_node!r} does not match .nvmrc {expected_node!r}."
        ]
    return []


def _project_dependency_spec(requirement_name: str) -> str | None:
    pyproject = _load_server_pyproject()
    project = pyproject.get("project")
    if not isinstance(project, Mapping):
        return None
    dependencies = project.get("dependencies")
    if not isinstance(dependencies, list):
        return None
    prefix = f"{requirement_name}>="
    for dependency in dependencies:
        if isinstance(dependency, str) and dependency.startswith(prefix):
            return dependency
    return None


def _build_system_requirement_spec(requirement_name: str) -> str | None:
    pyproject = _load_server_pyproject()
    build_system = pyproject.get("build-system")
    if not isinstance(build_system, Mapping):
        return None
    requires = build_system.get("requires")
    if not isinstance(requires, list):
        return None
    prefix = f"{requirement_name}>="
    for requirement in requires:
        if isinstance(requirement, str) and requirement.startswith(prefix):
            return requirement
    return None


def _platformio_package_pin(package_name: str) -> str | None:
    platformio_path = ROOT / "firmware" / "esp" / "platformio.ini"
    if not platformio_path.exists():
        return None
    in_platform_packages = False
    for raw_line in platformio_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_platform_packages = False
            continue
        if line.startswith("platform_packages"):
            in_platform_packages = True
            _, _, value = line.partition("=")
            candidate = value.strip()
            if candidate.startswith(f"{package_name}@"):
                return candidate.split("@", 1)[1].strip()
            continue
        if in_platform_packages:
            if "=" in raw_line and not raw_line.startswith((" ", "\t")):
                in_platform_packages = False
                continue
            if line.startswith(f"{package_name}@"):
                return line.split("@", 1)[1].strip()
    return None


def _lower_bound_major(requirement_spec: str) -> int | None:
    match = re.search(r">=?\s*([0-9]+)", requirement_spec)
    return int(match.group(1)) if match else None


def _upper_bound_major(requirement_spec: str) -> int | None:
    match = re.search(r"<\s*([0-9]+)", requirement_spec)
    return int(match.group(1)) if match else None


def _normalize_python_token(token: str) -> str:
    stripped = token.strip("\"'")
    if Path(stripped).name.startswith("python") or "python-path" in stripped:
        return "python"
    return token


def _normalize_tokenized_command(tokens: list[str]) -> str:
    if not tokens:
        return ""
    normalized = list(tokens)
    normalized[0] = _normalize_python_token(normalized[0])
    return shlex.join(normalized)


def _normalize_shell_command(command: str) -> str:
    tokens = shlex.split(command)
    if "&&" not in tokens:
        return _normalize_tokenized_command(tokens)

    parts: list[str] = []
    current: list[str] = []
    for token in tokens:
        if token == "&&":
            if current:
                parts.append(_normalize_tokenized_command(current))
                current = []
            continue
        current.append(token)
    if current:
        parts.append(_normalize_tokenized_command(current))
    return " && ".join(parts)


def _normalize_env(env: Mapping[str, object] | None) -> str:
    if not env:
        return ""
    parts = [f"{key}={env[key]}" for key in sorted(env)]
    return f"env {' '.join(parts)} "


def _normalize_ci_step_commands(step: Mapping[str, object]) -> list[str]:
    run = step.get("run")
    if not isinstance(run, str):
        return []
    working_directory = step.get("working-directory")
    cwd_prefix = ""
    if isinstance(working_directory, str) and working_directory:
        cwd_prefix = f"cd {working_directory} && "
    env_prefix = _normalize_env(
        step.get("env") if isinstance(step.get("env"), Mapping) else None
    )
    lines = [raw_line.strip() for raw_line in run.splitlines() if raw_line.strip()]
    line_cwd_prefix = ""
    if lines and lines[0].startswith("cd ") and "&&" not in lines[0] and len(lines) > 1:
        line_cwd_prefix = f"{_normalize_shell_command(lines[0])} && "
        lines = lines[1:]

    commands: list[str] = []
    for line in lines:
        commands.append(
            f"{cwd_prefix}{line_cwd_prefix}{env_prefix}{_normalize_shell_command(line)}"
        )
    return commands


def _local_action_file(action_ref: str) -> Path | None:
    if not action_ref.startswith("./"):
        return None
    action_file = ROOT / action_ref.removeprefix("./") / "action.yml"
    return action_file if action_file.exists() else None


def _resolved_action_inputs(
    action: Mapping[str, object], raw_with: Mapping[str, object] | None
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    raw_inputs = action.get("inputs")
    if isinstance(raw_inputs, Mapping):
        for input_name, input_spec in raw_inputs.items():
            if not isinstance(input_name, str):
                continue
            default = ""
            if isinstance(input_spec, Mapping):
                raw_default = input_spec.get("default")
                if raw_default is not None:
                    default = str(raw_default)
            resolved[input_name] = default
    if raw_with is not None:
        for input_name, value in raw_with.items():
            if isinstance(input_name, str) and value is not None:
                resolved[input_name] = str(value)
    return resolved


def _action_step_enabled(step: Mapping[str, object], inputs: Mapping[str, str]) -> bool:
    raw_if = step.get("if")
    if not isinstance(raw_if, str):
        return True
    match = _ACTION_INPUT_EQ_RE.fullmatch(raw_if.strip())
    if match is None:
        return True
    input_name, expected_value = match.groups()
    return inputs.get(input_name, "") == expected_value


def _normalized_ci_steps(raw_step: Mapping[str, object]) -> list[dict[str, object]]:
    run = raw_step.get("run")
    if isinstance(run, str):
        return [
            {
                "name": raw_step.get("name", ""),
                "commands": _normalize_ci_step_commands(raw_step),
            }
        ]

    uses = raw_step.get("uses")
    if not isinstance(uses, str):
        return []
    action_file = _local_action_file(uses)
    if action_file is None:
        return []
    action = _load_yaml_mapping(action_file)
    runs = action.get("runs")
    if not isinstance(runs, Mapping):
        return []
    raw_steps = runs.get("steps")
    if not isinstance(raw_steps, list):
        return []
    raw_with = raw_step.get("with")
    action_inputs = _resolved_action_inputs(
        action, raw_with if isinstance(raw_with, Mapping) else None
    )
    normalized_steps: list[dict[str, object]] = []
    for action_step in raw_steps:
        if not isinstance(action_step, Mapping):
            continue
        if not _action_step_enabled(action_step, action_inputs):
            continue
        normalized_steps.extend(_normalized_ci_steps(action_step))
    return normalized_steps


def _ci_run_steps_by_job() -> dict[str, list[dict[str, object]]]:
    workflow = _load_ci_workflow()
    jobs = workflow.get("jobs")
    if not isinstance(jobs, Mapping):
        return {}

    result: dict[str, list[dict[str, object]]] = {}
    for job_name, job_body in jobs.items():
        if not isinstance(job_name, str) or not isinstance(job_body, Mapping):
            continue
        raw_steps = job_body.get("steps")
        if not isinstance(raw_steps, list):
            continue
        normalized_steps: list[dict[str, object]] = []
        for raw_step in raw_steps:
            if not isinstance(raw_step, Mapping):
                continue
            normalized_steps.extend(_normalized_ci_steps(raw_step))
        result[job_name] = normalized_steps
    return result


def _normalize_local_step(step) -> str:
    cwd_prefix = ""
    if step.cwd != ROOT:
        cwd_prefix = f"cd {step.cwd.relative_to(ROOT).as_posix()} && "
    env_prefix = _normalize_env(step.env)
    return f"{cwd_prefix}{env_prefix}{_normalize_tokenized_command(step.cmd)}"


def _local_runner_commands() -> tuple[dict[str, list[str]], list[str], list[str]]:
    ci_parallel = _load_ci_parallel_module()
    common_bootstrap = [
        _normalize_local_step(step)
        for step in ci_parallel._bootstrap_steps(  # type: ignore[attr-defined]
            sys.executable,
            True,
            include_platformio=False,
        )
    ]
    firmware_bootstrap = [
        _normalize_local_step(step)
        for step in ci_parallel._bootstrap_steps(  # type: ignore[attr-defined]
            sys.executable,
            True,
            include_platformio=True,
        )
    ]
    job_steps = {
        name: [_normalize_local_step(step) for step in steps]
        for name, steps in ci_parallel._job_steps(sys.executable).items()  # type: ignore[attr-defined]
    }
    return job_steps, common_bootstrap, firmware_bootstrap


def _pip_install_markers(commands: list[str]) -> set[str]:
    markers: set[str] = set()
    for command in commands:
        tokens = shlex.split(command)
        if len(tokens) < 5:
            continue
        if tokens[1:4] != ["-m", "pip", "install"]:
            continue
        args = tokens[4:]
        i = 0
        while i < len(args):
            token = args[i]
            if token == "--upgrade" and i + 1 < len(args):
                markers.add(f"{token} {args[i + 1]}")
                i += 2
                continue
            if token == "-e" and i + 1 < len(args):
                markers.add(f"{token} {args[i + 1]}")
                i += 2
                continue
            if not token.startswith("-"):
                markers.add(token)
            i += 1
    return markers


def _ci_commands_named(steps: list[dict[str, object]], names: set[str]) -> list[str]:
    collected: list[str] = []
    for step in steps:
        if step.get("name") not in names:
            continue
        commands = step.get("commands")
        if isinstance(commands, list):
            collected.extend(str(command) for command in commands)
    return collected


def check_ci_job_sync() -> list[str]:
    """Verify run_ci_parallel.py job names match ci.yml job names."""
    ci_yml = ROOT / ".github" / "workflows" / "ci.yml"
    parallel_py = ROOT / "tools" / "tests" / "run_ci_parallel.py"
    errors: list[str] = []
    if not ci_yml.exists() or not parallel_py.exists():
        return errors

    ci_jobs = set(_ci_run_steps_by_job())
    parallel_jobs = set(_local_runner_commands()[0])

    only_ci = ci_jobs - parallel_jobs
    only_parallel = parallel_jobs - ci_jobs
    if only_ci:
        errors.append(f"CI jobs not mirrored in run_ci_parallel.py: {sorted(only_ci)}")
    if only_parallel:
        errors.append(f"run_ci_parallel.py jobs not in ci.yml: {sorted(only_parallel)}")
    return errors


def check_ci_command_sync() -> list[str]:
    """Verify mirrored CI run commands stay aligned with run_ci_parallel.py."""
    ci_steps = _ci_run_steps_by_job()
    local_jobs, common_bootstrap, firmware_bootstrap = _local_runner_commands()
    errors: list[str] = []

    common_backend_markers = _pip_install_markers(common_bootstrap[:2])
    for job_name in _MIRRORED_BACKEND_INSTALL_JOBS:
        install_commands = _ci_commands_named(
            ci_steps.get(job_name, []), {"Install dependencies"}
        )
        if _pip_install_markers(install_commands) != common_backend_markers:
            errors.append(
                f"{job_name} install commands drifted from local bootstrap: "
                f"ci={install_commands!r} local={common_bootstrap[:2]!r}"
            )

    ui_bootstrap_commands = common_bootstrap[2:]
    for job_name in _MIRRORED_UI_INSTALL_JOBS:
        install_commands = _ci_commands_named(
            ci_steps.get(job_name, []), {"Install UI dependencies"}
        )
        if install_commands != ui_bootstrap_commands:
            errors.append(
                f"{job_name} UI install commands drifted from local bootstrap: "
                f"ci={install_commands!r} local={ui_bootstrap_commands!r}"
            )

    firmware_install_commands = _ci_commands_named(
        ci_steps.get(_FIRMWARE_INSTALL_JOB, []),
        {"Install dependencies", "Install PlatformIO dependencies"},
    )
    if _pip_install_markers(firmware_install_commands) != _pip_install_markers(
        firmware_bootstrap[:3]
    ):
        errors.append(
            f"{_FIRMWARE_INSTALL_JOB} install commands drifted from local bootstrap: "
            f"ci={firmware_install_commands!r} local={firmware_bootstrap[:3]!r}"
        )

    install_step_names = {
        "Install dependencies",
        "Install PlatformIO dependencies",
        "Install UI dependencies",
    }
    for job_name, steps in ci_steps.items():
        expected_commands: list[str] = []
        for step in steps:
            if step.get("name") in install_step_names:
                continue
            commands = step.get("commands")
            if isinstance(commands, list):
                expected_commands.extend(str(command) for command in commands)
        local_commands = local_jobs.get(job_name, [])
        if expected_commands != local_commands:
            errors.append(
                f"{job_name} run commands drifted from run_ci_parallel.py: "
                f"ci={expected_commands!r} local={local_commands!r}"
            )

    return errors


def check_ci_lite_job_sync() -> list[str]:
    """Verify Makefile CI_LITE_JOBS tracks the non-Docker CI job subset."""
    ci_jobs = list(_ci_run_steps_by_job())
    expected = [
        job_name for job_name in ci_jobs if job_name not in _CI_LITE_EXCLUDED_JOBS
    ]
    actual = _makefile_job_list("CI_LITE_JOBS")
    if not actual:
        return ["Makefile CI_LITE_JOBS is missing or unparsable."]
    if actual == expected:
        return []
    return [
        "Makefile CI_LITE_JOBS drifted from the non-Docker CI subset: "
        f"expected={expected!r} actual={actual!r}"
    ]


def check_docker_ci_dependency_hygiene() -> list[str]:
    errors: list[str] = []

    expected_python = _read_required_text(ROOT / ".python-version")
    expected_node = _read_required_text(ROOT / ".nvmrc")
    errors.extend(
        _validate_server_dockerfile(
            path=ROOT / "apps" / "server" / "Dockerfile",
            label="Production Dockerfile",
            expected_python=expected_python,
            expected_node=expected_node,
            require_ui_stage=True,
        )
    )
    errors.extend(
        _validate_server_dockerfile(
            path=ROOT / "apps" / "server" / "Dockerfile.e2e",
            label="E2E Dockerfile",
            expected_python=expected_python,
            expected_node=None,
            require_ui_stage=False,
        )
    )
    errors.extend(_validate_ui_dev_compose_node_image(expected_node))

    workflow = _load_ci_workflow()
    jobs = workflow.get("jobs")
    if not isinstance(jobs, Mapping):
        errors.append("CI workflow is missing its jobs mapping.")
        return errors

    python_action_file = ROOT / ".github" / "actions" / "setup-python" / "action.yml"
    if not python_action_file.exists():
        errors.append(
            "Missing shared GitHub Actions Python setup action at .github/actions/setup-python/action.yml."
        )
    else:
        python_action_steps = _load_action_steps(python_action_file)
        setup_step = next(
            (
                step
                for step in python_action_steps
                if isinstance(step, Mapping)
                and isinstance(step.get("uses"), str)
                and step["uses"].startswith("actions/setup-python@")
            ),
            None,
        )
        if setup_step is None:
            errors.append(
                ".github/actions/setup-python/action.yml must wrap actions/setup-python."
            )
        else:
            uses = setup_step.get("uses")
            if uses != "actions/setup-python@v6":
                errors.append(
                    ".github/actions/setup-python/action.yml must pin actions/setup-python@v6."
                )
            raw_with = setup_step.get("with")
            if not isinstance(raw_with, Mapping):
                errors.append(
                    ".github/actions/setup-python/action.yml must configure python-version-file and pip caching."
                )
            else:
                if raw_with.get("python-version-file") != ".python-version":
                    errors.append(
                        ".github/actions/setup-python/action.yml must resolve Python from .python-version."
                    )
                if raw_with.get("cache") != "pip":
                    errors.append(
                        ".github/actions/setup-python/action.yml must enable pip caching."
                    )
                if (
                    raw_with.get("cache-dependency-path")
                    != "apps/server/pyproject.toml"
                ):
                    errors.append(
                        ".github/actions/setup-python/action.yml must cache against apps/server/pyproject.toml."
                    )

    action_file = ROOT / ".github" / "actions" / "setup-backend" / "action.yml"
    if not action_file.exists():
        errors.append(
            "Missing shared backend setup composite action at .github/actions/setup-backend/action.yml."
        )
    else:
        backend_action_steps = _load_action_steps(action_file)
        if not any(
            isinstance(step, Mapping) and step.get("uses") == _LOCAL_PYTHON_SETUP_ACTION
            for step in backend_action_steps
        ):
            errors.append(
                ".github/actions/setup-backend/action.yml must delegate Python setup to "
                f"{_LOCAL_PYTHON_SETUP_ACTION}."
            )
        if any(
            isinstance(step, Mapping)
            and isinstance(step.get("uses"), str)
            and step["uses"].startswith("actions/setup-python@")
            for step in backend_action_steps
        ):
            errors.append(
                ".github/actions/setup-backend/action.yml must not call actions/setup-python directly."
            )

    for job_name in (*_MIRRORED_BACKEND_INSTALL_JOBS, _FIRMWARE_INSTALL_JOB):
        raw_job = jobs.get(job_name)
        if not isinstance(raw_job, Mapping):
            continue
        raw_steps = raw_job.get("steps")
        if not isinstance(raw_steps, list):
            continue
        setup_step = next(
            (
                step
                for step in raw_steps
                if isinstance(step, Mapping)
                and step.get("uses") == _LOCAL_BACKEND_SETUP_ACTION
            ),
            None,
        )
        if setup_step is None:
            errors.append(
                f"{job_name} must use {_LOCAL_BACKEND_SETUP_ACTION} for shared backend setup."
            )
            continue
        if job_name == _FIRMWARE_INSTALL_JOB:
            raw_with = setup_step.get("with")
            include_platformio = ""
            if isinstance(raw_with, Mapping):
                raw_value = raw_with.get("include-platformio")
                if raw_value is not None:
                    include_platformio = str(raw_value)
            if include_platformio != "true":
                errors.append(
                    "firmware-native-tests must enable include-platformio on the shared backend setup action."
                )

    workflow_dir = ROOT / ".github" / "workflows"
    for workflow_path in sorted(workflow_dir.glob("*.yml")):
        workflow = _load_yaml_mapping(workflow_path)
        workflow_jobs = workflow.get("jobs")
        if not isinstance(workflow_jobs, Mapping):
            continue
        rel_workflow_path = workflow_path.relative_to(ROOT)
        for job_name, raw_job in workflow_jobs.items():
            if not isinstance(raw_job, Mapping):
                continue
            raw_steps = raw_job.get("steps")
            if not isinstance(raw_steps, list):
                continue
            for step in raw_steps:
                if not isinstance(step, Mapping):
                    continue
                uses = step.get("uses")
                if isinstance(uses, str) and uses.startswith("actions/setup-python@"):
                    errors.append(
                        f"{rel_workflow_path}:{job_name} must use {_LOCAL_PYTHON_SETUP_ACTION} "
                        f"or {_LOCAL_BACKEND_SETUP_ACTION} instead of direct {uses}."
                    )

    runtime_support_matrix = (ROOT / "docs" / "runtime_support_matrix.md").read_text(
        encoding="utf-8"
    )
    if ".github/actions/setup-python/action.yml" not in runtime_support_matrix:
        errors.append(
            "docs/runtime_support_matrix.md must point GitHub Actions maintainers to .github/actions/setup-python/action.yml."
        )
    if ".github/actions/setup-backend/action.yml" not in runtime_support_matrix:
        errors.append(
            "docs/runtime_support_matrix.md must point GitHub Actions maintainers to .github/actions/setup-backend/action.yml."
        )
    if "docker-compose.dev.yml" not in runtime_support_matrix:
        errors.append(
            "docs/runtime_support_matrix.md must mention docker-compose.dev.yml as a Node policy surface."
        )

    ui_readme = (ROOT / "apps" / "ui" / "README.md").read_text(encoding="utf-8")
    if "docs/runtime_support_matrix.md" not in ui_readme or ".nvmrc" not in ui_readme:
        errors.append(
            "apps/ui/README.md must point UI setup readers to docs/runtime_support_matrix.md and .nvmrc."
        )

    ui_smoke = jobs.get("ui-smoke") if isinstance(jobs, Mapping) else None
    steps = ui_smoke.get("steps") if isinstance(ui_smoke, Mapping) else None
    playwright_cache_ok = False
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, Mapping):
                continue
            uses = step.get("uses")
            if not isinstance(uses, str) or not uses.startswith("actions/cache@"):
                continue
            with_data = step.get("with")
            if not isinstance(with_data, Mapping):
                continue
            path = with_data.get("path")
            key = with_data.get("key")
            if (
                isinstance(path, str)
                and path.strip() == "~/.cache/ms-playwright"
                and isinstance(key, str)
                and "ms-playwright" in key
                and "package-lock.json" in key
            ):
                playwright_cache_ok = True
                break
    if not playwright_cache_ok:
        errors.append(
            "ui-smoke must cache ~/.cache/ms-playwright with a package-lock-based actions/cache key."
        )

    for job_name in _BACKEND_TEST_SHARD_JOBS:
        backend_job = jobs.get(job_name) if isinstance(jobs, Mapping) else None
        if isinstance(backend_job, Mapping) and backend_job.get("needs") not in (
            None,
            [],
        ):
            errors.append(
                f"{job_name} must not declare job needs so backend test shards can start immediately."
            )
        backend_steps = (
            backend_job.get("steps") if isinstance(backend_job, Mapping) else None
        )
        backend_duration_cache_ok = False
        if isinstance(backend_steps, list):
            for step in backend_steps:
                if not isinstance(step, Mapping):
                    continue
                uses = step.get("uses")
                if not isinstance(uses, str) or not uses.startswith("actions/cache@"):
                    continue
                with_data = step.get("with")
                if not isinstance(with_data, Mapping):
                    continue
                path = with_data.get("path")
                key = with_data.get("key")
                restore_keys = with_data.get("restore-keys")
                if (
                    isinstance(path, str)
                    and path.strip()
                    == "~/.cache/vibesensor/backend-duration-cache.json"
                    and isinstance(key, str)
                    and "backend-test-durations" in key
                    and "run_backend_parallel.py" in key
                    and "apps/server/tests/**/*.py" in key
                    and "github.run_id" in key
                    and isinstance(restore_keys, str)
                    and "run_backend_parallel.py" in restore_keys
                    and "${{ runner.os }}-backend-test-durations-" in restore_keys
                ):
                    backend_duration_cache_ok = True
                    break
        if not backend_duration_cache_ok:
            errors.append(
                f"{job_name} must cache ~/.cache/vibesensor/backend-duration-cache.json "
                "with a restoreable actions/cache key tied to run_backend_parallel.py, "
                "apps/server/tests, and github.run_id."
            )

    e2e_job = jobs.get("e2e") if isinstance(jobs, Mapping) else None
    steps: object = None
    e2e_uses_docker_steps = False
    if not isinstance(e2e_job, Mapping):
        errors.append("CI workflow is missing the e2e job.")
    else:
        if e2e_job.get("needs") not in (None, []):
            errors.append("e2e must not declare job needs so it can start immediately.")

        steps = e2e_job.get("steps")
        if isinstance(steps, list):
            for step in steps:
                if not isinstance(step, Mapping):
                    continue
                uses = step.get("uses")
                if isinstance(uses, str) and (
                    uses.startswith("docker/setup-buildx-action@")
                    or uses.startswith("docker/build-push-action@")
                ):
                    e2e_uses_docker_steps = True
                    break
    if e2e_uses_docker_steps:
        errors.append(
            "e2e must not depend on Docker buildx or docker image build steps."
        )

    e2e_duration_cache_ok = False
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, Mapping):
                continue
            uses = step.get("uses")
            if not isinstance(uses, str) or not uses.startswith("actions/cache@"):
                continue
            with_data = step.get("with")
            if not isinstance(with_data, Mapping):
                continue
            path = with_data.get("path")
            key = with_data.get("key")
            restore_keys = with_data.get("restore-keys")
            if (
                isinstance(path, str)
                and path.strip() == "~/.cache/vibesensor/e2e-duration-cache.json"
                and isinstance(key, str)
                and "e2e-durations" in key
                and "run_e2e_parallel.py" in key
                and "tests_e2e" in key
                and "github.run_id" in key
                and isinstance(restore_keys, str)
                and "tests_e2e" in restore_keys
                and "${{ runner.os }}-e2e-durations-" in restore_keys
            ):
                e2e_duration_cache_ok = True
                break
    if not e2e_duration_cache_ok:
        errors.append(
            "e2e must cache ~/.cache/vibesensor/e2e-duration-cache.json with a "
            "restoreable actions/cache key tied to run_e2e_parallel.py, tests_e2e, and github.run_id."
        )

    numpy_spec = _project_dependency_spec("numpy")
    if numpy_spec is None:
        errors.append(
            "apps/server/pyproject.toml is missing the numpy runtime dependency."
        )
    else:
        lower_major = _lower_bound_major(numpy_spec)
        upper_major = _upper_bound_major(numpy_spec)
        if lower_major is None or upper_major is None:
            errors.append(
                f"NumPy dependency must declare explicit lower and upper bounds; found {numpy_spec!r}."
            )
        elif upper_major <= lower_major or upper_major > lower_major + 2:
            errors.append(
                "NumPy dependency must stay within at most two adjacent major versions; "
                f"found {numpy_spec!r}."
            )

    return errors


def check_python_policy_alignment() -> list[str]:
    errors: list[str] = []
    pinned_python = _read_required_text(ROOT / ".python-version")
    pinned_minor = _major_minor(pinned_python)
    if pinned_minor is None:
        return [".python-version must contain an exact X.Y.Z Python version."]

    pyproject = _load_server_pyproject()
    project = pyproject.get("project")
    tool = pyproject.get("tool")
    if not isinstance(project, Mapping):
        return ["apps/server/pyproject.toml is missing the [project] table."]
    if not isinstance(tool, Mapping):
        return ["apps/server/pyproject.toml is missing the [tool] table."]

    requires_python = project.get("requires-python")
    if not isinstance(requires_python, str):
        return ["apps/server/pyproject.toml must declare project.requires-python."]
    compatibility_floor = _requires_python_floor(requires_python)
    if compatibility_floor is None:
        return [
            "apps/server/pyproject.toml project.requires-python must use a simple >=X.Y floor for Python policy alignment checks."
        ]
    floor_minor = _major_minor(compatibility_floor)
    if floor_minor is None:
        return [
            "apps/server/pyproject.toml project.requires-python must parse to a Python X.Y floor."
        ]
    if pinned_minor < floor_minor:
        errors.append(
            f".python-version {pinned_python!r} must not be below the package compatibility floor {requires_python!r}."
        )

    ruff = tool.get("ruff")
    if not isinstance(ruff, Mapping):
        errors.append("apps/server/pyproject.toml is missing the [tool.ruff] table.")
    else:
        target_version = ruff.get("target-version")
        expected_target = _ruff_target_for_python(compatibility_floor)
        if target_version != expected_target:
            errors.append(
                "apps/server/pyproject.toml tool.ruff.target-version must match the "
                f"package compatibility floor {compatibility_floor!r}; expected {expected_target!r}, found {target_version!r}."
            )

    mypy = tool.get("mypy")
    if not isinstance(mypy, Mapping):
        errors.append("apps/server/pyproject.toml is missing the [tool.mypy] table.")
    else:
        mypy_python = mypy.get("python_version")
        if mypy_python != compatibility_floor:
            errors.append(
                "apps/server/pyproject.toml tool.mypy.python_version must match the "
                f"package compatibility floor {compatibility_floor!r}; found {mypy_python!r}."
            )

    matrix_text = (ROOT / "docs" / "runtime_support_matrix.md").read_text(
        encoding="utf-8"
    )
    if pinned_python not in matrix_text:
        errors.append(
            "docs/runtime_support_matrix.md must mention the exact native/CI Python pin from .python-version."
        )
    if requires_python not in matrix_text:
        errors.append(
            "docs/runtime_support_matrix.md must mention the backend compatibility floor from apps/server/pyproject.toml."
        )
    if "Backend lint/type settings should target this same floor" not in matrix_text:
        errors.append(
            "docs/runtime_support_matrix.md must explain that backend lint/type settings follow the compatibility floor."
        )

    return errors


def check_runtime_policy_drift() -> list[str]:
    errors: list[str] = []
    matrix_rows = _load_runtime_support_matrix_rows()
    if not matrix_rows:
        return [
            "docs/runtime_support_matrix.md must contain a parseable current support matrix table."
        ]

    pinned_python = _read_required_text(ROOT / ".python-version")
    pinned_node = _read_required_text(ROOT / ".nvmrc")
    pyproject = _load_server_pyproject()
    project = pyproject.get("project")
    if not isinstance(project, Mapping):
        return ["apps/server/pyproject.toml is missing the [project] table."]
    requires_python = project.get("requires-python")
    if not isinstance(requires_python, str):
        return ["apps/server/pyproject.toml must declare project.requires-python."]

    native_row = _require_runtime_support_row(matrix_rows, _NATIVE_RUNTIME_ROW, errors)
    actions_row = _require_runtime_support_row(
        matrix_rows, _GITHUB_ACTIONS_RUNTIME_ROW, errors
    )
    docker_row = _require_runtime_support_row(matrix_rows, _DOCKER_RUNTIME_ROW, errors)
    package_row = _require_runtime_support_row(
        matrix_rows, _PACKAGE_RUNTIME_ROW, errors
    )
    manual_pi_row = _require_runtime_support_row(
        matrix_rows, _MANUAL_PI_RUNTIME_ROW, errors
    )
    pi_image_row = _require_runtime_support_row(
        matrix_rows, _PI_IMAGE_RUNTIME_ROW, errors
    )

    if native_row is not None:
        _matrix_row_mentions(
            native_row,
            pinned_python,
            "the exact native Python pin from .python-version",
            errors,
        )
        _matrix_row_mentions(
            native_row,
            f"{pinned_node}.x",
            "the supported Node major from .nvmrc",
            errors,
        )
        _matrix_row_mentions(
            native_row,
            "make doctor",
            "make doctor as the native prerequisite check",
            errors,
        )
        _matrix_row_mentions(
            native_row,
            "tools/dev/check_prerequisites.py",
            "tools/dev/check_prerequisites.py as the native prerequisite checker",
            errors,
        )

    if actions_row is not None:
        _matrix_row_mentions(
            actions_row,
            ".python-version",
            ".python-version in the GitHub Actions row",
            errors,
        )
        _matrix_row_mentions(
            actions_row,
            ".nvmrc",
            ".nvmrc in the GitHub Actions row",
            errors,
        )
        _matrix_row_mentions(
            actions_row,
            ".github/actions/setup-python/action.yml",
            "the shared GitHub Actions Python setup path",
            errors,
        )
        _matrix_row_mentions(
            actions_row,
            ".github/actions/setup-backend/action.yml",
            "the shared backend setup action",
            errors,
        )

    if docker_row is not None:
        _matrix_row_mentions(
            docker_row,
            ".python-version",
            ".python-version in the Docker row",
            errors,
        )
        _matrix_row_mentions(
            docker_row,
            ".nvmrc",
            ".nvmrc in the Docker row",
            errors,
        )
        _matrix_row_mentions(
            docker_row,
            "apps/server/Dockerfile",
            "apps/server/Dockerfile as a Docker policy surface",
            errors,
        )
        _matrix_row_mentions(
            docker_row,
            "docker-compose.dev.yml",
            "docker-compose.dev.yml as a Docker dev policy surface",
            errors,
        )
        _matrix_row_mentions(
            docker_row,
            "tools/dev/check_hygiene.py",
            "tools/dev/check_hygiene.py as the Docker drift checker",
            errors,
        )

    if package_row is not None:
        _matrix_row_mentions(
            package_row,
            requires_python,
            "the backend package compatibility floor from apps/server/pyproject.toml",
            errors,
        )
        _matrix_row_mentions(
            package_row,
            "apps/server/pyproject.toml",
            "apps/server/pyproject.toml in the package row",
            errors,
        )
        _matrix_row_mentions(
            package_row,
            "compatibility floor",
            "the compatibility-floor explanation for the installable package row",
            errors,
        )

    if manual_pi_row is not None:
        _matrix_row_mentions(
            manual_pi_row,
            requires_python,
            "the packaged-server Python floor in the manual Pi row",
            errors,
        )
        _matrix_row_mentions(
            manual_pi_row,
            "apps/server/scripts/install_pi.sh",
            "apps/server/scripts/install_pi.sh in the manual Pi row",
            errors,
        )

    if pi_image_row is not None:
        _matrix_row_mentions(
            pi_image_row,
            ".python-version",
            ".python-version in the Pi image row",
            errors,
        )
        _matrix_row_mentions(
            pi_image_row,
            "apps/server/pyproject.toml",
            "apps/server/pyproject.toml in the Pi image row",
            errors,
        )
        _matrix_row_mentions(
            pi_image_row,
            ".nvmrc",
            ".nvmrc in the Pi image row",
            errors,
        )
        _matrix_row_mentions(
            pi_image_row,
            "infra/pi-image/pi-gen/README.md",
            "the Pi image README in the Pi image row",
            errors,
        )

    matrix_text = _read_required_text(_RUNTIME_SUPPORT_MATRIX_PATH)
    if (
        "tools/dev/check_hygiene.py" not in matrix_text
        or "runtime-policy coverage contract" not in matrix_text
    ):
        errors.append(
            "docs/runtime_support_matrix.md must explain that tools/dev/check_hygiene.py reads the matrix as the runtime-policy coverage contract."
        )

    contributing_text = _read_required_text(_CONTRIBUTING_PATH)
    for required, description in (
        ("make lint", "make lint as the fixing path"),
        ("runtime policy drift", "runtime policy drift wording"),
        ("docs/runtime_support_matrix.md", "docs/runtime_support_matrix.md"),
        (".python-version", ".python-version"),
        (".nvmrc", ".nvmrc"),
        ("apps/server/pyproject.toml", "apps/server/pyproject.toml"),
    ):
        if required not in contributing_text:
            errors.append(
                "CONTRIBUTING.md must explain how to resolve runtime policy drift failures and must mention "
                f"{description}."
            )

    install_pi_text = _read_required_text(_INSTALL_PI_PATH)
    for required, description in (
        (
            'RUNTIME_POLICY_DOC="docs/runtime_support_matrix.md"',
            "the runtime policy doc path",
        ),
        ('SERVER_PYPROJECT="${PI_DIR}/pyproject.toml"', "the server pyproject anchor"),
        ("read_supported_python_floor()", "read_supported_python_floor()"),
        ("validate_supported_python()", "validate_supported_python()"),
        ("requires python3 >=", "the supported-floor failure message"),
    ):
        if required not in install_pi_text:
            errors.append(
                "apps/server/scripts/install_pi.sh must keep the runtime policy guard and must mention "
                f"{description}."
            )

    image_validation_text = _read_required_text(_IMAGE_VALIDATION_PATH)
    for required, description in (
        ("read_supported_python_floor_from_pyproject()", "pyproject floor parsing"),
        (".vibesensor-python-runtime.env", "the recorded runtime metadata file"),
        ("VALIDATED_IMAGE_PYTHON_VERSION", "validated image Python version output"),
        ("VALIDATED_IMAGE_PYTHON_FLOOR", "validated image Python floor output"),
        ("Validation failed: image runtime Python ", "the runtime mismatch failure"),
    ):
        if required not in image_validation_text:
            errors.append(
                "infra/pi-image/pi-gen/lib/image_validation.sh must keep the runtime policy validation path and must mention "
                f"{description}."
            )

    return errors


def check_dependency_reproducibility_hygiene() -> list[str]:
    errors: list[str] = []

    release_fetcher = (
        ROOT
        / "apps"
        / "server"
        / "vibesensor"
        / "use_cases"
        / "updates"
        / "releases"
        / "release_fetcher.py"
    ).read_text(encoding="utf-8")
    packaging_spec = _project_dependency_spec("packaging")
    if (
        "from packaging.version import Version" in release_fetcher
        and packaging_spec is None
    ):
        errors.append(
            "apps/server/pyproject.toml must declare packaging when release_fetcher imports packaging.version.Version."
        )

    setuptools_spec = _build_system_requirement_spec("setuptools")
    if setuptools_spec is None:
        errors.append(
            "apps/server/pyproject.toml build-system requires must declare setuptools."
        )
    elif "<" not in setuptools_spec:
        errors.append(
            f"apps/server/pyproject.toml build-system setuptools requirement must include an upper bound; found {setuptools_spec!r}."
        )

    wheel_spec = _build_system_requirement_spec("wheel")
    if wheel_spec is None:
        errors.append(
            "apps/server/pyproject.toml build-system requires must declare wheel."
        )
    elif ">=" not in wheel_spec or "<" not in wheel_spec:
        errors.append(
            "apps/server/pyproject.toml build-system wheel requirement must include "
            f"explicit lower and upper bounds; found {wheel_spec!r}."
        )

    websockets_spec = _project_dependency_spec("websockets")
    if websockets_spec is None:
        errors.append(
            "apps/server/pyproject.toml is missing the websockets runtime dependency."
        )
    else:
        lower_major = _lower_bound_major(websockets_spec)
        upper_major = _upper_bound_major(websockets_spec)
        if lower_major is None or upper_major is None:
            errors.append(
                "websockets dependency must declare explicit lower and upper bounds; "
                f"found {websockets_spec!r}."
            )
        elif upper_major != lower_major + 1:
            errors.append(
                "websockets dependency must stay within a single major version window; "
                f"found {websockets_spec!r}."
            )

    framework_pin = _platformio_package_pin("framework-arduinoespressif32")
    if framework_pin is None:
        errors.append(
            "firmware/esp/platformio.ini must pin framework-arduinoespressif32 via "
            "platform_packages."
        )
    elif framework_pin.startswith(("~", "^", "<", ">", "=")):
        errors.append(
            "firmware/esp/platformio.ini must pin framework-arduinoespressif32 to an "
            f"exact version; found {framework_pin!r}."
        )

    dependabot_path = ROOT / ".github" / "dependabot.yml"
    if not dependabot_path.exists():
        errors.append(
            "Missing .github/dependabot.yml for automated dependency updates."
        )
        return errors

    dependabot = _load_yaml_mapping(dependabot_path)
    raw_updates = dependabot.get("updates")
    if not isinstance(raw_updates, list):
        errors.append(".github/dependabot.yml must define an updates list.")
        return errors

    configured_updates: set[tuple[str, str]] = set()
    for item in raw_updates:
        if not isinstance(item, Mapping):
            continue
        ecosystem = item.get("package-ecosystem")
        directory = item.get("directory")
        if isinstance(ecosystem, str) and isinstance(directory, str):
            configured_updates.add((ecosystem, directory))

    required_updates = {
        ("pip", "/apps/server"),
        ("npm", "/apps/ui"),
        ("github-actions", "/"),
    }
    missing_updates = sorted(required_updates - configured_updates)
    if missing_updates:
        errors.append(
            ".github/dependabot.yml is missing required update entries: "
            f"{missing_updates}"
        )

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

    ci_command_sync_errors = check_ci_command_sync()
    if ci_command_sync_errors:
        print("CI command sync drift detected:")
        for item in ci_command_sync_errors:
            print(f"  - {item}")
        failures += 1
    else:
        print("CI commands in sync between ci.yml and run_ci_parallel.py.")

    ci_lite_sync_errors = check_ci_lite_job_sync()
    if ci_lite_sync_errors:
        print("CI lite job drift detected:")
        for item in ci_lite_sync_errors:
            print(f"  - {item}")
        failures += 1
    else:
        print("Makefile CI_LITE_JOBS matches the non-Docker CI subset.")

    docker_ci_hygiene_errors = check_docker_ci_dependency_hygiene()
    if docker_ci_hygiene_errors:
        print("Docker/CI dependency hygiene drift detected:")
        for item in docker_ci_hygiene_errors:
            print(f"  - {item}")
        failures += 1
    else:
        print("Docker/CI dependency hygiene checks passed.")

    python_policy_errors = check_python_policy_alignment()
    if python_policy_errors:
        print("Python policy alignment drift detected:")
        for item in python_policy_errors:
            print(f"  - {item}")
        failures += 1
    else:
        print("Python policy alignment checks passed.")

    runtime_policy_errors = check_runtime_policy_drift()
    if runtime_policy_errors:
        print("Runtime policy drift detected:")
        for item in runtime_policy_errors:
            print(f"  - {item}")
        failures += 1
    else:
        print("Runtime policy drift checks passed.")

    dependency_repro_errors = check_dependency_reproducibility_hygiene()
    if dependency_repro_errors:
        print("Dependency reproducibility hygiene drift detected:")
        for item in dependency_repro_errors:
            print(f"  - {item}")
        failures += 1
    else:
        print("Dependency reproducibility hygiene checks passed.")

    frontend_contract_errors = check_frontend_generated_contract_boundaries()
    if frontend_contract_errors:
        print("Frontend generated-contract boundary drift detected:")
        for item in frontend_contract_errors:
            print(f"  - {item}")
        failures += 1
    else:
        print("Frontend generated-contract boundaries passed.")

    frontend_html_errors = check_frontend_raw_html_boundaries()
    if frontend_html_errors:
        print("Frontend raw HTML boundary drift detected:")
        for item in frontend_html_errors:
            print(f"  - {item}")
        failures += 1
    else:
        print("Frontend raw HTML boundaries passed.")

    frontend_dom_registry_errors = check_frontend_dom_registry_guardrails()
    if frontend_dom_registry_errors:
        print("Frontend DOM registry guardrail drift detected:")
        for item in frontend_dom_registry_errors:
            print(f"  - {item}")
        failures += 1
    else:
        print("Frontend DOM registry guardrails passed.")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
