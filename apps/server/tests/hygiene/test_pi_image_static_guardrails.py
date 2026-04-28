"""Static guardrails for pi-image build wrappers and layout."""

from __future__ import annotations

import pytest
from _paths import REPO_ROOT


@pytest.fixture(scope="module")
def pi_gen_source_text() -> str:
    pi_gen_root = REPO_ROOT / "infra" / "pi-image" / "pi-gen"
    paths = [
        pi_gen_root / "build.sh",
        pi_gen_root / "validate-image.sh",
        *sorted((pi_gen_root / "lib").glob("*.sh")),
        *sorted(
            path
            for path in (pi_gen_root / "templates").rglob("*")
            if path.is_file() and path.suffix != ".gpg"
        ),
    ]
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)


_BUILD_WRAPPER_CHECKS: list[tuple[str, str]] = [
    ("BUILD_MODE", "build wrapper must support split app/image build modes"),
    ("BUILD_MODE=app", "build wrapper must support app-only artifact builds"),
    ("npm", "build wrapper must build UI artifacts during app build mode"),
    ("network-manager", "build wrapper must bake network-manager"),
    ("dnsmasq", "build wrapper must bake dnsmasq"),
    ("99-vibesensor-dnsmasq.conf", "build wrapper must assert DNS drop-in"),
    ("firmware", "build wrapper must handle ESP firmware cache/baseline"),
    ("flash.json", "build wrapper must validate firmware manifest"),
    ("vibesensor-fw-refresh", "build wrapper must call firmware cache refresh CLI entrypoint"),
    ("10-vibesensor-hostkeys.conf", "build wrapper must include ssh host-key bootstrap drop-in"),
    (
        "Validation failed: ssh.service is not enabled in multi-user.target",
        "build wrapper must validate ssh.service enablement",
    ),
    (
        "Validation failed: sshd first-boot readiness test failed",
        "build wrapper must validate sshd first-boot readiness",
    ),
    (
        "Validation failed: first user password hash does not match VS_FIRST_USER_PASS",
        "build wrapper must validate the configured first user password hash",
    ),
]


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("substring", "message"),
    _BUILD_WRAPPER_CHECKS,
    ids=[check[0][:40] for check in _BUILD_WRAPPER_CHECKS],
)
def test_build_wrapper_asserts_requirement(
    pi_gen_source_text: str,
    substring: str,
    message: str,
) -> None:
    assert substring in pi_gen_source_text, message


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
    assert (
        REPO_ROOT / "apps" / "server" / "systemd" / "vibesensor-rfkill-unblock.service"
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
