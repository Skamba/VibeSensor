"""Guard Pi image Python runtime reporting and policy validation."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests._paths import REPO_ROOT

_ARTIFACTS_SCRIPT = REPO_ROOT / "infra/pi-image/pi-gen/lib/artifacts.sh"
_IMAGE_VALIDATION_SCRIPT = REPO_ROOT / "infra/pi-image/pi-gen/lib/image_validation.sh"
_BUILD_SCRIPT = REPO_ROOT / "infra/pi-image/pi-gen/build.sh"
_STAGE_RUN_TEMPLATE = (
    REPO_ROOT / "infra/pi-image/pi-gen/templates/stage-vibesensor/00-vibesensor/00-run.sh.template"
)


def _run_artifacts_script(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            "-lc",
            f'set -euo pipefail; source "{_ARTIFACTS_SCRIPT}"; {command}',
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _run_image_validation_script(
    command: str, *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            "-lc",
            f'set -euo pipefail; source "{_IMAGE_VALIDATION_SCRIPT}"; {command}',
        ],
        check=check,
        capture_output=True,
        text=True,
    )


def test_image_validation_reads_supported_python_floor_from_pyproject(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        "\n".join(
            [
                "[project]",
                'requires-python = ">=3.13"',
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = _run_image_validation_script(
        f'read_supported_python_floor_from_pyproject "{pyproject}"'
    )

    assert result.stdout.strip() == "3.13"


def test_image_validation_python_version_meets_floor() -> None:
    _run_image_validation_script('python_version_meets_floor "3.13.4" "3.13"')
    _run_image_validation_script('python_version_meets_floor "3.14.0" "3.13"')

    result = _run_image_validation_script(
        'python_version_meets_floor "3.12.9" "3.13"',
        check=False,
    )

    assert result.returncode == 1


def test_pi_image_stage_records_runtime_python_metadata_before_cleanup() -> None:
    text = _STAGE_RUN_TEMPLATE.read_text(encoding="utf-8")

    metadata_path = (
        'PYTHON_RUNTIME_INFO_FILE="/opt/VibeSensor/apps/server/.venv/'
        '.vibesensor-python-runtime.env"'
    )
    metadata_write = 'cat >"${PYTHON_RUNTIME_INFO_FILE}" <<EOF'
    cleanup_block = "rm -rf \\"

    assert metadata_path in text
    assert "venv_python_version=${VENV_PYTHON_VERSION}" in text
    assert "supported_python_floor=${SUPPORTED_PYTHON_FLOOR}" in text
    assert text.index(metadata_write) < text.index(cleanup_block)


def test_image_validation_reports_and_checks_embedded_python_runtime_metadata() -> None:
    text = _IMAGE_VALIDATION_SCRIPT.read_text(encoding="utf-8")

    assert ".vibesensor-python-runtime.env" in text
    assert "Validation failed: image runtime Python " in text
    assert "validated_venv_python_version=${VALIDATED_IMAGE_PYTHON_VERSION}" in text
    assert "validated_supported_python_floor=>=${VALIDATED_IMAGE_PYTHON_FLOOR}" in text


def test_write_version_info_includes_validated_image_python_metadata(tmp_path: Path) -> None:
    version_info = tmp_path / "image.version.txt"

    _run_artifacts_script(
        " ".join(
            [
                f'write_version_info "{version_info}"',
                '"/tmp/vibesensor-lite.img.zip"',
                '"20260406T010520Z"',
                '"abcdef123456"',
                '"main"',
                '"3.13.4"',
                '"3.13"',
            ]
        )
    )

    text = version_info.read_text(encoding="utf-8")
    assert "image_runtime_python_version=3.13.4" in text
    assert "image_runtime_python_floor=3.13" in text


def test_pi_build_threads_validated_runtime_python_into_version_info() -> None:
    text = _BUILD_SCRIPT.read_text(encoding="utf-8")

    assert '"${VALIDATED_IMAGE_PYTHON_VERSION:-}"' in text
    assert '"${VALIDATED_IMAGE_PYTHON_FLOOR:-}"' in text
