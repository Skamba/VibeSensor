"""Behavior-first app composition smoke coverage for ``create_app()``."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yaml
from fastapi.testclient import TestClient


def _write_config(tmp_path: Path) -> Path:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "logging": {
                    "history_db_path": str(tmp_path / "history.db"),
                },
            }
        ),
        encoding="utf-8",
    )
    return cfg_path


def _fake_app_runtime(router_deps: object) -> SimpleNamespace:
    return SimpleNamespace(
        lifecycle=SimpleNamespace(lifecycle_runtime=lambda: SimpleNamespace()),
        router=router_deps,
    )


def test_create_app_serves_composed_routes_with_fake_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_state,
) -> None:
    cfg_path = _write_config(tmp_path)
    history_runs = [
        {
            "run_id": "run-1",
            "status": "complete",
            "start_time_utc": "2026-01-01T00:00:00Z",
            "end_time_utc": "2026-01-01T00:01:00Z",
            "created_at": "2026-01-01T00:01:05Z",
            "sample_count": 3200,
        }
    ]
    fake_state.run_service = SimpleNamespace(
        list_runs=AsyncMock(return_value=history_runs),
        get_run=AsyncMock(),
        get_insights=AsyncMock(),
        delete_run=AsyncMock(),
    )

    monkeypatch.setenv("VIBESENSOR_SERVE_STATIC", "0")
    from vibesensor.app import bootstrap as app_module

    start_calls = {"count": 0}
    stop_calls = {"count": 0}

    class _FakeLifecycleManager:
        def __init__(self, *, runtime: object, start_udp_receiver: object) -> None:
            self.runtime = runtime
            self.start_udp_receiver = start_udp_receiver

        async def start(self) -> None:
            start_calls["count"] += 1

        async def stop(self) -> None:
            stop_calls["count"] += 1

    monkeypatch.setattr(
        app_module,
        "build_runtime",
        lambda _config: _fake_app_runtime(fake_state.router),
    )
    monkeypatch.setattr(app_module, "LifecycleManager", _FakeLifecycleManager)

    app = app_module.create_app(config_path=cfg_path)
    route_paths = {getattr(route, "path", "") for route in app.routes}
    assert {
        "/api/health",
        "/api/settings/language",
        "/api/history",
        "/api/update/status",
    }.issubset(route_paths)

    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        assert health.json()["startup_state"] == "ready"

        language = client.get("/api/settings/language")
        assert language.status_code == 200
        assert language.json() == {"language": "en"}

        history = client.get("/api/history")
        assert history.status_code == 200
        payload = history.json()
        assert payload["runs"][0]["run_id"] == "run-1"
        assert payload["runs"][0]["status"] == "complete"
        assert payload["runs"][0]["sample_count"] == 3200

    assert start_calls["count"] == 1
    assert stop_calls["count"] == 1


def test_create_app_reports_missing_static_build_clearly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_state,
) -> None:
    cfg_path = _write_config(tmp_path)
    package_dir = tmp_path / "pkg"
    package_dir.mkdir()
    monkeypatch.delenv("VIBESENSOR_SERVE_STATIC", raising=False)

    from vibesensor.app import bootstrap as app_module

    class _FakeLifecycleManager:
        def __init__(self, *, runtime: object, start_udp_receiver: object) -> None:
            self.runtime = runtime
            self.start_udp_receiver = start_udp_receiver

        async def start(self) -> None:
            return None

        async def stop(self) -> None:
            return None

    monkeypatch.setattr(
        app_module,
        "build_runtime",
        lambda _config: _fake_app_runtime(fake_state.router),
    )
    monkeypatch.setattr(app_module, "LifecycleManager", _FakeLifecycleManager)
    monkeypatch.setattr(app_module, "_PACKAGE_DIR", package_dir)

    with pytest.raises(RuntimeError, match="UI not built"):
        app_module.create_app(config_path=cfg_path)
