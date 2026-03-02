"""Settings endpoints – cars, sensors, speed source, language, unit, analysis."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

from ..api_models import (
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

if TYPE_CHECKING:
    from ..app import RuntimeState


def create_settings_routes(state: RuntimeState) -> APIRouter:
    router = APIRouter()

    # -- cars ------------------------------------------------------------------

    @router.get("/api/settings/cars", response_model=CarsResponse)
    async def get_cars() -> CarsResponse:
        return state.settings_store.get_cars()

    @router.post("/api/settings/cars", response_model=CarsResponse)
    async def add_car(req: CarUpsertRequest) -> CarsResponse:
        payload = req.model_dump(exclude_none=True)
        result = await asyncio.to_thread(state.settings_store.add_car, payload)
        state.apply_car_settings()
        return result

    @router.put("/api/settings/cars/{car_id}", response_model=CarsResponse)
    async def update_car(car_id: str, req: CarUpsertRequest) -> CarsResponse:
        try:
            payload = req.model_dump(exclude_none=True)
            result = await asyncio.to_thread(
                state.settings_store.update_car,
                car_id,
                payload,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        state.apply_car_settings()
        return result

    @router.delete("/api/settings/cars/{car_id}", response_model=CarsResponse)
    async def delete_car(car_id: str) -> CarsResponse:
        try:
            result = await asyncio.to_thread(state.settings_store.delete_car, car_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        state.apply_car_settings()
        return result

    @router.post("/api/settings/cars/active", response_model=CarsResponse)
    async def set_active_car(req: ActiveCarRequest) -> CarsResponse:
        car_id = req.carId
        try:
            result = await asyncio.to_thread(state.settings_store.set_active_car, car_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        state.apply_car_settings()
        return result

    # -- speed source ----------------------------------------------------------

    @router.get("/api/settings/speed-source", response_model=SpeedSourceResponse)
    async def get_speed_source() -> SpeedSourceResponse:
        return state.settings_store.get_speed_source()

    @router.post("/api/settings/speed-source", response_model=SpeedSourceResponse)
    async def update_speed_source(req: SpeedSourceRequest) -> SpeedSourceResponse:
        payload = req.model_dump(exclude_none=True)
        result = await asyncio.to_thread(
            state.settings_store.update_speed_source,
            payload,
        )
        state.apply_speed_source_settings()
        return result

    @router.get("/api/settings/speed-source/status", response_model=SpeedSourceStatusResponse)
    async def get_speed_source_status() -> SpeedSourceStatusResponse:
        return state.gps_monitor.status_dict()

    # -- sensors ---------------------------------------------------------------

    def _sensors_response() -> SensorsResponse:
        return {"sensorsByMac": state.settings_store.get_sensors()}

    @router.get("/api/settings/sensors", response_model=SensorsResponse)
    async def get_sensors() -> SensorsResponse:
        return _sensors_response()

    @router.post("/api/settings/sensors/{mac}", response_model=SensorsResponse)
    async def update_sensor(mac: str, req: SensorRequest) -> SensorsResponse:
        try:
            payload = req.model_dump(exclude_none=True)
            await asyncio.to_thread(
                state.settings_store.set_sensor,
                mac,
                payload,
            )
            return _sensors_response()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/api/settings/sensors/{mac}", response_model=SensorsResponse)
    async def delete_sensor(mac: str) -> SensorsResponse:
        try:
            removed = await asyncio.to_thread(state.settings_store.remove_sensor, mac)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not removed:
            raise HTTPException(status_code=404, detail="Unknown sensor MAC")
        return _sensors_response()

    # -- language & units ------------------------------------------------------

    @router.get("/api/settings/language", response_model=LanguageResponse)
    async def get_language() -> LanguageResponse:
        return {"language": state.settings_store.language}

    @router.post("/api/settings/language", response_model=LanguageResponse)
    async def set_language(req: LanguageRequest) -> LanguageResponse:
        try:
            language = await asyncio.to_thread(state.settings_store.set_language, req.language)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"language": language}

    @router.get("/api/settings/speed-unit", response_model=SpeedUnitResponse)
    async def get_speed_unit() -> SpeedUnitResponse:
        return {"speedUnit": state.settings_store.speed_unit}

    @router.post("/api/settings/speed-unit", response_model=SpeedUnitResponse)
    async def set_speed_unit(req: SpeedUnitRequest) -> SpeedUnitResponse:
        try:
            unit = await asyncio.to_thread(state.settings_store.set_speed_unit, req.speedUnit)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"speedUnit": unit}

    # -- analysis settings -----------------------------------------------------

    @router.get("/api/analysis-settings", response_model=AnalysisSettingsResponse)
    async def get_analysis_settings() -> AnalysisSettingsResponse:
        return state.analysis_settings.snapshot()

    @router.post("/api/analysis-settings", response_model=AnalysisSettingsResponse)
    async def set_analysis_settings(req: AnalysisSettingsRequest) -> AnalysisSettingsResponse:
        changes = req.model_dump(exclude_none=True)
        if changes:
            try:
                await asyncio.to_thread(state.settings_store.update_active_car_aspects, changes)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            state.apply_car_settings()
        return state.analysis_settings.snapshot()

    # -- simulator speed override (delegates to speed source) ------------------

    @router.post("/api/simulator/speed-override", response_model=SpeedSourceResponse)
    async def set_simulator_speed_override(req: SpeedSourceRequest) -> SpeedSourceResponse:
        return await update_speed_source(req)

    return router
