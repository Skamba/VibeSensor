"""Car-profile settings routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from vibesensor.adapters.http._helpers import (
    OpenAPIResponses,
    normalize_car_id_or_400,
)
from vibesensor.adapters.http.error_boundary import http_exception_for_value_error
from vibesensor.adapters.http.models import (
    ActiveCarRequest,
    CarsResponse,
    CarUpsertRequest,
)
from vibesensor.adapters.http.settings.dependencies import CarSettingsRouteDeps
from vibesensor.shared.boundaries.settings import (
    car_config_update_payload_from_mapping,
    cars_response_payload,
)

_CAR_NOT_FOUND_RESPONSES: OpenAPIResponses = {
    400: {"description": "Invalid car identifier."},
    404: {"description": "Requested car profile was not found."},
}

_DELETE_CAR_RESPONSES: OpenAPIResponses = {
    400: {
        "description": (
            "Invalid car identifier or the requested deletion violates "
            "current settings constraints."
        )
    },
    404: {"description": "Requested car profile was not found."},
}


def create_car_settings_routes(deps: CarSettingsRouteDeps) -> APIRouter:
    """Create routes for car-profile settings."""

    router = APIRouter(tags=["settings"])

    @router.get("/api/settings/cars", response_model=CarsResponse)
    async def get_cars() -> CarsResponse:
        """List all saved car profiles together with the currently active car ID."""

        return CarsResponse.model_validate(cars_response_payload(deps.car_settings.get_cars()))

    @router.post("/api/settings/cars", response_model=CarsResponse)
    async def add_car(req: CarUpsertRequest) -> CarsResponse:
        """Create a new car profile from the provided partial settings payload."""

        payload = car_config_update_payload_from_mapping(req.model_dump(exclude_none=True))
        result = await asyncio.to_thread(deps.car_settings.add_car, payload)
        return CarsResponse.model_validate(cars_response_payload(result))

    @router.put(
        "/api/settings/cars/active",
        response_model=CarsResponse,
        responses=_CAR_NOT_FOUND_RESPONSES,
    )
    async def set_active_car(req: ActiveCarRequest) -> CarsResponse:
        """Select which saved car profile should drive current analysis settings."""

        car_id = normalize_car_id_or_400(req.car_id)
        try:
            result = await asyncio.to_thread(deps.car_settings.set_active_car, car_id)
        except ValueError as exc:
            raise http_exception_for_value_error(exc, status_code=404) from exc
        return CarsResponse.model_validate(cars_response_payload(result))

    @router.put(
        "/api/settings/cars/{car_id}",
        response_model=CarsResponse,
        responses=_CAR_NOT_FOUND_RESPONSES,
    )
    async def update_car(car_id: str, req: CarUpsertRequest) -> CarsResponse:
        """Update an existing car profile while preserving unspecified fields."""

        normalized_car_id = normalize_car_id_or_400(car_id)
        payload = car_config_update_payload_from_mapping(req.model_dump(exclude_none=True))
        try:
            result = await asyncio.to_thread(
                deps.car_settings.update_car,
                normalized_car_id,
                payload,
            )
        except ValueError as exc:
            raise http_exception_for_value_error(exc, status_code=404) from exc
        return CarsResponse.model_validate(cars_response_payload(result))

    @router.delete(
        "/api/settings/cars/{car_id}",
        response_model=CarsResponse,
        responses=_DELETE_CAR_RESPONSES,
    )
    async def delete_car(car_id: str) -> CarsResponse:
        """Delete a saved car profile when that removal keeps settings state valid."""

        normalized_car_id = normalize_car_id_or_400(car_id)
        cars_snapshot = await asyncio.to_thread(deps.car_settings.get_cars)
        if not any(car["id"] == normalized_car_id for car in cars_snapshot.cars):
            raise HTTPException(
                status_code=404,
                detail=f"Car {normalized_car_id!r} not found",
            )
        try:
            result = await asyncio.to_thread(
                deps.car_settings.delete_car,
                normalized_car_id,
            )
        except ValueError as exc:
            raise http_exception_for_value_error(exc, status_code=400) from exc
        return CarsResponse.model_validate(cars_response_payload(result))

    return router
