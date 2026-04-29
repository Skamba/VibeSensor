"""Static guardrails for pi-image layout and packaged entrypoint contracts."""

from __future__ import annotations

import pytest
from _paths import REPO_ROOT


@pytest.mark.smoke
def test_pi_gen_pipeline_split_files_exist() -> None:
    pi_gen_root = REPO_ROOT / "infra" / "pi-image" / "pi-gen"

    assert (pi_gen_root / "validate-image.sh").is_file()
    assert (pi_gen_root / "lib" / "app_artifacts.sh").is_file()
    assert (pi_gen_root / "lib" / "stage_assembly.sh").is_file()
    assert (pi_gen_root / "lib" / "image_validation.sh").is_file()
    assert (pi_gen_root / "templates" / "stage0-bootstrap-raspberrypi.gpg").is_file()
    assert (
        pi_gen_root / "templates" / "stage-vibesensor" / "00-vibesensor" / "00-run.sh.template"
    ).is_file()


@pytest.mark.smoke
def test_server_systemd_uses_console_script_entrypoint() -> None:
    service_text = (REPO_ROOT / "apps" / "server" / "systemd" / "vibesensor.service").read_text(
        encoding="utf-8"
    )

    assert (
        "ExecStart=__VENV_DIR__/bin/vibesensor-server --config /etc/vibesensor/config.yaml"
        in service_text
    )


@pytest.mark.smoke
def test_pi_image_validation_checks_current_packaged_static_data_layout() -> None:
    validation_text = (
        REPO_ROOT / "infra" / "pi-image" / "pi-gen" / "lib" / "image_validation.sh"
    ).read_text(encoding="utf-8")

    assert "vehicle_configurations" in validation_text
    assert "car_sources" in validation_text
    assert "car_library.json" not in validation_text
