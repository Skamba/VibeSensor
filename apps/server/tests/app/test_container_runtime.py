"""Composition-root coverage: ``build_runtime()`` wires config into the lifecycle runtime."""

from __future__ import annotations

from pathlib import Path

import yaml

from vibesensor.app.composition import build_runtime
from vibesensor.app.config_loader import load_config


def test_build_runtime_projects_config_into_lifecycle_runtime(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "logging": {"history_db_path": str(tmp_path / "history.db")},
                "udp": {"data_host": "127.0.0.1", "data_port": 9100},
            },
        ),
        encoding="utf-8",
    )
    config = load_config(cfg_path)

    runtime = build_runtime(config)
    lifecycle = runtime.lifecycle
    try:
        assert lifecycle.history_db_path == tmp_path / "history.db"
        assert lifecycle.udp_data_host == "127.0.0.1"
        assert lifecycle.udp_data_port == 9100
        # Lifecycle and HTTP routes must share the same live collaborators.
        assert runtime.web.registry is lifecycle.registry
        assert runtime.web.control_plane is lifecycle.control_plane
        assert runtime.web.processor is lifecycle.processor
        assert runtime.web.run_recorder is lifecycle.run_recorder
        assert runtime.web.ws_broadcaster is lifecycle.ws_broadcaster
        assert runtime.web.health_state is lifecycle.health_state
        assert runtime.web.ingest_diagnostics is lifecycle.ingest_diagnostics
        assert runtime.web.update_manager is lifecycle.update_manager
        assert runtime.web.esp_flash_manager is lifecycle.esp_flash_manager
    finally:
        lifecycle.history_db.close()
