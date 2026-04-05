"""Sensor-metadata settings routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from vibesensor.adapters.http._helpers import (
    OpenAPIResponses,
    normalize_mac_or_400,
)
from vibesensor.adapters.http.error_boundary import http_exception_for_value_error
from vibesensor.adapters.http.models import SensorRequest, SensorsResponse
from vibesensor.adapters.http.settings.dependencies import SensorSettingsRouteDeps
from vibesensor.shared.boundaries.settings import (
    sensor_config_update_payload_from_mapping,
    sensors_response_payload,
)

_UPDATE_SENSOR_RESPONSES: OpenAPIResponses = {
    400: {"description": "Invalid sensor MAC address or sensor settings payload."},
    409: {"description": "Requested sensor location is already assigned to another sensor."},
}

_DELETE_SENSOR_RESPONSES: OpenAPIResponses = {
    400: {"description": "Invalid sensor MAC address."},
    404: {"description": "Sensor configuration not found for the given MAC address."},
}


def create_sensor_settings_routes(deps: SensorSettingsRouteDeps) -> APIRouter:
    """Create routes for persisted sensor metadata."""

    router = APIRouter(tags=["settings"])

    @router.get("/api/settings/sensors", response_model=SensorsResponse)
    async def get_sensors() -> SensorsResponse:
        """List persisted per-sensor settings keyed by normalized MAC address."""

        return SensorsResponse.model_validate(
            sensors_response_payload(deps.sensor_metadata_store.get_sensors())
        )

    @router.post(
        "/api/settings/sensors/{mac}",
        response_model=SensorsResponse,
        responses=_UPDATE_SENSOR_RESPONSES,
    )
    async def update_sensor(mac: str, req: SensorRequest) -> SensorsResponse:
        """Create or update persisted sensor metadata for a specific MAC address."""

        normalized_mac = normalize_mac_or_400(mac)
        payload = sensor_config_update_payload_from_mapping(req.model_dump(exclude_none=True))
        try:
            await asyncio.to_thread(
                deps.sensor_metadata_store.set_sensor,
                normalized_mac,
                payload,
            )
        except ValueError as exc:
            raise http_exception_for_value_error(exc, status_code=409) from exc
        return SensorsResponse.model_validate(
            sensors_response_payload(deps.sensor_metadata_store.get_sensors())
        )

    @router.delete(
        "/api/settings/sensors/{mac}",
        response_model=SensorsResponse,
        responses=_DELETE_SENSOR_RESPONSES,
    )
    async def delete_sensor(mac: str) -> SensorsResponse:
        """Delete persisted sensor metadata for a specific MAC address."""

        normalized_mac = normalize_mac_or_400(mac)
        try:
            removed = await asyncio.to_thread(
                deps.sensor_metadata_store.remove_sensor,
                normalized_mac,
            )
        except ValueError as exc:
            raise http_exception_for_value_error(exc, status_code=400) from exc
        if not removed:
            raise HTTPException(status_code=404, detail="Unknown sensor MAC")
        return SensorsResponse.model_validate(
            sensors_response_payload(deps.sensor_metadata_store.get_sensors())
        )

    return router
