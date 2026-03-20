"""Client-management HTTP API models."""

from __future__ import annotations

from pydantic import BaseModel, Field

from vibesensor.shared.types.payload_types import ClientApiRow

from .base import _FrozenBase


class IdentifyRequest(_FrozenBase):
    """Request body for the ``/api/clients/{id}/identify`` endpoint."""

    duration_ms: int = Field(default=1500, ge=100, le=60_000)


class SetLocationRequest(_FrozenBase):
    """Request body for setting the sensor location code."""

    location_code: str = Field(min_length=0, max_length=64)


class ClientsResponse(BaseModel):
    """Response body listing all currently-connected sensor clients."""

    clients: list[ClientApiRow]


class LocationOptionResponse(BaseModel):
    """A single sensor-location option (code + human-readable label)."""

    code: str
    label: str


class ClientLocationsResponse(BaseModel):
    """Response body with available sensor-location options."""

    locations: list[LocationOptionResponse]


class IdentifyResponse(BaseModel):
    """Response body for a sensor identify (blink) command."""

    status: str
    cmd_seq: int | None = None


class SetClientLocationResponse(BaseModel):
    """Response body confirming the new location assignment for a client."""

    id: str
    mac_address: str
    location_code: str
    name: str


class RemoveClientResponse(BaseModel):
    """Response body confirming removal of a disconnected client."""

    id: str
    status: str
