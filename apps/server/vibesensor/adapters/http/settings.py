"""Settings endpoints – cars, sensors, speed source, language, unit, analysis."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

from vibesensor.adapters.http._helpers import domain_errors_to_http, normalize_mac_or_400
from vibesensor.adapters.http.models import (
    ActiveCarRequest,
    AnalysisSettingsRequest,
    AnalysisSettingsResponse,
    CarResponse,
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
from vibesensor.shared.types.car_config import (
    CarConfigPayload,
    CarConfigUpdatePayload,
    CarsSnapshot,
)
from vibesensor.shared.types.sensor_config import SensorConfigUpdatePayload
from vibesensor.shared.types.settings_types import AnalysisSettingsPayload
from vibesensor.shared.types.speed_source_config import (
    SpeedSourcePayload as BackendSpeedSourcePayload,
)
from vibesensor.shared.types.speed_source_config import SpeedSourceUpdatePayload

if TYPE_CHECKING:
    from vibesensor.adapters.gps.gps_speed import GPSSpeedMonitor
    from vibesensor.adapters.gps.speed_status import SpeedSourceStatusSnapshot
    from vibesensor.infra.config.settings_store import SettingsStore


def create_settings_routes(
    settings_store: SettingsStore,
    gps_monitor: GPSSpeedMonitor,
) -> APIRouter:
    """Create and return the device-settings API routes."""
    router = APIRouter()

    def _car_response(payload: CarConfigPayload) -> CarResponse:
        return CarResponse(
            id=payload["id"],
            name=payload["name"],
            type=payload["type"],
            aspects=dict(payload["aspects"]),
            variant=payload.get("variant"),
        )

    def _cars_response(snapshot: CarsSnapshot) -> CarsResponse:
        return CarsResponse(
            cars=[_car_response(car) for car in snapshot.cars],
            active_car_id=snapshot.active_car_id,
        )

    def _speed_source_response(payload: BackendSpeedSourcePayload) -> SpeedSourceResponse:
        return SpeedSourceResponse(
            speed_source=payload["speedSource"],
            manual_speed_kph=payload["manualSpeedKph"],
            stale_timeout_s=payload["staleTimeoutS"],
        )

    def _speed_source_status_response(
        snapshot: SpeedSourceStatusSnapshot,
    ) -> SpeedSourceStatusResponse:
        return SpeedSourceStatusResponse(
            gps_enabled=snapshot.gps_enabled,
            connection_state=snapshot.connection_state,
            device=snapshot.device,
            fix_mode=snapshot.fix_mode,
            fix_dimension=snapshot.fix_dimension,
            speed_confidence=snapshot.speed_confidence,
            epx_m=snapshot.epx_m,
            epy_m=snapshot.epy_m,
            epv_m=snapshot.epv_m,
            last_update_age_s=snapshot.last_update_age_s,
            raw_speed_kmh=snapshot.raw_speed_kmh,
            effective_speed_kmh=snapshot.effective_speed_kmh,
            last_error=snapshot.last_error,
            reconnect_delay_s=snapshot.reconnect_delay_s,
            fallback_active=snapshot.fallback_active,
            speed_source=snapshot.speed_source,
            stale_timeout_s=snapshot.stale_timeout_s,
        )

    def _car_upsert_payload(req: CarUpsertRequest) -> CarConfigUpdatePayload:
        payload: CarConfigUpdatePayload = {}
        if req.name is not None:
            payload["name"] = req.name
        if req.type is not None:
            payload["type"] = req.type
        if req.aspects is not None:
            payload["aspects"] = req.aspects
        if req.variant is not None:
            payload["variant"] = req.variant
        return payload

    def _speed_source_update_payload(req: SpeedSourceRequest) -> SpeedSourceUpdatePayload:
        payload: SpeedSourceUpdatePayload = {}
        if req.speed_source is not None:
            payload["speedSource"] = req.speed_source
        if req.manual_speed_kph is not None:
            payload["manualSpeedKph"] = req.manual_speed_kph
        if req.stale_timeout_s is not None:
            payload["staleTimeoutS"] = req.stale_timeout_s
        return payload

    def _sensor_update_payload(req: SensorRequest) -> SensorConfigUpdatePayload:
        payload: SensorConfigUpdatePayload = {}
        if req.name is not None:
            payload["name"] = req.name
        if req.location_code is not None:
            payload["location_code"] = req.location_code
        return payload

    def _analysis_settings_payload(req: AnalysisSettingsRequest) -> AnalysisSettingsPayload:
        payload: AnalysisSettingsPayload = {}
        if req.tire_width_mm is not None:
            payload["tire_width_mm"] = req.tire_width_mm
        if req.tire_aspect_pct is not None:
            payload["tire_aspect_pct"] = req.tire_aspect_pct
        if req.rim_in is not None:
            payload["rim_in"] = req.rim_in
        if req.final_drive_ratio is not None:
            payload["final_drive_ratio"] = req.final_drive_ratio
        if req.current_gear_ratio is not None:
            payload["current_gear_ratio"] = req.current_gear_ratio
        if req.wheel_bandwidth_pct is not None:
            payload["wheel_bandwidth_pct"] = req.wheel_bandwidth_pct
        if req.driveshaft_bandwidth_pct is not None:
            payload["driveshaft_bandwidth_pct"] = req.driveshaft_bandwidth_pct
        if req.engine_bandwidth_pct is not None:
            payload["engine_bandwidth_pct"] = req.engine_bandwidth_pct
        if req.speed_uncertainty_pct is not None:
            payload["speed_uncertainty_pct"] = req.speed_uncertainty_pct
        if req.tire_diameter_uncertainty_pct is not None:
            payload["tire_diameter_uncertainty_pct"] = req.tire_diameter_uncertainty_pct
        if req.final_drive_uncertainty_pct is not None:
            payload["final_drive_uncertainty_pct"] = req.final_drive_uncertainty_pct
        if req.gear_uncertainty_pct is not None:
            payload["gear_uncertainty_pct"] = req.gear_uncertainty_pct
        if req.min_abs_band_hz is not None:
            payload["min_abs_band_hz"] = req.min_abs_band_hz
        if req.max_band_half_width_pct is not None:
            payload["max_band_half_width_pct"] = req.max_band_half_width_pct
        if req.tire_deflection_factor is not None:
            payload["tire_deflection_factor"] = req.tire_deflection_factor
        return payload

    def _analysis_settings_response() -> AnalysisSettingsResponse:
        return AnalysisSettingsResponse.model_validate(
            asdict(settings_store.analysis_settings_snapshot())
        )

    # -- cars ------------------------------------------------------------------

    @router.get("/api/settings/cars", response_model=CarsResponse)
    async def get_cars() -> CarsResponse:
        return _cars_response(settings_store.get_cars())

    @router.post("/api/settings/cars", response_model=CarsResponse)
    async def add_car(req: CarUpsertRequest) -> CarsResponse:
        payload = _car_upsert_payload(req)
        result = await asyncio.to_thread(settings_store.add_car, payload)
        return _cars_response(result)

    @router.put("/api/settings/cars/active", response_model=CarsResponse)
    async def set_active_car(req: ActiveCarRequest) -> CarsResponse:
        car_id = req.car_id
        with domain_errors_to_http(catch_value_error=404):
            result = await asyncio.to_thread(settings_store.set_active_car, car_id)
        return _cars_response(result)

    @router.put("/api/settings/cars/{car_id}", response_model=CarsResponse)
    async def update_car(car_id: str, req: CarUpsertRequest) -> CarsResponse:
        payload = _car_upsert_payload(req)
        with domain_errors_to_http(catch_value_error=404):
            result = await asyncio.to_thread(
                settings_store.update_car,
                car_id,
                payload,
            )
        return _cars_response(result)

    @router.delete("/api/settings/cars/{car_id}", response_model=CarsResponse)
    async def delete_car(car_id: str) -> CarsResponse:
        # Existence check first so unknown-car yields 404 while business-logic
        # errors (e.g. "cannot delete the last car") propagate as 400.
        cars_snapshot = await asyncio.to_thread(settings_store.get_cars)
        if not any(car["id"] == car_id for car in cars_snapshot.cars):
            raise HTTPException(status_code=404, detail=f"Car {car_id!r} not found")
        with domain_errors_to_http(catch_value_error=400):
            result = await asyncio.to_thread(settings_store.delete_car, car_id)
        return _cars_response(result)

    # -- speed source ----------------------------------------------------------

    async def _apply_speed_source_update(req: SpeedSourceRequest) -> SpeedSourceResponse:
        payload = _speed_source_update_payload(req)
        result = await asyncio.to_thread(
            settings_store.update_speed_source,
            payload,
        )
        return _speed_source_response(result)

    @router.get("/api/settings/speed-source", response_model=SpeedSourceResponse)
    async def get_speed_source() -> SpeedSourceResponse:
        return _speed_source_response(settings_store.get_speed_source())

    @router.put("/api/settings/speed-source", response_model=SpeedSourceResponse)
    async def update_speed_source(req: SpeedSourceRequest) -> SpeedSourceResponse:
        return await _apply_speed_source_update(req)

    @router.get("/api/settings/speed-source/status", response_model=SpeedSourceStatusResponse)
    async def get_speed_source_status() -> SpeedSourceStatusResponse:
        return _speed_source_status_response(gps_monitor.status_snapshot())

    # -- sensors ---------------------------------------------------------------

    def _sensors_response() -> SensorsResponse:
        return SensorsResponse.model_validate({"sensors_by_mac": settings_store.get_sensors()})

    @router.get("/api/settings/sensors", response_model=SensorsResponse)
    async def get_sensors() -> SensorsResponse:
        return _sensors_response()

    @router.post("/api/settings/sensors/{mac}", response_model=SensorsResponse)
    async def update_sensor(mac: str, req: SensorRequest) -> SensorsResponse:
        normalized_mac = normalize_mac_or_400(mac)
        payload = _sensor_update_payload(req)
        with domain_errors_to_http(catch_value_error=400):
            await asyncio.to_thread(
                settings_store.set_sensor,
                normalized_mac,
                payload,
            )
        return _sensors_response()

    @router.delete("/api/settings/sensors/{mac}", response_model=SensorsResponse)
    async def delete_sensor(mac: str) -> SensorsResponse:
        normalized_mac = normalize_mac_or_400(mac)
        with domain_errors_to_http(catch_value_error=400):
            removed = await asyncio.to_thread(settings_store.remove_sensor, normalized_mac)
        if not removed:
            raise HTTPException(status_code=404, detail="Unknown sensor MAC")
        return _sensors_response()

    # -- language & units ------------------------------------------------------

    @router.get("/api/settings/language", response_model=LanguageResponse)
    async def get_language() -> LanguageResponse:
        return LanguageResponse(language=settings_store.language)

    @router.put("/api/settings/language", response_model=LanguageResponse)
    async def set_language(req: LanguageRequest) -> LanguageResponse:
        with domain_errors_to_http(catch_value_error=400):
            language = await asyncio.to_thread(settings_store.set_language, req.language)
        return LanguageResponse(language=language)

    @router.get("/api/settings/speed-unit", response_model=SpeedUnitResponse)
    async def get_speed_unit() -> SpeedUnitResponse:
        return SpeedUnitResponse(speed_unit=settings_store.speed_unit)

    @router.put("/api/settings/speed-unit", response_model=SpeedUnitResponse)
    async def set_speed_unit(req: SpeedUnitRequest) -> SpeedUnitResponse:
        with domain_errors_to_http(catch_value_error=400):
            unit = await asyncio.to_thread(settings_store.set_speed_unit, req.speed_unit)
        return SpeedUnitResponse(speed_unit=unit)

    # -- analysis settings -----------------------------------------------------

    @router.get("/api/settings/analysis", response_model=AnalysisSettingsResponse)
    async def get_analysis_settings() -> AnalysisSettingsResponse:
        return _analysis_settings_response()

    @router.put("/api/settings/analysis", response_model=AnalysisSettingsResponse)
    async def set_analysis_settings(req: AnalysisSettingsRequest) -> AnalysisSettingsResponse:
        changes = _analysis_settings_payload(req)
        if changes:
            with domain_errors_to_http(catch_value_error=400):
                await asyncio.to_thread(settings_store.update_active_car_aspects, changes)
        return _analysis_settings_response()

    return router
