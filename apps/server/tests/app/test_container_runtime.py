"""Composition-root coverage: ``build_runtime()`` wires config into the lifecycle runtime."""

from __future__ import annotations

from pathlib import Path

import yaml

from vibesensor.app.config_loader import load_config
from vibesensor.app.container import build_runtime


def test_build_runtime_projects_config_into_lifecycle_runtime(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "logging": {
                    "history_db_path": str(tmp_path / "history.db"),
                    "shutdown_analysis_timeout_s": 12.5,
                },
                "udp": {"data_host": "127.0.0.1", "data_port": 9100, "data_queue_maxsize": 321},
                "gps": {"gpsd_host": "gpsd.local", "gpsd_port": 2950},
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
        assert lifecycle.udp_data_queue_maxsize == 321
        assert lifecycle.gpsd_host == "gpsd.local"
        assert lifecycle.gpsd_port == 2950
        assert lifecycle.shutdown_analysis_timeout_s == 12.5
        # Lifecycle and HTTP routes must share the same live collaborators.
        assert runtime.router.live.registry is lifecycle.registry
        assert runtime.router.live.control_plane is lifecycle.control_plane
        assert runtime.router.live.processor is lifecycle.processor
        assert runtime.router.live.run_recorder is lifecycle.run_recorder
        assert runtime.router.live.ws_broadcaster is lifecycle.ws_broadcaster
        assert runtime.router.health.health_state is lifecycle.health_state
        assert runtime.router.health.ingest_diagnostics is lifecycle.ingest_diagnostics
        assert runtime.router.updates.update_manager is lifecycle.update_manager
        assert runtime.router.updates.esp_flash_manager is lifecycle.esp_flash_manager
    finally:
        lifecycle.history_db.close()
