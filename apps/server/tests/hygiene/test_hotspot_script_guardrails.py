"""Static guardrails for the hotspot provisioning script."""

from __future__ import annotations

import pytest
from _paths import SERVER_ROOT


@pytest.fixture(scope="module")
def hotspot_script_text() -> str:
    return (SERVER_ROOT / "scripts" / "hotspot_nmcli.sh").read_text(encoding="utf-8")


@pytest.mark.smoke
def test_hotspot_script_has_no_runtime_apt_get(hotspot_script_text: str) -> None:
    assert "apt-get" not in hotspot_script_text, (
        "hotspot script must not install packages at runtime"
    )


@pytest.mark.smoke
def test_hotspot_script_prefers_repo_venv_hotspot_config_cli(
    hotspot_script_text: str,
) -> None:
    assert ".venv/bin/vibesensor-hotspot-config" in hotspot_script_text, (
        "hotspot script must resolve hotspot config from the bundled server venv"
    )
    assert 'HOTSPOT_CONFIG_EXPORTS="$("${HOTSPOT_CONFIG_CLI}" "${CONFIG_PATH}")"' in (
        hotspot_script_text
    ), "hotspot script must capture config CLI output before eval"


@pytest.mark.smoke
def test_hotspot_script_err_trap_logs_to_stderr(hotspot_script_text: str) -> None:
    assert 'echo "ERROR rc=${rc} line=${failed_line} cmd=${failed_cmd}" >&2' in (
        hotspot_script_text
    ), "ERR trap output must go to stderr so eval command substitutions stay clean"
