from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from vibesensor.history_db import HistoryDB
from vibesensor.udp_control_tx import UDPControlPlane


@pytest.mark.asyncio
async def test_lifespan_shutdown_closes_history_db(tmp_path: Path, monkeypatch) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "logging": {
                    "log_metrics": False,
                    "metrics_log_path": str(tmp_path / "metrics.jsonl"),
                    "history_db_path": str(tmp_path / "history.db"),
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("VIBESENSOR_SERVE_STATIC", "0")
    monkeypatch.setenv("VIBESENSOR_DISABLE_AUTO_APP", "1")
    from vibesensor import app as app_module
    from vibesensor.runtime import lifecycle as lifecycle_mod

    async def _fake_udp_receiver(*args, **kwargs):
        return None, None

    async def _fake_start(self):
        return None

    closed = {"value": False}

    def _fake_close(self):
        closed["value"] = True

    monkeypatch.setattr(lifecycle_mod, "start_udp_data_receiver", _fake_udp_receiver)
    monkeypatch.setattr(UDPControlPlane, "start", _fake_start)
    monkeypatch.setattr(HistoryDB, "close", _fake_close)

    app = app_module.create_app(config_path=cfg_path)
    async with app.router.lifespan_context(app):
        pass

    assert closed["value"] is True
