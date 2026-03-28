"""Smoke guards for critical AI-facing runtime and image-build entrypoints."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from _paths import REPO_ROOT, SERVER_ROOT

from vibesensor.adapters.http import create_router

# ---------------------------------------------------------------------------
# Fixtures – read shared files once per module
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def hotspot_script_text() -> str:
    return (SERVER_ROOT / "scripts" / "hotspot_nmcli.sh").read_text(encoding="utf-8")


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


@pytest.fixture(scope="module")
def install_pi_text() -> str:
    return (SERVER_ROOT / "scripts" / "install_pi.sh").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Health route
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_smoke_health_route_registered() -> None:
    state = MagicMock()
    placeholder = MagicMock()
    state.telemetry = SimpleNamespace(
        control_plane=placeholder,
        health_state=placeholder,
        processing_loop_state=placeholder,
        processor=placeholder,
        registry=placeholder,
        run_recorder=placeholder,
        ws_hub=placeholder,
    )
    state.settings = SimpleNamespace(
        gps_monitor=placeholder,
        settings_store=placeholder,
    )
    state.history = SimpleNamespace(
        export_service=placeholder,
        report_service=placeholder,
        run_service=placeholder,
    )
    state.updates = SimpleNamespace(
        esp_flash_manager=placeholder,
        update_manager=placeholder,
    )
    router = create_router(state)
    routes = {r.path: r.methods for r in router.routes if hasattr(r, "methods")}
    assert "/api/health" in routes, "Missing /api/health route"
    assert "GET" in routes["/api/health"], "/api/health must support GET"


# ---------------------------------------------------------------------------
# Hotspot script (shared fixture avoids reading the file twice)
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_smoke_hotspot_script_has_no_runtime_apt_get(hotspot_script_text: str) -> None:
    assert "apt-get" not in hotspot_script_text, (
        "hotspot script must not install packages at runtime"
    )


# ---------------------------------------------------------------------------
# Build wrapper (parametrized for per-check failure isolation)
# ---------------------------------------------------------------------------

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
    ("substring", "msg"),
    _BUILD_WRAPPER_CHECKS,
    ids=[c[0][:40] for c in _BUILD_WRAPPER_CHECKS],
)
def test_smoke_build_wrapper_asserts_requirement(
    pi_gen_source_text: str,
    substring: str,
    msg: str,
) -> None:
    assert substring in pi_gen_source_text, msg


@pytest.mark.smoke
def test_smoke_pi_gen_pipeline_split_files_exist() -> None:
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
def test_smoke_server_systemd_uses_console_script_entrypoint() -> None:
    service_text = (REPO_ROOT / "apps" / "server" / "systemd" / "vibesensor.service").read_text(
        encoding="utf-8"
    )

    assert (
        "ExecStart=__VENV_DIR__/bin/vibesensor-server --config /etc/vibesensor/config.yaml"
        in service_text
    )


# ---------------------------------------------------------------------------
# install_pi.sh (parametrized for per-check failure isolation)
# ---------------------------------------------------------------------------

_INSTALL_PI_CHECKS: list[tuple[str, str]] = [
    ("python3", "Pi install script must install python3"),
    (
        'chown -R "${SERVICE_USER}:${SERVICE_USER}" "${PI_DIR}"',
        "Pi install script must ensure repo ownership for update writes",
    ),
    ("rollback", "Pi install script must create rollback directory for release-based updates"),
    (
        "vibesensor-fw-refresh",
        "Pi install script must refresh ESP firmware cache from GitHub Releases",
    ),
    ("firmware", "Pi install script must handle ESP firmware cache"),
]


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("substring", "msg"),
    _INSTALL_PI_CHECKS,
    ids=[c[0][:40] for c in _INSTALL_PI_CHECKS],
)
def test_smoke_install_pi_requires(install_pi_text: str, substring: str, msg: str) -> None:
    assert substring in install_pi_text, msg


# ---------------------------------------------------------------------------
# Remaining smoke checks (unchanged)
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_smoke_server_pyproject_includes_esptool_for_esp_flash() -> None:
    pyproject = SERVER_ROOT / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert "esptool" in text, "Server dependencies must include esptool for offline ESP flash"
    assert "vibesensor-fw-refresh" in text, (
        "Server must expose firmware cache refresh CLI entry point"
    )
    assert "vibesensor-fw-info" in text, "Server must expose firmware cache info CLI entry point"
    assert "vibesensor.use_cases.updates.firmware.firmware_cache:refresh_cache_cli" in text, (
        "Firmware cache refresh CLI entry point must target the firmware package module"
    )
    assert "vibesensor.use_cases.updates.firmware.firmware_cache:cache_info_cli" in text, (
        "Firmware cache info CLI entry point must target the firmware package module"
    )
    assert "vibesensor.use_cases.updates.releases.release_fetcher:fetch_latest_wheel_cli" in text, (
        "Server release fetch CLI entry point must target the releases package module"
    )


@pytest.mark.smoke
def test_smoke_firmware_uses_vendored_neopixel_library_for_offline_builds() -> None:
    repo_root = REPO_ROOT
    platformio_ini = repo_root / "firmware" / "esp" / "platformio.ini"
    text = platformio_ini.read_text(encoding="utf-8")
    assert "${PROJECT_DIR}/lib/Adafruit_NeoPixel" in text, (
        "firmware platformio.ini must use vendored NeoPixel library path"
    )
    vendored_header = (
        repo_root / "firmware" / "esp" / "lib" / "Adafruit_NeoPixel" / "Adafruit_NeoPixel.h"
    )
    assert vendored_header.is_file(), (
        "vendored NeoPixel header must exist for offline firmware build"
    )
