"""Car library lookup endpoints – brands, types, models."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Query

from ..api_models import (
    CarLibraryBrandsResponse,
    CarLibraryModelsResponse,
    CarLibraryTypesResponse,
)

if TYPE_CHECKING:
    from ..app import RuntimeState


def create_car_library_routes(state: RuntimeState) -> APIRouter:
    router = APIRouter()

    @router.get("/api/car-library/brands", response_model=CarLibraryBrandsResponse)
    async def get_car_library_brands() -> CarLibraryBrandsResponse:
        from ..car_library import get_brands

        return {"brands": get_brands()}

    @router.get("/api/car-library/types", response_model=CarLibraryTypesResponse)
    async def get_car_library_types(brand: str = Query(...)) -> CarLibraryTypesResponse:
        from ..car_library import get_types_for_brand

        return {"types": get_types_for_brand(brand)}

    @router.get("/api/car-library/models", response_model=CarLibraryModelsResponse)
    async def get_car_library_models(
        brand: str = Query(...), car_type: str = Query(..., alias="type")
    ) -> CarLibraryModelsResponse:
        from ..car_library import get_models_for_brand_type

        return {"models": get_models_for_brand_type(brand, car_type)}

    return router
