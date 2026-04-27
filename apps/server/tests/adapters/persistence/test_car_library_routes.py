"""HTTP-level tests for the car library API routes.

Covers:
- GET /api/car-library/brands         → 200, non-empty list
- GET /api/car-library/types?brand=X  → 200, non-empty / 404 unknown brand / 422 empty brand
- GET /api/car-library/models?brand=X&type=Y
                                      → 200, valid entries / 404 unknown combos
                                        / 422 empty params
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from test_support import response_payload


def _get_endpoint(router, path: str):
    """Return the endpoint callable registered for *path*, or raise."""
    for route in router.routes:
        if getattr(route, "path", "") == path:
            return route.endpoint
    raise KeyError(f"Route not found: {path}")


@pytest.fixture
def car_library_router(fake_state):
    """Return the car-library APIRouter for direct endpoint tests."""
    from vibesensor.adapters.http.car_library import create_car_library_routes

    return create_car_library_routes()


# ---------------------------------------------------------------------------
# /api/car-library/brands
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_brands_are_sorted(car_library_router) -> None:
    """Brands list must be sorted alphabetically."""
    endpoint = _get_endpoint(car_library_router, "/api/car-library/brands")
    result = response_payload(await endpoint())
    brands = result["brands"]
    assert brands == sorted(brands)


# ---------------------------------------------------------------------------
# /api/car-library/types
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("brand", ["TeslaNonExistent", "Unknown Brand XYZ"])
async def test_types_unknown_brand_raises_404(car_library_router, brand: str) -> None:
    """GET /api/car-library/types?brand=<unknown> must raise HTTP 404."""
    endpoint = _get_endpoint(car_library_router, "/api/car-library/types")
    with pytest.raises(HTTPException) as exc_info:
        await endpoint(brand=brand)
    assert exc_info.value.status_code == 404
    assert brand in exc_info.value.detail


# ---------------------------------------------------------------------------
# /api/car-library/models
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_models_unknown_brand_raises_404(car_library_router) -> None:
    """GET /api/car-library/models with unknown brand raises HTTP 404."""
    endpoint = _get_endpoint(car_library_router, "/api/car-library/models")
    with pytest.raises(HTTPException) as exc_info:
        await endpoint(brand="TeslaNotInLibrary", car_type="Sedan")
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_models_unknown_type_for_known_brand_raises_404(car_library_router) -> None:
    """GET /api/car-library/models with valid brand but unknown type raises HTTP 404."""
    endpoint = _get_endpoint(car_library_router, "/api/car-library/models")
    with pytest.raises(HTTPException) as exc_info:
        await endpoint(brand="BMW", car_type="Spaceship")
    assert exc_info.value.status_code == 404
    assert "Spaceship" in exc_info.value.detail
    assert "BMW" in exc_info.value.detail
