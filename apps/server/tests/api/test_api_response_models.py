from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI

from vibesensor.api import create_router


@pytest.fixture(scope="module")
def openapi_schema() -> dict:
    """Build the OpenAPI schema once for all tests in this module."""
    app = FastAPI()
    app.include_router(create_router(MagicMock()))
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
        ("/api/settings/update/status", "UpdateStatusResponse"),
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
        "processing_state",
        "processing_failures",
    ]
    assert components["LanguageResponse"]["required"] == ["language"]

    cars_properties = components["CarsResponse"]["properties"]
    assert cars_properties["cars"]["items"] == {"$ref": "#/components/schemas/CarResponse"}
    assert cars_properties["activeCarId"] == {
        "anyOf": [{"type": "string"}, {"type": "null"}],
        "title": "Activecarid",
    }

    update_status_properties = components["UpdateStatusResponse"]["properties"]
    assert update_status_properties["issues"]["items"] == {
        "$ref": "#/components/schemas/UpdateIssueResponse"
    }
