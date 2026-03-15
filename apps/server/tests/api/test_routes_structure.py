"""Tests that protect the routes package module structure.

These tests verify:
1. The routes package assembles all domain sub-routers correctly
2. Each route module is self-contained (imports resolve)
3. The assembled router exposes all expected endpoints
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


class TestRoutesPackageStructure:
    """Verify the routes package has the expected modules."""

    def test_all_expected_modules_exist(self) -> None:
        import vibesensor.adapters.http as pkg
        found = {mod.name for mod in pkgutil.iter_modules(pkg.__path__) if not mod.ispkg}
        assert set(_EXPECTED_MODULES) == found

    def test_create_router_importable_from_routes(self) -> None:
        from vibesensor.adapters.http import create_router

        assert callable(create_router)

    @pytest.mark.parametrize("mod_name", _EXPECTED_MODULES)
    def test_each_module_importable(self, mod_name: str) -> None:
        mod = importlib.import_module(f"vibesensor.adapters.http.{mod_name}")
        assert mod is not None


_EXPECTED_PATHS = (
    "/api/health",
    "/api/settings/cars",
    "/api/settings/speed-source",
    "/api/settings/speed-source/status",
    "/api/settings/sensors",
    "/api/settings/language",
    "/api/settings/speed-unit",
    "/api/settings/analysis",
    "/api/clients",
    "/api/client-locations",
    "/api/recording/status",
    "/api/recording/start",
    "/api/recording/stop",
    "/api/history",
    "/api/update/status",
    "/api/update/start",
    "/api/update/cancel",
    "/api/esp-flash/ports",
    "/api/esp-flash/start",
    "/api/esp-flash/status",
    "/api/esp-flash/logs",
    "/api/esp-flash/cancel",
    "/api/esp-flash/history",
    "/api/car-library/brands",
    "/api/car-library/types",
    "/api/car-library/models",
    "/ws",
)


class TestRouterEndpoints:
    """Verify that the assembled router exposes all expected URL paths."""

    def test_all_expected_paths_present(self, route_paths: set[str]) -> None:
        missing = [p for p in _EXPECTED_PATHS if p not in route_paths]
        assert not missing, f"Missing routes: {missing}"

    def test_no_duplicate_path_method_pairs(self, fake_state) -> None:
        """Verify no two routes share the same (path, methods) combination."""
        from vibesensor.adapters.http import create_router

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
