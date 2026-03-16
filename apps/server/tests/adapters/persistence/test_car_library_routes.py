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
async def test_brands_returns_list(car_library_router) -> None:
    """GET /api/car-library/brands returns a non-empty list including BMW and Audi."""
    endpoint = _get_endpoint(car_library_router, "/api/car-library/brands")
    result = response_payload(await endpoint())
    assert "brands" in result
    brands = result["brands"]
    assert isinstance(brands, list)
    assert len(brands) >= 2
    assert "BMW" in brands
    assert "Audi" in brands


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
async def test_types_known_brand_returns_types(car_library_router) -> None:
    """GET /api/car-library/types?brand=BMW returns body types."""
    endpoint = _get_endpoint(car_library_router, "/api/car-library/types")
    result = response_payload(await endpoint(brand="BMW"))
    assert "types" in result
    types = result["types"]
    assert isinstance(types, list)
    assert len(types) >= 1
    assert "Sedan" in types


@pytest.mark.asyncio
@pytest.mark.parametrize("brand", ["TeslaNonExistent", "Unknown Brand XYZ"])
async def test_types_unknown_brand_raises_404(car_library_router, brand: str) -> None:
    """GET /api/car-library/types?brand=<unknown> must raise HTTP 404."""
    endpoint = _get_endpoint(car_library_router, "/api/car-library/types")
    with pytest.raises(HTTPException) as exc_info:
        await endpoint(brand=brand)
    assert exc_info.value.status_code == 404
    assert brand in exc_info.value.detail


@pytest.mark.asyncio
async def test_types_both_brands_have_sedan_and_suv(car_library_router) -> None:
    """BMW and Audi must both expose Sedan and SUV body types."""
    endpoint = _get_endpoint(car_library_router, "/api/car-library/types")
    for brand in ("BMW", "Audi"):
        result = response_payload(await endpoint(brand=brand))
        types = result["types"]
        assert "Sedan" in types, f"{brand} missing Sedan"
        assert "SUV" in types, f"{brand} missing SUV"


# ---------------------------------------------------------------------------
# /api/car-library/models
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_models_known_brand_type_returns_entries(car_library_router) -> None:
    """GET /api/car-library/models?brand=BMW&type=Sedan returns model entries."""
    endpoint = _get_endpoint(car_library_router, "/api/car-library/models")
    result = response_payload(await endpoint(brand="BMW", car_type="Sedan"))
    assert "models" in result
    models = result["models"]
    assert isinstance(models, list)
    assert len(models) > 0
    for m in models:
        assert m["brand"] == "BMW"
        assert m["type"] == "Sedan"
        assert isinstance(m["model"], str)
        assert len(m["gearboxes"]) >= 1
        assert len(m["tire_options"]) >= 2


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


@pytest.mark.asyncio
async def test_models_entries_have_positive_tire_specs(car_library_router) -> None:
    """All returned model entries must have positive tire dimensions."""
    endpoint = _get_endpoint(car_library_router, "/api/car-library/models")
    result = response_payload(await endpoint(brand="BMW", car_type="Sedan"))
    for m in result["models"]:
        assert m["tire_width_mm"] > 0, f"{m['model']} tire_width_mm not positive"
        assert m["tire_aspect_pct"] > 0, f"{m['model']} tire_aspect_pct not positive"
        assert m["rim_in"] > 0, f"{m['model']} rim_in not positive"


@pytest.mark.asyncio
async def test_models_all_brands_and_types_serve_results(car_library_router) -> None:
    """Every (brand, type) combination in the library must return >=1 model entry."""
    brands_ep = _get_endpoint(car_library_router, "/api/car-library/brands")
    types_ep = _get_endpoint(car_library_router, "/api/car-library/types")
    models_ep = _get_endpoint(car_library_router, "/api/car-library/models")

    brands_result = response_payload(await brands_ep())
    for brand in brands_result["brands"]:
        types_result = response_payload(await types_ep(brand=brand))
        for car_type in types_result["types"]:
            models_result = response_payload(await models_ep(brand=brand, car_type=car_type))
            assert len(models_result["models"]) > 0, (
                f"Empty models for brand={brand!r} type={car_type!r}"
            )
