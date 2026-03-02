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
    from ..app import RuntimeState


def create_client_routes(state: RuntimeState) -> APIRouter:
    router = APIRouter()

    @router.get("/api/clients", response_model=ClientsResponse)
    async def get_clients() -> ClientsResponse:
        return {"clients": state.registry.snapshot_for_api()}

    @router.get("/api/client-locations", response_model=ClientLocationsResponse)
    async def get_client_locations() -> ClientLocationsResponse:
        return {"locations": all_locations()}

    @router.post("/api/clients/{client_id}/identify", response_model=IdentifyResponse)
    async def identify_client(client_id: str, req: IdentifyRequest) -> IdentifyResponse:
        normalized = normalize_client_id_or_400(client_id)
        ok, cmd_seq = state.control_plane.send_identify(normalized, req.duration_ms)
        if not ok:
            raise HTTPException(status_code=404, detail="Client missing or no control address")
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
        if state.registry.get(normalized_client_id) is None:
            raise HTTPException(status_code=404, detail="Unknown client_id")

        code = req.location_code.strip()

        if code:
            label = label_for_code(code)
            if label is None:
                raise HTTPException(status_code=400, detail="Unknown location_code")

            for row in state.registry.snapshot_for_api():
                if row["id"] != normalized_client_id and row.get("location") == code:
                    other_name = row.get("name") or "another sensor"
                    raise HTTPException(
                        status_code=409,
                        detail=f"Location already assigned to {other_name}",
                    )

            updated = state.registry.set_name(normalized_client_id, label)
        else:
            # Empty location_code → clear the assignment
            updated = state.registry.clear_name(normalized_client_id)

        state.registry.set_location(normalized_client_id, code)
        mac = client_id_mac(updated.client_id)
        await asyncio.to_thread(state.settings_store.set_sensor, mac, {"location": code})
        return {
            "id": updated.client_id,
            "mac_address": mac,
            "location_code": code,
            "name": updated.name,
        }

    @router.delete("/api/clients/{client_id}", response_model=RemoveClientResponse)
    async def remove_client(client_id: str) -> RemoveClientResponse:
        normalized_client_id = normalize_client_id_or_400(client_id)
        removed = state.registry.remove_client(normalized_client_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Unknown client_id")
        return {"id": normalized_client_id, "status": "removed"}

    return router
