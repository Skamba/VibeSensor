"""Car library lookup endpoints – brands, types, models."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..api_models import (
    CarLibraryBrandsResponse,
    CarLibraryModelsResponse,
    CarLibraryTypesResponse,
)


def create_car_library_routes() -> APIRouter:
    """Create and return the car-library API routes."""
    from ..car_library import get_brands, get_models_for_brand_type, get_types_for_brand

    router = APIRouter()

    @router.get("/api/car-library/brands", response_model=CarLibraryBrandsResponse)
    async def get_car_library_brands() -> CarLibraryBrandsResponse:
        """Return all available car manufacturer brands from the library."""
        return CarLibraryBrandsResponse(brands=get_brands())

    @router.get("/api/car-library/types", response_model=CarLibraryTypesResponse)
    async def get_car_library_types(
        brand: str = Query(..., min_length=1),
    ) -> CarLibraryTypesResponse:
        """Return body types available for *brand*; 404 if the brand is unknown."""
        if brand not in get_brands():
            raise HTTPException(status_code=404, detail=f"Unknown brand: {brand!r}")
        return CarLibraryTypesResponse(types=get_types_for_brand(brand))

    @router.get("/api/car-library/models", response_model=CarLibraryModelsResponse)
    async def get_car_library_models(
        brand: str = Query(..., min_length=1),
        car_type: str = Query(..., min_length=1, alias="type"),
    ) -> CarLibraryModelsResponse:
        """Return library entries for *brand* + *type*; 404 if the combination is unknown."""
        if brand not in get_brands():
            raise HTTPException(status_code=404, detail=f"Unknown brand: {brand!r}")
        if car_type not in get_types_for_brand(brand):
            raise HTTPException(
                status_code=404,
                detail=f"Unknown type {car_type!r} for brand {brand!r}",
            )
        return CarLibraryModelsResponse(models=get_models_for_brand_type(brand, car_type))

    return router
