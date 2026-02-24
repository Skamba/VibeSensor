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
def test_smoke_build_wrapper_asserts_hotspot_requirements() -> None:
    build_sh = Path(__file__).resolve().parents[3] / "infra" / "pi-image" / "pi-gen" / "build.sh"
    text = build_sh.read_text(encoding="utf-8")
    assert "nodejs" in text, "build wrapper must bake nodejs for on-device UI rebuild"
    assert "npm" in text, "build wrapper must bake npm for on-device UI rebuild"
    assert "network-manager" in text, "build wrapper must bake network-manager"
    assert "dnsmasq" in text, "build wrapper must bake dnsmasq"
    assert "99-vibesensor-dnsmasq.conf" in text, "build wrapper must assert DNS drop-in"


@pytest.mark.smoke
def test_smoke_install_pi_installs_rebuild_toolchain() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "install_pi.sh"
    text = script.read_text(encoding="utf-8")
    assert "nodejs" in text, "Pi install script must install nodejs for on-device rebuilds"
    assert "npm" in text, "Pi install script must install npm for on-device rebuilds"
    assert 'chown -R "${SERVICE_USER}:${SERVICE_USER}" "${PI_DIR}"' in text, (
        "Pi install script must ensure repo ownership for update writes"
    )


@pytest.mark.smoke
def test_smoke_server_pyproject_includes_platformio_for_esp_flash() -> None:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert "platformio" in text, "Server dependencies must include platformio for ESP flash"
