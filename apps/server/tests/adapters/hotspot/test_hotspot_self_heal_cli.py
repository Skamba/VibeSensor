"""CLI smoke test for hotspot self-heal diagnostics mode."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from vibesensor.cli.hotspot_self_heal import main


@pytest.mark.parametrize(
    ("mode", "expected_diagnostics_only"),
    [
        pytest.param("diagnostics", True, id="diagnostics-mode"),
        pytest.param("check-heal", False, id="check-heal-mode"),
    ],
)
def test_hotspot_self_heal_cli_loads_config_and_runs_selected_mode(
    mode: str,
    expected_diagnostics_only: bool,
) -> None:
    config = SimpleNamespace(ap=SimpleNamespace(), self_heal=SimpleNamespace())
    config.ap.self_heal = config.self_heal

    with (
        patch(
            "argparse.ArgumentParser.parse_args",
            return_value=SimpleNamespace(
                config=Path("/tmp/test-config.yaml"),
                mode=mode,
            ),
        ),
        patch("vibesensor.cli.hotspot_self_heal.load_config", return_value=config) as load_config,
        patch("vibesensor.cli.hotspot_self_heal.run_self_heal", return_value=0) as run_self_heal,
        patch("logging.basicConfig") as basic_config,
        pytest.raises(SystemExit) as exc_info,
    ):
        main()

    assert exc_info.value.code == 0
    load_config.assert_called_once_with(Path("/tmp/test-config.yaml"))
    run_self_heal.assert_called_once_with(
        config.ap,
        config.ap.self_heal,
        diagnostics_only=expected_diagnostics_only,
    )
    basic_config.assert_called_once()
