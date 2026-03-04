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

_EXPECTED_MODULES = (
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
)

# Symbols that must remain importable from vibesensor.api (backward compat)
_CALLABLE_COMPAT_SYMBOLS = (
    "create_router",
    "_safe_filename",
    "_bounded_sample",
    "build_report_pdf",
)

_MODEL_COMPAT_SYMBOLS = (
    "ActiveCarRequest",
    "AnalysisSettingsRequest",
    "AnalysisSettingsResponse",
    "CarLibraryModelsResponse",
    "CarUpsertRequest",
    "SetLocationRequest",
    "UpdateStartRequest",
)


class TestRoutesPackageStructure:
    """Verify the routes package has the expected modules."""

    def test_all_expected_modules_exist(self) -> None:
        import vibesensor.routes as pkg

        found = {mod.name for mod in pkgutil.iter_modules(pkg.__path__) if not mod.ispkg}
        assert set(_EXPECTED_MODULES) == found

    def test_create_router_importable_from_routes(self) -> None:
        from vibesensor.routes import create_router

        assert callable(create_router)

    @pytest.mark.parametrize("mod_name", _EXPECTED_MODULES)
    def test_each_module_importable(self, mod_name: str) -> None:
        mod = importlib.import_module(f"vibesensor.routes.{mod_name}")
        assert mod is not None


class TestBackwardCompatImports:
    """Verify that all symbols previously imported from vibesensor.api still work."""

    @pytest.mark.parametrize("symbol", _CALLABLE_COMPAT_SYMBOLS)
    def test_callable_symbol(self, symbol: str) -> None:
        from vibesensor import api

        obj = getattr(api, symbol)
        assert callable(obj)

    def test_flatten_for_csv(self) -> None:
        from vibesensor.api import _flatten_for_csv

        result = _flatten_for_csv({"record_type": "sample", "t_s": 1.0})
        assert result["record_type"] == "sample"

    def test_export_csv_columns(self) -> None:
        from vibesensor.api import _EXPORT_CSV_COLUMNS

        assert isinstance(_EXPORT_CSV_COLUMNS, tuple)
        assert "t_s" in _EXPORT_CSV_COLUMNS

    @pytest.mark.parametrize("symbol", _MODEL_COMPAT_SYMBOLS)
    def test_api_model_reexport(self, symbol: str) -> None:
        from vibesensor import api

        assert getattr(api, symbol) is not None


_EXPECTED_PATHS = (
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
)


class TestRouterEndpoints:
    """Verify that the assembled router exposes all expected URL paths."""

    def test_all_expected_paths_present(self, route_paths: set[str]) -> None:
        missing = [p for p in _EXPECTED_PATHS if p not in route_paths]
        assert not missing, f"Missing routes: {missing}"

    def test_no_duplicate_path_method_pairs(self, fake_state) -> None:
        """Verify no two routes share the same (path, methods) combination."""
        from vibesensor.routes import create_router

        router = create_router(fake_state)
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
