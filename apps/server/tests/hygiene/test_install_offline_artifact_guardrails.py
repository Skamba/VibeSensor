"""Static guardrails for install flow and offline artifact packaging."""

from __future__ import annotations

import pytest
from _paths import REPO_ROOT, SERVER_ROOT


@pytest.fixture(scope="module")
def install_pi_text() -> str:
    return (SERVER_ROOT / "scripts" / "install_pi.sh").read_text(encoding="utf-8")


_INSTALL_PI_CHECKS: list[tuple[str, str]] = [
    ("python3", "Pi install script must install python3"),
    (
        'chown -R "${SERVICE_USER}:${SERVICE_USER}" "${VENV_DIR}"',
        "Pi install script must ensure virtualenv ownership for update writes",
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
    ("substring", "message"),
    _INSTALL_PI_CHECKS,
    ids=[check[0][:40] for check in _INSTALL_PI_CHECKS],
)
def test_install_pi_requires(install_pi_text: str, substring: str, message: str) -> None:
    assert substring in install_pi_text, message


@pytest.mark.smoke
def test_server_pyproject_includes_esp_flash_and_firmware_cache_entrypoints() -> None:
    pyproject_text = (SERVER_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "esptool" in pyproject_text, (
        "Server dependencies must include esptool for offline ESP flash"
    )
    assert "pyserial" in pyproject_text, (
        "Server dependencies must include pyserial for ESP port discovery"
    )
    assert "vibesensor-fw-refresh" in pyproject_text, (
        "Server must expose firmware cache refresh CLI entry point"
    )
    assert "vibesensor-fw-info" in pyproject_text, (
        "Server must expose firmware cache info CLI entry point"
    )
    assert (
        "vibesensor.use_cases.updates.firmware.firmware_cache:refresh_cache_cli" in pyproject_text
    ), "Firmware cache refresh CLI entry point must target the firmware package module"
    assert (
        "vibesensor.use_cases.updates.firmware.firmware_cache:cache_info_cli" in pyproject_text
    ), "Firmware cache info CLI entry point must target the firmware package module"
    assert "vibesensor.use_cases.updates.releases.cli:fetch_latest_wheel_cli" in pyproject_text, (
        "Server release fetch CLI entry point must target the releases package module"
    )
    assert pyproject_text.count("vibesensor-fw-refresh") == 1
    assert pyproject_text.count("vibesensor-fw-info") == 1


@pytest.mark.smoke
def test_firmware_uses_pinned_registry_neopixel_library() -> None:
    platformio_text = (REPO_ROOT / "firmware" / "esp" / "platformio.ini").read_text(
        encoding="utf-8"
    )
    assert platformio_text.count("platform = espressif32@6.13.0") == 1, (
        "shared ESP32 PlatformIO settings must stay consolidated in one base env"
    )
    assert platformio_text.count("extends = env:firmware_esp32") == 2, (
        "both ESP32 board environments must inherit the shared firmware base env"
    )
    assert "adafruit/Adafruit NeoPixel@1.15.4" in platformio_text, (
        "firmware platformio.ini must pin the NeoPixel PlatformIO registry dependency"
    )
    assert "lib_deps =" in platformio_text
    vendored_library = REPO_ROOT / "firmware" / "esp" / "lib" / "Adafruit_NeoPixel"
    assert not vendored_library.exists(), (
        "firmware must not vendor Adafruit NeoPixel now that platformio.ini pins it"
    )
