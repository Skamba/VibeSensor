from __future__ import annotations

import pytest
from fastapi import FastAPI

from vibesensor.adapters.http.route_bundles import (
    create_health_route_bundle,
    create_history_route_bundle,
    create_live_route_bundle,
    create_settings_route_bundle,
    create_update_route_bundle,
)


@pytest.mark.parametrize(
    ("bundle_factory", "dep_attr", "expected_paths"),
    [
        (create_health_route_bundle, "health", {"/api/health"}),
        (
            create_settings_route_bundle,
            "settings",
            {"/api/settings/language", "/api/car-library/brands"},
        ),
        (
            create_live_route_bundle,
            "live",
            {
                "/api/clients",
                "/api/recording/status",
                "/ws",
            },
        ),
        (
            create_history_route_bundle,
            "history",
            {"/api/history", "/api/history/{run_id}/report.pdf"},
        ),
        (
            create_update_route_bundle,
            "updates",
            {"/api/update/status", "/api/esp-flash/status"},
        ),
    ],
)
def test_route_bundles_register_expected_domain_paths(
    fake_state,
    bundle_factory,
    dep_attr: str,
    expected_paths: set[str],
) -> None:
    router = bundle_factory(getattr(fake_state, dep_attr))

    paths = {route.path for route in router.routes if hasattr(route, "path")}

    assert expected_paths <= paths


def test_route_bundles_can_compose_smaller_subset_without_top_level_package(fake_state) -> None:
    app = FastAPI()
    app.include_router(create_health_route_bundle(fake_state.health))
    app.include_router(create_live_route_bundle(fake_state.live))

    paths = {route.path for route in app.routes if hasattr(route, "path")}

    assert "/api/health" in paths
    assert "/api/clients" in paths
    assert "/api/history" not in paths
