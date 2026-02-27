from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vibesensor.api import create_router


@pytest.mark.smoke
def test_smoke_health_route_registered() -> None:
    state = MagicMock()
    router = create_router(state)
    routes = {r.path: r.methods for r in router.routes if hasattr(r, "methods")}
    assert "/api/health" in routes, "Missing /api/health route"
    assert "GET" in routes["/api/health"], "/api/health must support GET"


@pytest.mark.smoke
def test_smoke_hotspot_script_has_no_runtime_apt_get() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "hotspot_nmcli.sh"
    text = script.read_text(encoding="utf-8")
    assert "apt-get" not in text, "hotspot script must not install packages at runtime"


@pytest.mark.smoke
def test_smoke_hotspot_script_only_reactivates_ap_after_uplink_session() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "hotspot_nmcli.sh"
    text = script.read_text(encoding="utf-8")
    assert 'if [ "${UPLINK_SESSION_USED:-0}" = "1" ]; then' in text, (
        "hotspot script must not re-activate AP connection unconditionally"
    )


@pytest.mark.smoke
def test_smoke_build_wrapper_asserts_hotspot_requirements() -> None:
    build_sh = Path(__file__).resolve().parents[3] / "infra" / "pi-image" / "pi-gen" / "build.sh"
    text = build_sh.read_text(encoding="utf-8")
    assert "nodejs" in text, "build wrapper must bake nodejs for on-device UI rebuild"
    assert "npm" in text, "build wrapper must bake npm for on-device UI rebuild"
    assert "network-manager" in text, "build wrapper must bake network-manager"
    assert "dnsmasq" in text, "build wrapper must bake dnsmasq"
    assert "99-vibesensor-dnsmasq.conf" in text, "build wrapper must assert DNS drop-in"
    assert "firmware" in text, "build wrapper must handle ESP firmware cache/baseline"
    assert "flash.json" in text, "build wrapper must validate firmware manifest"
    assert "vibesensor-fw-refresh" in text, (
        "build wrapper must call firmware cache refresh CLI entrypoint"
    )
    assert "10-vibesensor-hostkeys.conf" in text, (
        "build wrapper must include ssh host-key bootstrap drop-in"
    )
    assert "Validation failed: ssh.service is not enabled in multi-user.target" in text, (
        "build wrapper must validate ssh.service enablement"
    )
    assert "Validation failed: sshd first-boot readiness test failed" in text, (
        "build wrapper must validate sshd first-boot readiness"
    )


@pytest.mark.smoke
def test_smoke_install_pi_installs_core_toolchain() -> None:
    """Verify install_pi.sh installs required packages and sets up rollback dir."""
    script = Path(__file__).resolve().parents[1] / "scripts" / "install_pi.sh"
    text = script.read_text(encoding="utf-8")
    assert "python3" in text, "Pi install script must install python3"
    assert 'chown -R "${SERVICE_USER}:${SERVICE_USER}" "${PI_DIR}"' in text, (
        "Pi install script must ensure repo ownership for update writes"
    )
    assert "rollback" in text, (
        "Pi install script must create rollback directory for release-based updates"
    )
    assert "vibesensor-fw-refresh" in text, (
        "Pi install script must refresh ESP firmware cache from GitHub Releases"
    )
    assert "firmware" in text, "Pi install script must handle ESP firmware cache"


@pytest.mark.smoke
def test_smoke_server_pyproject_includes_esptool_for_esp_flash() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert "esptool" in text, "Server dependencies must include esptool for offline ESP flash"
    assert "vibesensor-fw-refresh" in text, (
        "Server must expose firmware cache refresh CLI entry point"
    )
    assert "vibesensor-fw-info" in text, "Server must expose firmware cache info CLI entry point"


@pytest.mark.smoke
def test_smoke_firmware_uses_vendored_neopixel_library_for_offline_builds() -> None:
    repo_root = Path(__file__).resolve().parents[3]
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
