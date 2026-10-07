"""HTTP-level tests for the car library API routes.

Covers:
- GET /api/car-library/brands          → sorted brands
- GET /api/car-library/models?brand=X  → every model of the brand, by model / 404 unknown brand
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from test_support.routes import iter_api_routes, response_payload


def _get_endpoint(router, path: str):
    """Return the endpoint callable registered for *path*, or raise."""
    for route in iter_api_routes(router.routes):
        if getattr(route, "path", "") == path:
            return route.endpoint
    raise KeyError(f"Route not found: {path}")


@pytest.fixture
def car_library_router(fake_state):
    """Return the car-library APIRouter for direct endpoint tests."""
    from vibesensor.web.car_library import create_car_library_routes

    return create_car_library_routes()


# ---------------------------------------------------------------------------
# /api/car-library/brands
# ---------------------------------------------------------------------------


def test_brands_are_sorted(car_library_router) -> None:
    """Brands list must be sorted alphabetically."""
    endpoint = _get_endpoint(car_library_router, "/api/car-library/brands")
    result = response_payload(endpoint())
    brands = result["brands"]
    assert brands == sorted(brands)


# ---------------------------------------------------------------------------
# /api/car-library/models
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("brand", ["TeslaNonExistent", "Unknown Brand XYZ"])
def test_models_unknown_brand_raises_404(car_library_router, brand: str) -> None:
    """GET /api/car-library/models?brand=<unknown> must raise HTTP 404."""
    endpoint = _get_endpoint(car_library_router, "/api/car-library/models")
    with pytest.raises(HTTPException) as exc_info:
        endpoint(brand=brand)
    assert exc_info.value.status_code == 404
    assert brand in exc_info.value.detail


def test_models_list_every_body_type_of_the_brand_by_model(car_library_router) -> None:
    """One list per brand: every body type, each entry naming its own, sorted by model."""
    endpoint = _get_endpoint(car_library_router, "/api/car-library/models")
    models = response_payload(endpoint(brand="BMW"))["models"]
    assert {entry["brand"] for entry in models} == {"BMW"}
    assert len({entry["type"] for entry in models}) > 1
    bases = [entry["model"].split(" (")[0].casefold() for entry in models]
    assert bases == sorted(bases)
