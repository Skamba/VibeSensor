from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from vibesensor.cli.hotspot_self_heal import main


def test_hotspot_self_heal_cli_loads_config_and_runs_diagnostics() -> None:
    cfg = SimpleNamespace(ap=SimpleNamespace(), self_heal=SimpleNamespace())
    cfg.ap.self_heal = cfg.self_heal

    with (
        patch(
            "argparse.ArgumentParser.parse_args",
            return_value=SimpleNamespace(
                config=Path("/tmp/test-config.yaml"),
                mode="diagnostics",
            ),
        ),
        patch("vibesensor.cli.hotspot_self_heal.load_config", return_value=cfg) as load_config,
        patch("vibesensor.cli.hotspot_self_heal.run_self_heal", return_value=0) as run_self_heal,
        patch("logging.basicConfig") as basic_config,
        pytest.raises(SystemExit) as exc_info,
    ):
        main()

    assert exc_info.value.code == 0
    load_config.assert_called_once_with(Path("/tmp/test-config.yaml"))
    run_self_heal.assert_called_once_with(cfg.ap, cfg.ap.self_heal, diagnostics_only=True)
    basic_config.assert_called_once()
