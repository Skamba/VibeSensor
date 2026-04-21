"""App lifespan coverage for shutting down runtime resources cleanly."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
import yaml

from vibesensor.adapters.persistence.history_db import SQLiteHistoryEngine
from vibesensor.adapters.udp.udp_control_tx import UDPControlPlane


def _write_config(tmp_path: Path) -> Path:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "logging": {
                    "history_db_path": str(tmp_path / "history.db"),
                },
            },
        ),
        encoding="utf-8",
    )
    return cfg_path


@pytest.mark.asyncio
async def test_lifespan_shutdown_closes_history_db(tmp_path: Path, monkeypatch) -> None:
    cfg_path = _write_config(tmp_path)
    monkeypatch.setenv("VIBESENSOR_SERVE_STATIC", "0")
    from vibesensor import app as app_module
    from vibesensor.app import bootstrap as bootstrap_mod

    async def _fake_udp_receiver(*args, **kwargs):
        return None, None

    async def _fake_start(self):
        return None

    async def _fake_stop(self):
        await self._runtime.history_db.aclose()

    closed = {"value": False}

    async def _fake_close(self):
        closed["value"] = True

    monkeypatch.setattr(bootstrap_mod, "start_udp_data_receiver", _fake_udp_receiver)
    monkeypatch.setattr(bootstrap_mod.LifecycleManager, "start", _fake_start)
    monkeypatch.setattr(bootstrap_mod.LifecycleManager, "stop", _fake_stop)
    monkeypatch.setattr(UDPControlPlane, "start", _fake_start)
    monkeypatch.setattr(SQLiteHistoryEngine, "aclose", _fake_close)

    app = await asyncio.to_thread(app_module.create_app, config_path=cfg_path)
    async with app.router.lifespan_context(app):
        pass

    assert closed["value"] is True


@pytest.mark.asyncio
async def test_lifespan_startup_runtime_error_cleans_up(tmp_path: Path, monkeypatch) -> None:
    cfg_path = _write_config(tmp_path)
    monkeypatch.setenv("VIBESENSOR_SERVE_STATIC", "0")
    from vibesensor import app as app_module
    from vibesensor.app import bootstrap as bootstrap_mod

    async def _failing_start(self) -> None:
        raise RuntimeError("start failed")

    stop_calls = {"count": 0}

    async def _fake_stop(self) -> None:
        stop_calls["count"] += 1

    monkeypatch.setattr(bootstrap_mod.LifecycleManager, "start", _failing_start)
    monkeypatch.setattr(bootstrap_mod.LifecycleManager, "stop", _fake_stop)

    app = await asyncio.to_thread(app_module.create_app, config_path=cfg_path)

    with pytest.raises(RuntimeError, match="start failed"):
        async with app.router.lifespan_context(app):
            pass

    assert stop_calls["count"] == 1


@pytest.mark.asyncio
async def test_lifespan_startup_programmer_error_does_not_clean_up(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cfg_path = _write_config(tmp_path)
    monkeypatch.setenv("VIBESENSOR_SERVE_STATIC", "0")
    from vibesensor import app as app_module
    from vibesensor.app import bootstrap as bootstrap_mod

    async def _failing_start(self) -> None:
        raise TypeError("bad bootstrap wiring")

    stop_calls = {"count": 0}

    async def _fake_stop(self) -> None:
        stop_calls["count"] += 1

    monkeypatch.setattr(bootstrap_mod.LifecycleManager, "start", _failing_start)
    monkeypatch.setattr(bootstrap_mod.LifecycleManager, "stop", _fake_stop)

    app = await asyncio.to_thread(app_module.create_app, config_path=cfg_path)

    with pytest.raises(TypeError, match="bad bootstrap wiring"):
        async with app.router.lifespan_context(app):
            pass

    assert stop_calls["count"] == 0
