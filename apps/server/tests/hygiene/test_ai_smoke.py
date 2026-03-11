from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from _paths import REPO_ROOT, SERVER_ROOT

from vibesensor.routes import create_router

# ---------------------------------------------------------------------------
# Fixtures – read shared files once per module
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def hotspot_script_text() -> str:
    return (SERVER_ROOT / "scripts" / "hotspot_nmcli.sh").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def build_sh_text() -> str:
    return (REPO_ROOT / "infra" / "pi-image" / "pi-gen" / "build.sh").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def install_pi_text() -> str:
    return (SERVER_ROOT / "scripts" / "install_pi.sh").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Health route
# ---------------------------------------------------------------------------


@pytest.mark.smoke
def test_smoke_health_route_registered() -> None:
    state = MagicMock()
    state.registry = MagicMock()
    state.processor = MagicMock()
    state.control_plane = MagicMock()
    state.worker_pool = MagicMock()
    state.settings_store = MagicMock()
    state.analysis_settings = MagicMock()
    state.gps_monitor = MagicMock()
    state.metrics_logger = MagicMock()
    state.history_db = MagicMock()
    state.run_service = MagicMock()
    state.report_service = MagicMock()
    state.export_service = MagicMock()
    state.ws_hub = MagicMock()
    state.ws_cache = MagicMock()
    state.ws_broadcast = MagicMock()
    state.processing_loop_state = MagicMock()
    state.health_state = MagicMock()
    state.processing_loop = MagicMock()
    state.update_manager = MagicMock()
    state.esp_flash_manager = MagicMock()
    state.apply_car_settings = MagicMock()
    state.apply_speed_source_settings = MagicMock()
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
]


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("substring", "msg"),
    _BUILD_WRAPPER_CHECKS,
    ids=[c[0][:40] for c in _BUILD_WRAPPER_CHECKS],
)
def test_smoke_build_wrapper_asserts_requirement(
    build_sh_text: str,
    substring: str,
    msg: str,
) -> None:
    assert substring in build_sh_text, msg


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
