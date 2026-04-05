"""Canonical boundary package for client API/WS payload projection."""

from .api_rows import (
    ClientSnapshotLike,
    ClientSnapshotSource,
    build_client_api_row,
    build_client_api_rows,
    snapshot_for_api,
)

__all__ = [
    "ClientSnapshotLike",
    "ClientSnapshotSource",
    "build_client_api_row",
    "build_client_api_rows",
    "snapshot_for_api",
]
