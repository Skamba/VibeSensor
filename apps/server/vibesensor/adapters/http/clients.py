"""Client listing, location assignment, identification, and removal endpoints."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from vibesensor.adapters.http._helpers import (
    OpenAPIResponses,
    normalize_client_id_or_400,
)
from vibesensor.adapters.http.dependencies import (
    ClientControlPlaneProtocol,
    ClientProcessorProtocol,
    ClientRegistryProtocol,
)
from vibesensor.adapters.http.error_boundary import http_exception_for_value_error
from vibesensor.adapters.http.models import (
    ClientLocationsResponse,
    ClientsResponse,
    IdentifyRequest,
    IdentifyResponse,
    LocationOptionResponse,
    RemoveClientResponse,
    SetClientLocationResponse,
    SetLocationRequest,
)
from vibesensor.adapters.udp.protocol import client_id_mac
from vibesensor.shared.boundaries.clients import snapshot_for_api
from vibesensor.shared.locations import all_locations
from vibesensor.shared.ports import SensorMetadataStore
from vibesensor.shared.sensor_metadata import resolve_sensor_presentation
from vibesensor.shared.types.sensor_config import SensorConfigPayload

_IDENTIFY_CLIENT_RESPONSES: OpenAPIResponses = {
    400: {"description": "Invalid sensor identifier."},
    404: {"description": "Sensor not found."},
    503: {"description": "Sensor is known but not currently reachable."},
}

_SET_CLIENT_LOCATION_RESPONSES: OpenAPIResponses = {
    400: {"description": "Invalid sensor identifier or unknown location code."},
    404: {"description": "Sensor not found."},
    409: {"description": "Requested location is already assigned to another sensor."},
}

_REMOVE_CLIENT_RESPONSES: OpenAPIResponses = {
    400: {"description": "Invalid sensor identifier."},
    404: {"description": "Sensor not found."},
}


def create_client_routes(
    registry: ClientRegistryProtocol,
    control_plane: ClientControlPlaneProtocol,
    sensor_settings_store: SensorMetadataStore,
    processor: ClientProcessorProtocol,
) -> APIRouter:
    """Create and return the client-management API routes."""
    router = APIRouter(tags=["clients"])

    @router.get("/api/clients", response_model=ClientsResponse)
    async def get_clients() -> ClientsResponse:
        """List known sensor clients with live connection state and latest computed metrics."""
        active_ids = registry.active_client_ids()
        metrics = processor.all_latest_metrics(active_ids)
        return ClientsResponse(
            clients=snapshot_for_api(
                registry,
                metrics_by_client=metrics,
                sensor_metadata_reader=sensor_settings_store,
            ),
        )

    @router.get("/api/client-locations", response_model=ClientLocationsResponse)
    async def get_client_locations() -> ClientLocationsResponse:
        """List the supported sensor location codes that operators can assign to clients."""
        return ClientLocationsResponse(
            locations=[
                LocationOptionResponse.model_validate(location) for location in all_locations()
            ]
        )

    @router.post(
        "/api/clients/{client_id}/identify",
        response_model=IdentifyResponse,
        responses=_IDENTIFY_CLIENT_RESPONSES,
    )
    async def identify_client(client_id: str, req: IdentifyRequest) -> IdentifyResponse:
        """Send a temporary identify/blink command so an operator can find a sensor physically."""
        normalized = normalize_client_id_or_400(client_id)
        # Distinguish "sensor never seen" (404) from "sensor known but not
        # currently connected" (503) so callers can react appropriately.
        if registry.get(normalized) is None:
            raise HTTPException(status_code=404, detail="Sensor not found")
        ok, cmd_seq = control_plane.send_identify(normalized, req.duration_ms)
        if not ok:
            raise HTTPException(status_code=503, detail="Sensor is not currently reachable")
        return IdentifyResponse(status="sent", cmd_seq=cmd_seq)

    @router.post(
        "/api/clients/{client_id}/location",
        response_model=SetClientLocationResponse,
        responses=_SET_CLIENT_LOCATION_RESPONSES,
    )
    async def set_client_location(
        client_id: str,
        req: SetLocationRequest,
    ) -> SetClientLocationResponse:
        """Assign or clear the logical location for a sensor and persist the updated mapping."""
        normalized_client_id = normalize_client_id_or_400(client_id)
        if registry.get(normalized_client_id) is None:
            raise HTTPException(status_code=404, detail="Sensor not found")

        updated = registry.get(normalized_client_id)
        try:
            stored = await asyncio.to_thread(
                sensor_settings_store.assign_sensor_location,
                normalized_client_id,
                req.location_code,
            )
        except ValueError as exc:
            status_code = 400 if str(exc) == "Unknown location_code" else 409
            raise http_exception_for_value_error(exc, status_code=status_code) from exc
        stored_sensor = stored.get(normalized_client_id)
        code = str(stored_sensor["location_code"] if stored_sensor is not None else "").strip()
        await asyncio.to_thread(registry.set_location, normalized_client_id, code)
        if code:
            await asyncio.to_thread(
                registry.set_name,
                normalized_client_id,
                str(stored_sensor["name"] if stored_sensor is not None else "").strip(),
            )
        else:
            await asyncio.to_thread(registry.clear_name, normalized_client_id)
        mac = client_id_mac(normalized_client_id)
        fallback_sensor: SensorConfigPayload = {
            "name": normalized_client_id,
            "location_code": code,
        }
        stored_sensor = stored_sensor or fallback_sensor
        fallback_name = updated.name if updated and updated.name is not None else ""
        name, _ = resolve_sensor_presentation(
            sensor_id=normalized_client_id,
            sensors_by_mac={normalized_client_id: stored_sensor},
            fallback_name=fallback_name,
            fallback_location_code=code,
        )
        return SetClientLocationResponse(
            id=normalized_client_id,
            mac_address=mac,
            location_code=code,
            name=name,
        )

    @router.delete(
        "/api/clients/{client_id}",
        response_model=RemoveClientResponse,
        responses=_REMOVE_CLIENT_RESPONSES,
    )
    async def remove_client(client_id: str) -> RemoveClientResponse:
        """Remove a disconnected sensor from the runtime registry."""
        normalized_client_id = normalize_client_id_or_400(client_id)
        removed = await asyncio.to_thread(registry.remove_client, normalized_client_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Sensor not found")
        return RemoveClientResponse(id=normalized_client_id, status="removed")

    return router
