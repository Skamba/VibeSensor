"""Car-profile settings routes."""

from __future__ import annotations

import asyncio
from typing import cast

from fastapi import APIRouter, HTTPException

from vibesensor.adapters.http._helpers import (
    OpenAPIResponses,
    normalize_car_id_or_400,
)
from vibesensor.adapters.http.error_boundary import http_exception_for_value_error
from vibesensor.adapters.http.models.settings import ActiveCarRequest
from vibesensor.adapters.http.settings.dependencies import CarSettingsRouteDeps
from vibesensor.settings.car_config import CarConfigUpdatePayload, CarsSnapshot

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

    @router.get("/api/settings/cars", response_model=CarsSnapshot)
    async def get_cars() -> CarsSnapshot:
        """List all saved car profiles together with the currently active car ID."""

        return deps.car_settings.get_cars()

    @router.post("/api/settings/cars", response_model=CarsSnapshot)
    async def add_car(req: CarConfigUpdatePayload) -> CarsSnapshot:
        """Create a new car profile from the provided partial settings payload."""

        return await asyncio.to_thread(deps.car_settings.add_car, _provided_fields(req))

    @router.put(
        "/api/settings/cars/active",
        response_model=CarsSnapshot,
        responses=_CAR_NOT_FOUND_RESPONSES,
    )
    async def set_active_car(req: ActiveCarRequest) -> CarsSnapshot:
        """Select which saved car profile should drive current analysis settings."""

        car_id = normalize_car_id_or_400(req.car_id)
        try:
            return await asyncio.to_thread(deps.car_settings.set_active_car, car_id)
        except ValueError as exc:
            raise http_exception_for_value_error(exc, status_code=404) from exc

    @router.put(
        "/api/settings/cars/{car_id}",
        response_model=CarsSnapshot,
        responses=_CAR_NOT_FOUND_RESPONSES,
    )
    async def update_car(car_id: str, req: CarConfigUpdatePayload) -> CarsSnapshot:
        """Update an existing car profile while preserving unspecified fields."""

        normalized_car_id = normalize_car_id_or_400(car_id)
        try:
            return await asyncio.to_thread(
                deps.car_settings.update_car,
                normalized_car_id,
                _provided_fields(req),
            )
        except ValueError as exc:
            raise http_exception_for_value_error(exc, status_code=404) from exc

    @router.delete(
        "/api/settings/cars/{car_id}",
        response_model=CarsSnapshot,
        responses=_DELETE_CAR_RESPONSES,
    )
    async def delete_car(car_id: str) -> CarsSnapshot:
        """Delete a saved car profile when that removal keeps settings state valid."""

        normalized_car_id = normalize_car_id_or_400(car_id)
        cars_snapshot = await asyncio.to_thread(deps.car_settings.get_cars)
        if not any(car["id"] == normalized_car_id for car in cars_snapshot.cars):
            raise HTTPException(
                status_code=404,
                detail=f"Car {normalized_car_id!r} not found",
            )
        try:
            return await asyncio.to_thread(
                deps.car_settings.delete_car,
                normalized_car_id,
            )
        except ValueError as exc:
            raise http_exception_for_value_error(exc, status_code=400) from exc

    return router


def _provided_fields(request: CarConfigUpdatePayload) -> CarConfigUpdatePayload:
    """Drop explicit nulls so they leave the stored value unchanged, like omitted fields."""
    return cast(
        CarConfigUpdatePayload,
        {key: value for key, value in request.items() if value is not None},
    )
