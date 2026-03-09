from __future__ import annotations

from typing import Any


def response_payload(response: Any) -> Any:
    if hasattr(response, "model_dump"):
        return response.model_dump(mode="json")
    return response
