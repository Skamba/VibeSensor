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
    CarResponse,
    CarsResponse,
    CarUpsertRequest,
)
from vibesensor.adapters.http.settings.dependencies import CarSettingsRouteDeps
from vibesensor.shared.types.car_config import (
    CarConfigPayload,
    CarConfigUpdatePayload,
    CarsSnapshot,
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


def _car_response(payload: CarConfigPayload) -> CarResponse:
    return CarResponse(
        id=payload["id"],
        name=payload["name"],
        type=payload["type"],
        aspects=payload["aspects"],
        variant=payload.get("variant"),
    )


def _cars_response(snapshot: CarsSnapshot) -> CarsResponse:
    return CarsResponse(
        cars=[_car_response(car) for car in snapshot.cars],
        active_car_id=snapshot.active_car_id,
    )


def _car_upsert_payload(req: CarUpsertRequest) -> CarConfigUpdatePayload:
    payload: CarConfigUpdatePayload = {}
    if req.name is not None:
        payload["name"] = req.name
    if req.type is not None:
        payload["type"] = req.type
    if req.aspects is not None:
        payload["aspects"] = req.aspects
    if req.variant is not None:
        payload["variant"] = req.variant
    return payload


def create_car_settings_routes(deps: CarSettingsRouteDeps) -> APIRouter:
    """Create routes for car-profile settings."""

    router = APIRouter(tags=["settings"])

    @router.get("/api/settings/cars", response_model=CarsResponse)
    async def get_cars() -> CarsResponse:
        """List all saved car profiles together with the currently active car ID."""

        return _cars_response(deps.car_settings.get_cars())

    @router.post("/api/settings/cars", response_model=CarsResponse)
    async def add_car(req: CarUpsertRequest) -> CarsResponse:
        """Create a new car profile from the provided partial settings payload."""

        payload = _car_upsert_payload(req)
        result = await asyncio.to_thread(deps.car_settings.add_car, payload)
        return _cars_response(result)

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
        return _cars_response(result)

    @router.put(
        "/api/settings/cars/{car_id}",
        response_model=CarsResponse,
        responses=_CAR_NOT_FOUND_RESPONSES,
    )
    async def update_car(car_id: str, req: CarUpsertRequest) -> CarsResponse:
        """Update an existing car profile while preserving unspecified fields."""

        normalized_car_id = normalize_car_id_or_400(car_id)
        payload = _car_upsert_payload(req)
        try:
            result = await asyncio.to_thread(
                deps.car_settings.update_car,
                normalized_car_id,
                payload,
            )
        except ValueError as exc:
            raise http_exception_for_value_error(exc, status_code=404) from exc
        return _cars_response(result)

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
        return _cars_response(result)

    return router
