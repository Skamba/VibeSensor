"""Client listing, location assignment, identification, and removal endpoints."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

from ..api_models import (
    ClientLocationsResponse,
    ClientsResponse,
    IdentifyRequest,
    IdentifyResponse,
    RemoveClientResponse,
    SetClientLocationResponse,
    SetLocationRequest,
)
from ..locations import all_locations, label_for_code
from ..protocol import client_id_mac
from ._helpers import normalize_client_id_or_400

if TYPE_CHECKING:
    from ..registry import ClientRegistry
    from ..settings_store import SettingsStore
    from ..udp_control_tx import UDPControlPlane


def create_client_routes(
    registry: ClientRegistry,
    control_plane: UDPControlPlane,
    settings_store: SettingsStore,
) -> APIRouter:
    """Create and return the client-management API routes."""
    router = APIRouter()

    @router.get("/api/clients", response_model=ClientsResponse)
    async def get_clients() -> ClientsResponse:
        return {"clients": registry.snapshot_for_api()}

    @router.get("/api/client-locations", response_model=ClientLocationsResponse)
    async def get_client_locations() -> ClientLocationsResponse:
        return {"locations": all_locations()}

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
        return {"status": "sent", "cmd_seq": cmd_seq}

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

            conflict = next(
                (
                    row
                    for row in registry.snapshot_for_api()
                    if row["id"] != normalized_client_id and row.get("location") == code
                ),
                None,
            )
            if conflict is not None:
                other_name = conflict.get("name") or "another sensor"
                raise HTTPException(
                    status_code=409,
                    detail=f"Location already assigned to {other_name}",
                )

            updated = registry.set_name(normalized_client_id, label)
        else:
            # Empty location_code → clear the assignment
            updated = registry.clear_name(normalized_client_id)

        registry.set_location(normalized_client_id, code)
        mac = client_id_mac(updated.client_id)
        await asyncio.to_thread(settings_store.set_sensor, mac, {"location": code})
        return {
            "id": updated.client_id,
            "mac_address": mac,
            "location_code": code,
            "name": updated.name,
        }

    @router.delete("/api/clients/{client_id}", response_model=RemoveClientResponse)
    async def remove_client(client_id: str) -> RemoveClientResponse:
        normalized_client_id = normalize_client_id_or_400(client_id)
        removed = registry.remove_client(normalized_client_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Sensor not found")
        return {"id": normalized_client_id, "status": "removed"}

    return router
