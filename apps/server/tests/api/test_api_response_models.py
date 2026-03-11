from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI

from vibesensor.routes import create_router


def _openapi_state() -> MagicMock:
    state = MagicMock()
    state.apply_car_settings = MagicMock()
    state.apply_speed_source_settings = MagicMock()
    return state


@pytest.fixture(scope="module")
def openapi_schema() -> dict:
    """Build the OpenAPI schema once for all tests in this module."""
    app = FastAPI()
    app.include_router(create_router(_openapi_state()))
    return app.openapi()


def _response_schema(openapi: dict, path: str, method: str = "get") -> dict:
    return openapi["paths"][path][method]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]


@pytest.mark.parametrize(
    ("path", "model"),
    [
        ("/api/health", "HealthResponse"),
        ("/api/settings/language", "LanguageResponse"),
        ("/api/settings/cars", "CarsResponse"),
        ("/api/update/status", "UpdateStatusResponse"),
    ],
    ids=["health", "language", "cars", "update_status"],
)
def test_openapi_uses_typed_response_model(openapi_schema: dict, path: str, model: str) -> None:
    schema = _response_schema(openapi_schema, path)
    assert schema == {"$ref": f"#/components/schemas/{model}"}


def test_openapi_component_shapes_are_not_generic_dict_for_typed_responses(
    openapi_schema: dict,
) -> None:
    components = openapi_schema["components"]["schemas"]

    assert components["HealthResponse"]["required"] == [
        "status",
        "startup_state",
        "startup_phase",
        "startup_error",
        "background_task_failures",
        "processing_state",
        "processing_failures",
        "processing_failure_categories",
        "processing_last_failure",
        "sample_rate_mismatch_count",
        "frame_size_mismatch_count",
        "degradation_reasons",
        "data_loss",
        "persistence",
        "intake_stats",
    ]
    assert components["LanguageResponse"]["required"] == ["language"]

    cars_properties = components["CarsResponse"]["properties"]
    assert cars_properties["cars"]["items"] == {"$ref": "#/components/schemas/CarResponse"}
    assert cars_properties["activeCarId"] == {
        "anyOf": [{"type": "string"}, {"type": "null"}],
        "title": "Activecarid",
    }

    history_list_properties = components["HistoryListResponse"]["properties"]
    assert history_list_properties["runs"]["items"] == {
        "$ref": "#/components/schemas/HistoryListEntryResponse",
    }

    update_status_properties = components["UpdateStatusResponse"]["properties"]
    assert update_status_properties["issues"]["items"] == {
        "$ref": "#/components/schemas/UpdateIssueResponse",
    }
    assert update_status_properties["runtime"] == {
        "$ref": "#/components/schemas/UpdateRuntimeResponse",
    }
    assert update_status_properties["phase_started_at"]["anyOf"][1] == {"type": "null"}
    assert update_status_properties["updated_at"]["anyOf"][1] == {"type": "null"}


# ---------------------------------------------------------------------------
# Fix 3+8: EspFlashStartRequest model_validator rejects missing port
# ---------------------------------------------------------------------------


def test_esp_flash_start_request_requires_port_when_not_auto_detect() -> None:
    """EspFlashStartRequest must reject auto_detect=False with no port (Fix 8)."""
    import pytest
    from pydantic import ValidationError

    from vibesensor.api_models import EspFlashStartRequest

    with pytest.raises(ValidationError):
        EspFlashStartRequest(port=None, auto_detect=False)

    with pytest.raises(ValidationError):
        EspFlashStartRequest(port="", auto_detect=False)

    # Valid: auto_detect=False with explicit port
    req = EspFlashStartRequest(port="/dev/ttyUSB0", auto_detect=False)
    assert req.port == "/dev/ttyUSB0"

    # Valid: auto_detect=True without port
    req = EspFlashStartRequest(port=None, auto_detect=True)
    assert req.auto_detect is True


# ---------------------------------------------------------------------------
# Fix 3: start_esp_flash catches ValueError and returns HTTP 400
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_esp_flash_start_returns_400_on_value_error() -> None:
    """start_esp_flash must map ValueError from esp_flash_manager.start → 400 (Fix 3)."""
    from fastapi import HTTPException

    from vibesensor.routes.updates import create_update_routes

    class _ValErrFlashManager:
        async def list_ports(self):
            return []

        def start(self, **_):
            raise ValueError("port is required when auto_detect is False")

        def cancel(self):
            return False

        def logs_since(self, _after):
            return {"lines": [], "next_after": 0}

        def history(self):
            return []

        @property
        def status(self):
            return type("S", (), {"to_dict": lambda self: {}})()

    state = MagicMock()
    state.esp_flash_manager = _ValErrFlashManager()
    router = create_update_routes(state.update_manager, state.esp_flash_manager)

    start_endpoint = None
    for route in router.routes:
        path_match = getattr(route, "path", "") == "/api/esp-flash/start"
        method_match = "POST" in getattr(route, "methods", set())
        if path_match and method_match:
            start_endpoint = route.endpoint
            break
    assert start_endpoint is not None

    req = type("R", (), {"port": None, "auto_detect": False})()
    with pytest.raises(HTTPException) as exc_info:
        await start_endpoint(req)
    assert exc_info.value.status_code == 400
