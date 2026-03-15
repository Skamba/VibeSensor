"""Client listing, location assignment, identification, and removal endpoints."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

from vibesensor.adapters.http.models import (
    ClientLocationsResponse,
    ClientsResponse,
    IdentifyRequest,
    IdentifyResponse,
    RemoveClientResponse,
    SetClientLocationResponse,
    SetLocationRequest,
)
from vibesensor.adapters.udp.protocol import client_id_mac
from vibesensor.shared.utils.locations import all_locations, label_for_code

from ._helpers import normalize_client_id_or_400

if TYPE_CHECKING:
    from vibesensor.adapters.udp.control_tx import UDPControlPlane
    from vibesensor.infra.config.settings_store import SettingsStore
    from vibesensor.infra.processing.processor import SignalProcessor
    from vibesensor.infra.runtime.registry import ClientRegistry


def create_client_routes(
    registry: ClientRegistry,
    control_plane: UDPControlPlane,
    settings_store: SettingsStore,
    processor: SignalProcessor,
) -> APIRouter:
    """Create and return the client-management API routes."""
    router = APIRouter()

    @router.get("/api/clients", response_model=ClientsResponse)
    async def get_clients() -> ClientsResponse:
        active_ids = registry.active_client_ids()
        metrics = processor.all_latest_metrics(active_ids)
        return ClientsResponse(clients=registry.snapshot_for_api(metrics_by_client=metrics))

    @router.get("/api/client-locations", response_model=ClientLocationsResponse)
    async def get_client_locations() -> ClientLocationsResponse:
        return ClientLocationsResponse(locations=all_locations())

    @router.post("/api/clients/{client_id}/identify", response_model=IdentifyResponse)
    async def identify_client(client_id: str, req: IdentifyRequest) -> IdentifyResponse:
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
    )
    async def set_client_location(
        client_id: str,
        req: SetLocationRequest,
    ) -> SetClientLocationResponse:
        normalized_client_id = normalize_client_id_or_400(client_id)
        if registry.get(normalized_client_id) is None:
            raise HTTPException(status_code=404, detail="Sensor not found")

        code = req.location_code.strip()

        if code:
            label = label_for_code(code)
            if label is None:
                raise HTTPException(status_code=400, detail="Unknown location_code")

            try:
                registry.set_location(normalized_client_id, code)
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

            registry.set_name(normalized_client_id, label)
        else:
            # Empty location_code → clear the assignment
            registry.set_location(normalized_client_id, code)
            registry.clear_name(normalized_client_id)

        updated = registry.get(normalized_client_id)
        name = updated.name if updated else None
        mac = client_id_mac(normalized_client_id)
        await asyncio.to_thread(settings_store.set_sensor, mac, {"location_code": code})
        return SetClientLocationResponse(
            id=normalized_client_id,
            mac_address=mac,
            location_code=code,
            name=name,
        )

    @router.delete("/api/clients/{client_id}", response_model=RemoveClientResponse)
    async def remove_client(client_id: str) -> RemoveClientResponse:
        normalized_client_id = normalize_client_id_or_400(client_id)
        removed = registry.remove_client(normalized_client_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Sensor not found")
        return RemoveClientResponse(id=normalized_client_id, status="removed")

    return router
