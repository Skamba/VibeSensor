from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI

from vibesensor.api import create_router


def _openapi_schema() -> dict:
    app = FastAPI()
    app.include_router(create_router(MagicMock()))
    return app.openapi()


def _response_schema(openapi: dict, path: str, method: str = "get") -> dict:
    return openapi["paths"][path][method]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]


def test_openapi_uses_typed_response_models_for_core_settings_routes() -> None:
    openapi = _openapi_schema()

    health_schema = _response_schema(openapi, "/api/health")
    language_schema = _response_schema(openapi, "/api/settings/language")
    cars_schema = _response_schema(openapi, "/api/settings/cars")
    update_status_schema = _response_schema(openapi, "/api/settings/update/status")

    assert health_schema == {"$ref": "#/components/schemas/HealthResponse"}
    assert language_schema == {"$ref": "#/components/schemas/LanguageResponse"}
    assert cars_schema == {"$ref": "#/components/schemas/CarsResponse"}
    assert update_status_schema == {"$ref": "#/components/schemas/UpdateStatusResponse"}


def test_openapi_component_shapes_are_not_generic_dict_for_typed_responses() -> None:
    openapi = _openapi_schema()
    components = openapi["components"]["schemas"]

    assert components["HealthResponse"]["required"] == [
        "status",
        "processing_state",
        "processing_failures",
    ]
    assert components["LanguageResponse"]["required"] == ["language"]

    cars_properties = components["CarsResponse"]["properties"]
    assert cars_properties["cars"]["items"] == {"$ref": "#/components/schemas/CarResponse"}
    assert cars_properties["activeCarId"]["type"] == "string"

    update_status_properties = components["UpdateStatusResponse"]["properties"]
    assert update_status_properties["issues"]["items"] == {
        "$ref": "#/components/schemas/UpdateIssueResponse"
    }
