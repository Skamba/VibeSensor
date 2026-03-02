"""Tests that protect the routes package module structure.

These tests verify:
1. The routes package assembles all domain sub-routers correctly
2. Backward-compatible imports from vibesensor.api still work
3. Each route module is self-contained (imports resolve)
4. The assembled router exposes all expected endpoints
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest


class TestRoutesPackageStructure:
    """Verify the routes package has the expected modules."""

    EXPECTED_MODULES = {
        "_helpers",
        "car_library",
        "clients",
        "debug",
        "health",
        "history",
        "recording",
        "settings",
        "updates",
        "websocket",
    }

    def test_all_expected_modules_exist(self) -> None:
        import vibesensor.routes as pkg

        found = {mod.name for mod in pkgutil.iter_modules(pkg.__path__) if not mod.ispkg}
        assert self.EXPECTED_MODULES == found

    def test_create_router_importable_from_routes(self) -> None:
        from vibesensor.routes import create_router

        assert callable(create_router)

    def test_each_module_importable(self) -> None:
        for mod_name in self.EXPECTED_MODULES:
            mod = importlib.import_module(f"vibesensor.routes.{mod_name}")
            assert mod is not None


class TestBackwardCompatImports:
    """Verify that all symbols previously imported from vibesensor.api still work."""

    def test_create_router(self) -> None:
        from vibesensor.api import create_router

        assert callable(create_router)

    def test_safe_filename(self) -> None:
        from vibesensor.api import _safe_filename

        assert _safe_filename("hello world!") == "hello_world_"

    def test_flatten_for_csv(self) -> None:
        from vibesensor.api import _flatten_for_csv

        result = _flatten_for_csv({"record_type": "sample", "t_s": 1.0})
        assert result["record_type"] == "sample"

    def test_export_csv_columns(self) -> None:
        from vibesensor.api import _EXPORT_CSV_COLUMNS

        assert isinstance(_EXPORT_CSV_COLUMNS, tuple)
        assert "t_s" in _EXPORT_CSV_COLUMNS

    def test_bounded_sample(self) -> None:
        from vibesensor.api import _bounded_sample

        assert callable(_bounded_sample)

    def test_build_report_pdf(self) -> None:
        from vibesensor.api import build_report_pdf

        assert callable(build_report_pdf)

    def test_api_model_reexports(self) -> None:
        from vibesensor.api import (
            ActiveCarRequest,
            AnalysisSettingsRequest,
            AnalysisSettingsResponse,
            CarLibraryModelsResponse,
            CarUpsertRequest,
            SetLocationRequest,
            UpdateStartRequest,
        )

        for cls in [
            ActiveCarRequest,
            AnalysisSettingsRequest,
            AnalysisSettingsResponse,
            CarLibraryModelsResponse,
            CarUpsertRequest,
            SetLocationRequest,
            UpdateStartRequest,
        ]:
            assert cls is not None


class TestRouterEndpoints:
    """Verify that the assembled router exposes all expected URL paths."""

    EXPECTED_PATHS = [
        "/api/health",
        "/api/settings/cars",
        "/api/settings/speed-source",
        "/api/settings/speed-source/status",
        "/api/settings/sensors",
        "/api/settings/language",
        "/api/settings/speed-unit",
        "/api/analysis-settings",
        "/api/clients",
        "/api/client-locations",
        "/api/logging/status",
        "/api/logging/start",
        "/api/logging/stop",
        "/api/history",
        "/api/settings/update/status",
        "/api/settings/update/start",
        "/api/settings/update/cancel",
        "/api/settings/esp-flash/ports",
        "/api/settings/esp-flash/start",
        "/api/settings/esp-flash/status",
        "/api/settings/esp-flash/logs",
        "/api/settings/esp-flash/cancel",
        "/api/settings/esp-flash/history",
        "/api/car-library/brands",
        "/api/car-library/types",
        "/api/car-library/models",
        "/api/simulator/speed-override",
        "/ws",
    ]

    @pytest.fixture()
    def route_paths(self) -> set[str]:
        from dataclasses import dataclass, field
        from unittest.mock import MagicMock

        from vibesensor.routes import create_router

        @dataclass
        class _FakeState:
            config: object = field(default_factory=MagicMock)
            registry: object = field(default_factory=MagicMock)
            processor: object = field(default_factory=MagicMock)
            control_plane: object = field(default_factory=MagicMock)
            ws_hub: object = field(default_factory=MagicMock)
            gps_monitor: object = field(default_factory=MagicMock)
            analysis_settings: object = field(default_factory=MagicMock)
            metrics_logger: object = field(default_factory=MagicMock)
            live_diagnostics: object = field(default_factory=MagicMock)
            settings_store: object = field(default_factory=MagicMock)
            history_db: object = field(default_factory=MagicMock)
            update_manager: object = field(default_factory=MagicMock)
            esp_flash_manager: object = field(default_factory=MagicMock)
            processing_state: str = "idle"
            processing_failure_count: int = 0
            apply_car_settings: object = field(default_factory=MagicMock)
            apply_speed_source_settings: object = field(default_factory=MagicMock)

        router = create_router(_FakeState())
        return {r.path for r in router.routes}

    def test_all_expected_paths_present(self, route_paths: set[str]) -> None:
        missing = [p for p in self.EXPECTED_PATHS if p not in route_paths]
        assert not missing, f"Missing routes: {missing}"

    def test_no_duplicate_path_method_pairs(self, route_paths: set[str]) -> None:
        """Verify no two routes share the same (path, methods) combination."""
        from dataclasses import dataclass, field
        from unittest.mock import MagicMock

        from vibesensor.routes import create_router

        @dataclass
        class _FakeState:
            config: object = field(default_factory=MagicMock)
            registry: object = field(default_factory=MagicMock)
            processor: object = field(default_factory=MagicMock)
            control_plane: object = field(default_factory=MagicMock)
            ws_hub: object = field(default_factory=MagicMock)
            gps_monitor: object = field(default_factory=MagicMock)
            analysis_settings: object = field(default_factory=MagicMock)
            metrics_logger: object = field(default_factory=MagicMock)
            live_diagnostics: object = field(default_factory=MagicMock)
            settings_store: object = field(default_factory=MagicMock)
            history_db: object = field(default_factory=MagicMock)
            update_manager: object = field(default_factory=MagicMock)
            esp_flash_manager: object = field(default_factory=MagicMock)
            processing_state: str = "idle"
            processing_failure_count: int = 0
            apply_car_settings: object = field(default_factory=MagicMock)
            apply_speed_source_settings: object = field(default_factory=MagicMock)

        router = create_router(_FakeState())
        seen: set[tuple[str, str]] = set()
        dupes = []
        for r in router.routes:
            methods = getattr(r, "methods", None) or {"WS"}
            for method in methods:
                key = (r.path, method)
                if key in seen:
                    dupes.append(key)
                seen.add(key)
        assert not dupes, f"Duplicate (path, method) pairs: {dupes}"
