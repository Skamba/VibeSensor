# ruff: noqa: F403,F405
"""Runtime policy and dependency reproducibility checks."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping


from ._shared import *
from .ci_workflow import (
    _extend_missing_text_requirements,
)


def _requires_python_floor(spec: str) -> str | None:
    match = re.fullmatch(r"\s*>=\s*(\d+\.\d+)(?:\.\d+)?\s*", spec)
    if match is None:
        return None
    return match.group(1)


def _ruff_target_for_python(version: str) -> str:
    major, minor = version.split(".")
    return f"py{major}{minor}"


def _major_minor(version: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"\s*(\d+)\.(\d+)(?:\.\d+)?\s*", version)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


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


def _load_server_pyproject() -> dict[str, object]:
    return tomllib.loads((ROOT / "apps" / "server" / "pyproject.toml").read_text())


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


def check_python_policy_alignment() -> list[str]:
    errors: list[str] = []
    pinned_python = _read_required_text(ROOT / ".python-version")
    pinned_minor = _major_minor(pinned_python)
    if pinned_minor is None:
        return [".python-version must contain an exact X.Y.Z Python version."]
    pinned_minor_str = f"{pinned_minor[0]}.{pinned_minor[1]}"

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
        if mypy_python != pinned_minor_str:
            errors.append(
                "apps/server/pyproject.toml tool.mypy.python_version must match the "
                f"exact native/CI Python minor from .python-version ({pinned_minor_str!r}); found {mypy_python!r}."
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
    if "Backend Ruff formatting/lint stays on this floor" not in matrix_text:
        errors.append(
            "docs/runtime_support_matrix.md must explain that backend Ruff formatting/lint follows the compatibility floor."
        )
    if (
        "backend mypy type checking follows the exact native-dev / CI Python minor"
        not in matrix_text
    ):
        errors.append(
            "docs/runtime_support_matrix.md must explain that backend mypy follows the exact native/CI Python minor from .python-version."
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
    _extend_missing_text_requirements(
        errors,
        contributing_text,
        (
            TextRequirement(
                needle="make lint",
                error_message=(
                    "CONTRIBUTING.md must explain how to resolve runtime policy drift failures and "
                    "must mention make lint as the fixing path."
                ),
            ),
            TextRequirement(
                needle="runtime policy drift",
                error_message=(
                    "CONTRIBUTING.md must explain how to resolve runtime policy drift failures and "
                    "must mention runtime policy drift wording."
                ),
            ),
            TextRequirement(
                needle="docs/runtime_support_matrix.md",
                error_message=(
                    "CONTRIBUTING.md must explain how to resolve runtime policy drift failures and "
                    "must mention docs/runtime_support_matrix.md."
                ),
            ),
            TextRequirement(
                needle=".python-version",
                error_message=(
                    "CONTRIBUTING.md must explain how to resolve runtime policy drift failures and "
                    "must mention .python-version."
                ),
            ),
            TextRequirement(
                needle=".nvmrc",
                error_message=(
                    "CONTRIBUTING.md must explain how to resolve runtime policy drift failures and "
                    "must mention .nvmrc."
                ),
            ),
            TextRequirement(
                needle="apps/server/pyproject.toml",
                error_message=(
                    "CONTRIBUTING.md must explain how to resolve runtime policy drift failures and "
                    "must mention apps/server/pyproject.toml."
                ),
            ),
        ),
    )

    install_pi_text = _read_required_text(_INSTALL_PI_PATH)
    _extend_missing_text_requirements(
        errors,
        install_pi_text,
        (
            TextRequirement(
                needle='RUNTIME_POLICY_DOC="docs/runtime_support_matrix.md"',
                error_message=(
                    "apps/server/scripts/install_pi.sh must keep the runtime policy guard and must "
                    "mention the runtime policy doc path."
                ),
            ),
            TextRequirement(
                needle='SERVER_PYPROJECT="${PI_DIR}/pyproject.toml"',
                error_message=(
                    "apps/server/scripts/install_pi.sh must keep the runtime policy guard and must "
                    "mention the server pyproject anchor."
                ),
            ),
            TextRequirement(
                needle="read_supported_python_floor()",
                error_message=(
                    "apps/server/scripts/install_pi.sh must keep the runtime policy guard and must "
                    "mention read_supported_python_floor()."
                ),
            ),
            TextRequirement(
                needle="validate_supported_python()",
                error_message=(
                    "apps/server/scripts/install_pi.sh must keep the runtime policy guard and must "
                    "mention validate_supported_python()."
                ),
            ),
            TextRequirement(
                needle="requires python3 >=",
                error_message=(
                    "apps/server/scripts/install_pi.sh must keep the runtime policy guard and must "
                    "mention the supported-floor failure message."
                ),
            ),
        ),
    )

    image_validation_text = _read_required_text(_IMAGE_VALIDATION_PATH)
    _extend_missing_text_requirements(
        errors,
        image_validation_text,
        (
            TextRequirement(
                needle="read_supported_python_floor_from_pyproject()",
                error_message=(
                    "infra/pi-image/pi-gen/lib/image_validation.sh must keep the runtime policy "
                    "validation path and must mention pyproject floor parsing."
                ),
            ),
            TextRequirement(
                needle=".vibesensor-python-runtime.env",
                error_message=(
                    "infra/pi-image/pi-gen/lib/image_validation.sh must keep the runtime policy "
                    "validation path and must mention the recorded runtime metadata file."
                ),
            ),
            TextRequirement(
                needle="VALIDATED_IMAGE_PYTHON_VERSION",
                error_message=(
                    "infra/pi-image/pi-gen/lib/image_validation.sh must keep the runtime policy "
                    "validation path and must mention the validated image Python version output."
                ),
            ),
            TextRequirement(
                needle="VALIDATED_IMAGE_PYTHON_FLOOR",
                error_message=(
                    "infra/pi-image/pi-gen/lib/image_validation.sh must keep the runtime policy "
                    "validation path and must mention the validated image Python floor output."
                ),
            ),
            TextRequirement(
                needle="Validation failed: image runtime Python ",
                error_message=(
                    "infra/pi-image/pi-gen/lib/image_validation.sh must keep the runtime policy "
                    "validation path and must mention the runtime mismatch failure."
                ),
            ),
        ),
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

    configured_updates: dict[tuple[str, str], Mapping[str, object]] = {}
    for item in raw_updates:
        if not isinstance(item, Mapping):
            continue
        ecosystem = item.get("package-ecosystem")
        directory = item.get("directory")
        if isinstance(ecosystem, str) and isinstance(directory, str):
            configured_updates[(ecosystem, directory)] = item

    required_updates = {
        ("pip", "/apps/server"),
        ("npm", "/apps/ui"),
        ("github-actions", "/"),
        ("docker", "/"),
    }
    missing_updates = sorted(required_updates - set(configured_updates))
    if missing_updates:
        errors.append(
            ".github/dependabot.yml is missing required update entries: "
            f"{missing_updates}"
        )

    docker_update = configured_updates.get(("docker", "/"))
    if docker_update is not None:
        schedule = docker_update.get("schedule")
        if not isinstance(schedule, Mapping) or schedule.get("interval") != "weekly":
            errors.append(".github/dependabot.yml docker updates must run weekly.")
        labels = docker_update.get("labels")
        label_names = (
            {label for label in labels if isinstance(label, str)}
            if isinstance(labels, list)
            else set()
        )
        if {"CI", "dependencies"} - label_names:
            errors.append(
                ".github/dependabot.yml docker updates must carry CI and dependencies labels."
            )

    return errors
