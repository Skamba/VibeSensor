"""Settings endpoints – cars, sensors, speed source, language, unit, analysis."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

from vibesensor.adapters.http.models import (
    ActiveCarRequest,
    AnalysisSettingsRequest,
    AnalysisSettingsResponse,
    CarsResponse,
    CarUpsertRequest,
    LanguageRequest,
    LanguageResponse,
    SensorRequest,
    SensorsResponse,
    SpeedSourceRequest,
    SpeedSourceResponse,
    SpeedSourceStatusResponse,
    SpeedUnitRequest,
    SpeedUnitResponse,
)

from ._helpers import normalize_mac_or_400

if TYPE_CHECKING:
    from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor
    from vibesensor.infra.config.analysis_settings import AnalysisSettingsStore
    from vibesensor.infra.config.settings_store import SettingsStore


@contextmanager
def _value_error_to_http(status_code: int = 400) -> Iterator[None]:
    """Translate :class:`ValueError` into an :class:`HTTPException`."""
    try:
        yield
    except ValueError as exc:
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


def create_settings_routes(
    settings_store: SettingsStore,
    gps_monitor: GPSSpeedMonitor,
    analysis_settings: AnalysisSettingsStore,
) -> APIRouter:
    """Create and return the device-settings API routes."""
    router = APIRouter()

    # -- cars ------------------------------------------------------------------

    @router.get("/api/settings/cars", response_model=CarsResponse)
    async def get_cars() -> CarsResponse:
        return CarsResponse(**settings_store.get_cars())

    @router.post("/api/settings/cars", response_model=CarsResponse)
    async def add_car(req: CarUpsertRequest) -> CarsResponse:
        payload = req.model_dump(exclude_none=True)
        result = await asyncio.to_thread(settings_store.add_car, payload)
        return CarsResponse(**result)

    @router.put("/api/settings/cars/{car_id}", response_model=CarsResponse)
    async def update_car(car_id: str, req: CarUpsertRequest) -> CarsResponse:
        payload = req.model_dump(exclude_none=True)
        with _value_error_to_http(404):
            result = await asyncio.to_thread(
                settings_store.update_car,
                car_id,
                payload,
            )
        return CarsResponse(**result)

    @router.delete("/api/settings/cars/{car_id}", response_model=CarsResponse)
    async def delete_car(car_id: str) -> CarsResponse:
        # Existence check first so unknown-car yields 404 while business-logic
        # errors (e.g. "cannot delete the last car") propagate as 400.
        cars_snapshot = await asyncio.to_thread(settings_store.get_cars)
        if not any(c.get("id") == car_id for c in cars_snapshot.get("cars", [])):
            raise HTTPException(status_code=404, detail=f"Car {car_id!r} not found")
        with _value_error_to_http():
            result = await asyncio.to_thread(settings_store.delete_car, car_id)
        return CarsResponse(**result)

    @router.post("/api/settings/cars/active", response_model=CarsResponse)
    async def set_active_car(req: ActiveCarRequest) -> CarsResponse:
        car_id = req.carId
        with _value_error_to_http(404):
            result = await asyncio.to_thread(settings_store.set_active_car, car_id)
        return CarsResponse(**result)

    # -- speed source ----------------------------------------------------------

    async def _apply_speed_source_update(req: SpeedSourceRequest) -> SpeedSourceResponse:
        payload = req.model_dump(exclude_none=True)
        result = await asyncio.to_thread(
            settings_store.update_speed_source,
            payload,
        )
        return SpeedSourceResponse(**result)

    @router.get("/api/settings/speed-source", response_model=SpeedSourceResponse)
    async def get_speed_source() -> SpeedSourceResponse:
        return SpeedSourceResponse(**settings_store.get_speed_source())

    @router.post("/api/settings/speed-source", response_model=SpeedSourceResponse)
    async def update_speed_source(req: SpeedSourceRequest) -> SpeedSourceResponse:
        return await _apply_speed_source_update(req)

    @router.get("/api/settings/speed-source/status", response_model=SpeedSourceStatusResponse)
    async def get_speed_source_status() -> SpeedSourceStatusResponse:
        return SpeedSourceStatusResponse(**gps_monitor.status_dict())

    # -- sensors ---------------------------------------------------------------

    def _sensors_response() -> SensorsResponse:
        return SensorsResponse(sensorsByMac=settings_store.get_sensors())

    @router.get("/api/settings/sensors", response_model=SensorsResponse)
    async def get_sensors() -> SensorsResponse:
        return _sensors_response()

    @router.post("/api/settings/sensors/{mac}", response_model=SensorsResponse)
    async def update_sensor(mac: str, req: SensorRequest) -> SensorsResponse:
        normalized_mac = normalize_mac_or_400(mac)
        payload = req.model_dump(exclude_none=True)
        with _value_error_to_http():
            await asyncio.to_thread(
                settings_store.set_sensor,
                normalized_mac,
                payload,
            )
        return _sensors_response()

    @router.delete("/api/settings/sensors/{mac}", response_model=SensorsResponse)
    async def delete_sensor(mac: str) -> SensorsResponse:
        normalized_mac = normalize_mac_or_400(mac)
        with _value_error_to_http():
            removed = await asyncio.to_thread(settings_store.remove_sensor, normalized_mac)
        if not removed:
            raise HTTPException(status_code=404, detail="Unknown sensor MAC")
        return _sensors_response()

    # -- language & units ------------------------------------------------------

    @router.get("/api/settings/language", response_model=LanguageResponse)
    async def get_language() -> LanguageResponse:
        return LanguageResponse(language=settings_store.language)

    @router.post("/api/settings/language", response_model=LanguageResponse)
    async def set_language(req: LanguageRequest) -> LanguageResponse:
        with _value_error_to_http():
            language = await asyncio.to_thread(settings_store.set_language, req.language)
        return LanguageResponse(language=language)

    @router.get("/api/settings/speed-unit", response_model=SpeedUnitResponse)
    async def get_speed_unit() -> SpeedUnitResponse:
        return SpeedUnitResponse(speedUnit=settings_store.speed_unit)

    @router.post("/api/settings/speed-unit", response_model=SpeedUnitResponse)
    async def set_speed_unit(req: SpeedUnitRequest) -> SpeedUnitResponse:
        with _value_error_to_http():
            unit = await asyncio.to_thread(settings_store.set_speed_unit, req.speedUnit)
        return SpeedUnitResponse(speedUnit=unit)

    # -- analysis settings -----------------------------------------------------

    @router.get("/api/settings/analysis", response_model=AnalysisSettingsResponse)
    async def get_analysis_settings() -> AnalysisSettingsResponse:
        return AnalysisSettingsResponse(**analysis_settings.snapshot())

    @router.post("/api/settings/analysis", response_model=AnalysisSettingsResponse)
    async def set_analysis_settings(req: AnalysisSettingsRequest) -> AnalysisSettingsResponse:
        changes = req.model_dump(exclude_none=True)
        if changes:
            with _value_error_to_http():
                await asyncio.to_thread(settings_store.update_active_car_aspects, changes)
        return AnalysisSettingsResponse(**analysis_settings.snapshot())

    return router
