"""Bundled car-library data must always serialize through the HTTP response models.

These tests walk every bundled brand and model through the real FastAPI
routes (so ``response_model`` validation runs too). A data row that the
response models reject would otherwise surface on the device as an HTTP 500
from ``/api/car-library/models`` and leave the add-car wizard without models.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from vibesensor.settings.car_library import get_brands
from vibesensor.web.car_library import create_car_library_routes
from vibesensor.web.models.car_library import (
    CarLibraryBrandsResponse,
    CarLibraryModelsResponse,
)


@pytest.fixture(scope="module")
def car_library_client() -> Iterator[TestClient]:
    """Serve only the car-library routes; server errors surface as HTTP 500."""
    app = FastAPI()
    app.include_router(create_car_library_routes())
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def test_every_bundled_brand_and_model_passes_http_response_models(
    car_library_client: TestClient,
) -> None:
    """Every bundled brand/model returns 200 and validates against the response models."""
    brands_response = car_library_client.get("/api/car-library/brands")
    assert brands_response.status_code == 200, brands_response.text
    brands = CarLibraryBrandsResponse.model_validate(brands_response.json()).brands
    assert brands

    failures: list[str] = []
    model_count = 0
    for brand in brands:
        models_response = car_library_client.get("/api/car-library/models", params={"brand": brand})
        if models_response.status_code != 200:
            failures.append(f"models {brand!r}: HTTP {models_response.status_code}")
            continue
        models = CarLibraryModelsResponse.model_validate(models_response.json()).models
        if not models:
            failures.append(f"models {brand!r}: empty model list")
        model_count += len(models)

    assert not failures, "\n".join(failures)
    assert model_count > 0


def test_models_without_a_driven_final_drive_serve_gearboxes_with_unknown_final_drive(
    car_library_client: TestClient,
) -> None:
    """Rows that leave the final drive unresolved still offer their gearbox.

    Canonical rows keep an unpublished or unencodable final drive unresolved
    instead of guessing it. The gearbox is served with ``final_drive_ratio:
    null`` (and no final-drive confidence), so the car can be saved and the
    driveline order reports "not testable". A missing top gear is served the
    same way, and an EV never has one: its reduction ratio is the final drive.
    """
    unknown_fd_models: list[str] = []
    ev_gearboxes: list[str] = []
    for brand in get_brands():
        response = car_library_client.get("/api/car-library/models", params={"brand": brand})
        assert response.status_code == 200, f"{brand}: {response.text}"
        for model in response.json()["models"]:
            for variant in model["variants"]:
                assert variant["gearboxes"], (model["model"], variant["name"])
                for gearbox in variant["gearboxes"]:
                    # An unknown ratio is served as null, never with a confidence.
                    for ratio in ("final_drive_ratio", "top_gear_ratio"):
                        if gearbox[ratio] is None:
                            assert gearbox[f"{ratio}_confidence"] is None
                    if gearbox["final_drive_ratio"] is None:
                        unknown_fd_models.append(model["model"])
                    if gearbox["fuel_type"] == "EV":
                        assert gearbox["top_gear_ratio"] is None, (model["model"], variant["name"])
                        ev_gearboxes.append(gearbox["name"])

    # Audi TT RS Coupe (8S) is one of the rows whose final drive Audi does not publish.
    assert "TT RS Coupe (8S, 2016–2023)" in unknown_fd_models
    # The e-tron GT's rear 2-speed gearbox is an EV gearbox too: one reduction, no top gear.
    assert "2-speed automatic (rear) / single-speed (front)" in ev_gearboxes
