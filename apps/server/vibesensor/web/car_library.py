"""Car library lookup endpoints – brands and their models."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from vibesensor.web._helpers import OpenAPIResponses
from vibesensor.web.models.car_library import (
    CarLibraryBrandsResponse,
    CarLibraryModelEntry,
    CarLibraryModelsResponse,
)

_CAR_LIBRARY_NOT_FOUND_RESPONSES: OpenAPIResponses = {
    404: {"description": "The requested brand does not exist."},
}


def create_car_library_routes() -> APIRouter:
    """Create and return the car-library API routes.

    The library is built on the first request, not at server start (it takes
    about a second on the Pi). The handlers are sync so FastAPI runs them in
    its thread pool, and that first build does not stall the event loop.
    """

    router = APIRouter(tags=["car-library"])

    @router.get("/api/car-library/brands", response_model=CarLibraryBrandsResponse)
    def get_car_library_brands() -> CarLibraryBrandsResponse:
        """Return all available car manufacturer brands from the library."""
        from vibesensor.settings.car_library import get_brands

        return CarLibraryBrandsResponse(brands=get_brands())

    @router.get(
        "/api/car-library/models",
        response_model=CarLibraryModelsResponse,
        responses=_CAR_LIBRARY_NOT_FOUND_RESPONSES,
    )
    def get_car_library_models(
        brand: str = Query(..., min_length=1, description="Manufacturer brand to look up."),
    ) -> CarLibraryModelsResponse:
        """Return every library model of *brand*, each with its body type; 404 if unknown."""
        from vibesensor.settings.car_library import get_brands, get_models_for_brand

        if brand not in get_brands():
            raise HTTPException(status_code=404, detail=f"Unknown brand: {brand!r}")
        return CarLibraryModelsResponse(
            models=[
                CarLibraryModelEntry.model_validate(model) for model in get_models_for_brand(brand)
            ]
        )

    return router
