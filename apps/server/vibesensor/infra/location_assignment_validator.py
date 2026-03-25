"""Shared location-assignment validation for runtime and settings infrastructure."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

__all__ = ["AssignedLocation", "LocationAssignmentValidator"]


@dataclass(frozen=True, slots=True)
class AssignedLocation:
    owner_id: str
    owner_name: str
    location_code: str


class LocationAssignmentValidator:
    """Normalize registry locations and reject duplicate assignments."""

    __slots__ = ("_max_utf8_bytes",)

    def __init__(self, *, max_utf8_bytes: int = 64) -> None:
        self._max_utf8_bytes = max_utf8_bytes

    def normalize(self, location: str) -> str:
        clean = location.strip()
        encoded = clean.encode("utf-8", errors="ignore")
        if len(encoded) <= self._max_utf8_bytes:
            return clean
        return encoded[: self._max_utf8_bytes].decode("utf-8", errors="ignore")

    def validate_assignment(
        self,
        *,
        owner_id: str,
        location_code: str,
        assigned_locations: Iterable[AssignedLocation],
    ) -> None:
        if not location_code:
            return
        for assigned in assigned_locations:
            if assigned.owner_id == owner_id or assigned.location_code != location_code:
                continue
            conflict_name = assigned.owner_name or assigned.owner_id
            raise ValueError(
                f"Location '{location_code}' already assigned to {conflict_name}",
            )
