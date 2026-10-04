"""Route lookup helpers for FastAPI router trees.

Since FastAPI 0.137, ``include_router`` stores an ``_IncludedRouter`` wrapper in
``router.routes`` instead of flattening the included ``APIRoute`` objects, so
tests must walk the tree to find the routes they exercise.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Any

from fastapi.routing import APIRoute


def iter_api_routes(routes: Iterable[Any]) -> Iterator[APIRoute]:
    """Yield every ``APIRoute`` reachable from *routes*, depth first."""
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
            continue
        container = getattr(route, "original_router", route)
        nested = getattr(container, "routes", None)
        if nested is not None:
            yield from iter_api_routes(nested)


def response_payload(response: Any) -> Any:
    """JSON-ready payload of a route response model (or the value itself)."""
    if hasattr(response, "model_dump"):
        return response.model_dump(mode="json")
    return response
