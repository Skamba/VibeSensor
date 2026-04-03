"""Settings endpoints – cars, sensors, speed source, language, unit, analysis."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException

from vibesensor.adapters.http._helpers import (
    OpenAPIResponses,
    normalize_car_id_or_400,
    normalize_mac_or_400,
)
from vibesensor.adapters.http.analysis_settings_request_codec import (
    analysis_settings_payload_from_request,
)
from vibesensor.adapters.http.error_boundary import route_errors_to_http
from vibesensor.adapters.http.models import (
    ActiveCarRequest,
    AnalysisSettingsRequest,
    AnalysisSettingsResponse,
    CarResponse,
    CarsResponse,
    CarUpsertRequest,
    LanguageRequest,
    LanguageResponse,
    ObdDeviceResponse,
    ObdPairRequest,
    ObdPairResponse,
    ObdScanResponse,
    ObdStatusResponse,
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
from vibesensor.shared.types.speed_source_config import (
    SpeedSourcePayload as BackendSpeedSourcePayload,
)
from vibesensor.shared.types.speed_source_config import SpeedSourceUpdatePayload

if TYPE_CHECKING:
    from vibesensor.adapters.gps.speed_status import SpeedSourceStatusSnapshot
    from vibesensor.adapters.http.dependencies import (
        ObdAdminServiceProtocol,
        SettingsSpeedServiceProtocol,
        SpeedSourceSettingsServiceProtocol,
    )
    from vibesensor.adapters.obd.models import ObdDeviceSnapshot, ObdStatusSnapshot
    from vibesensor.infra.config.settings_store import SettingsStore

_CAR_NOT_FOUND_RESPONSES: OpenAPIResponses = {
    400: {"description": "Invalid car identifier."},
    404: {"description": "Requested car profile was not found."},
}

_DELETE_CAR_RESPONSES: OpenAPIResponses = {
    400: {
        "description": (
            "Invalid car identifier or the requested deletion violates "
            "current settings constraints."
        )
    },
    404: {"description": "Requested car profile was not found."},
}

_UPDATE_SPEED_SOURCE_RESPONSES: OpenAPIResponses = {
    400: {"description": "The requested speed-source configuration is invalid."},
}

_UPDATE_SENSOR_RESPONSES: OpenAPIResponses = {
    400: {"description": "Invalid sensor MAC address or sensor settings payload."},
    409: {"description": "Requested sensor location is already assigned to another sensor."},
}

_DELETE_SENSOR_RESPONSES: OpenAPIResponses = {
    400: {"description": "Invalid sensor MAC address."},
    404: {"description": "Sensor configuration not found for the given MAC address."},
}

_SET_LANGUAGE_RESPONSES: OpenAPIResponses = {
    400: {"description": "Unsupported language code."},
}

_SET_SPEED_UNIT_RESPONSES: OpenAPIResponses = {
    400: {"description": "Unsupported speed unit."},
}

_SET_ANALYSIS_SETTINGS_RESPONSES: OpenAPIResponses = {
    400: {"description": "Analysis settings are invalid or no active car is configured."},
}

_OBD_ADMIN_RESPONSES: OpenAPIResponses = {
    503: {"description": "Bluetooth OBD helper unavailable or the requested action failed."},
}


def create_settings_routes(
    settings_store: SettingsStore,
    speed_source_service: SpeedSourceSettingsServiceProtocol,
    speed_status_service: SettingsSpeedServiceProtocol,
    obd_admin_service: ObdAdminServiceProtocol,
) -> APIRouter:
    """Create and return the device-settings API routes."""
    router = APIRouter(tags=["settings"])

    def _car_response(payload: CarConfigPayload) -> CarResponse:
        return CarResponse(
            id=payload["id"],
            name=payload["name"],
            type=payload["type"],
            aspects=payload["aspects"],
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
            obd_device_mac=payload.get("obdDeviceMac"),
            obd_device_name=payload.get("obdDeviceName"),
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

    def _obd_device_response(snapshot: ObdDeviceSnapshot) -> ObdDeviceResponse:
        return ObdDeviceResponse(
            mac_address=snapshot.mac_address,
            name=snapshot.name,
            paired=snapshot.paired,
            trusted=snapshot.trusted,
            connected=snapshot.connected,
            rfcomm_channel=snapshot.rfcomm_channel,
        )

    def _obd_pair_response(
        *,
        configured_device_mac: str,
        configured_device_name: str | None,
        snapshot: ObdDeviceSnapshot,
    ) -> ObdPairResponse:
        return ObdPairResponse(
            configured_device_mac=configured_device_mac,
            configured_device_name=configured_device_name,
            paired=snapshot.paired,
            trusted=snapshot.trusted,
            connected=snapshot.connected,
            rfcomm_channel=snapshot.rfcomm_channel,
        )

    def _obd_status_response(snapshot: ObdStatusSnapshot) -> ObdStatusResponse:
        return ObdStatusResponse(
            configured_device_mac=snapshot.configured_device_mac,
            configured_device_name=snapshot.configured_device_name,
            connection_state=snapshot.connection_state,
            device_mac=snapshot.device_mac,
            device_name=snapshot.device_name,
            paired=snapshot.paired,
            trusted=snapshot.trusted,
            connected=snapshot.connected,
            rfcomm_channel=snapshot.rfcomm_channel,
            last_sample_age_s=snapshot.last_sample_age_s,
            last_speed_kmh=snapshot.last_speed_kmh,
            last_rpm=snapshot.last_rpm,
            rpm_sample_age_s=snapshot.rpm_sample_age_s,
            rpm_target_interval_ms=snapshot.rpm_target_interval_ms,
            rpm_effective_hz=snapshot.rpm_effective_hz,
            request_rtt_ms=snapshot.request_rtt_ms,
            timeout_count=snapshot.timeout_count,
            error_count=snapshot.error_count,
            poll_mode=snapshot.poll_mode,
            backoff_active=snapshot.backoff_active,
            last_error=snapshot.last_error,
            last_raw_response=snapshot.last_raw_response,
            reconnect_delay_s=snapshot.reconnect_delay_s,
            debug_hint=snapshot.debug_hint,
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
        if req.obd_device_mac is not None:
            payload["obdDeviceMac"] = req.obd_device_mac
        if req.obd_device_name is not None:
            payload["obdDeviceName"] = req.obd_device_name
        return payload

    def _sensor_update_payload(req: SensorRequest) -> SensorConfigUpdatePayload:
        payload: SensorConfigUpdatePayload = {}
        if req.name is not None:
            payload["name"] = req.name
        if req.location_code is not None:
            payload["location_code"] = req.location_code
        return payload

    def _analysis_settings_response() -> AnalysisSettingsResponse:
        return AnalysisSettingsResponse.model_validate(
            asdict(settings_store.analysis_settings_snapshot())
        )

    # -- cars ------------------------------------------------------------------

    @router.get("/api/settings/cars", response_model=CarsResponse)
    async def get_cars() -> CarsResponse:
        """List all saved car profiles together with the currently active car ID."""
        return _cars_response(settings_store.get_cars())

    @router.post("/api/settings/cars", response_model=CarsResponse)
    async def add_car(req: CarUpsertRequest) -> CarsResponse:
        """Create a new car profile from the provided partial settings payload."""
        payload = _car_upsert_payload(req)
        result = await asyncio.to_thread(settings_store.add_car, payload)
        return _cars_response(result)

    @router.put(
        "/api/settings/cars/active",
        response_model=CarsResponse,
        responses=_CAR_NOT_FOUND_RESPONSES,
    )
    async def set_active_car(req: ActiveCarRequest) -> CarsResponse:
        """Select which saved car profile should drive current analysis settings."""
        car_id = normalize_car_id_or_400(req.car_id)
        with route_errors_to_http(catch_value_error=404):
            result = await asyncio.to_thread(settings_store.set_active_car, car_id)
        return _cars_response(result)

    @router.put(
        "/api/settings/cars/{car_id}",
        response_model=CarsResponse,
        responses=_CAR_NOT_FOUND_RESPONSES,
    )
    async def update_car(car_id: str, req: CarUpsertRequest) -> CarsResponse:
        """Update an existing car profile while preserving unspecified fields."""
        car_id = normalize_car_id_or_400(car_id)
        payload = _car_upsert_payload(req)
        with route_errors_to_http(catch_value_error=404):
            result = await asyncio.to_thread(
                settings_store.update_car,
                car_id,
                payload,
            )
        return _cars_response(result)

    @router.delete(
        "/api/settings/cars/{car_id}",
        response_model=CarsResponse,
        responses=_DELETE_CAR_RESPONSES,
    )
    async def delete_car(car_id: str) -> CarsResponse:
        """Delete a saved car profile when that removal keeps settings state valid."""
        car_id = normalize_car_id_or_400(car_id)
        # Existence check first so unknown-car yields 404 while business-logic
        # errors (e.g. "cannot delete the last car") propagate as 400.
        cars_snapshot = await asyncio.to_thread(settings_store.get_cars)
        if not any(car["id"] == car_id for car in cars_snapshot.cars):
            raise HTTPException(status_code=404, detail=f"Car {car_id!r} not found")
        with route_errors_to_http(catch_value_error=400):
            result = await asyncio.to_thread(settings_store.delete_car, car_id)
        return _cars_response(result)

    # -- speed source ----------------------------------------------------------

    @router.get("/api/settings/speed-source", response_model=SpeedSourceResponse)
    async def get_speed_source() -> SpeedSourceResponse:
        """Return the persisted speed-source configuration used for order tracking."""
        return _speed_source_response(speed_source_service.get_speed_source())

    @router.put(
        "/api/settings/speed-source",
        response_model=SpeedSourceResponse,
        responses=_UPDATE_SPEED_SOURCE_RESPONSES,
    )
    async def update_speed_source(req: SpeedSourceRequest) -> SpeedSourceResponse:
        """Update the preferred speed source, manual fallback speed, and staleness timeout."""
        payload = _speed_source_update_payload(req)
        with route_errors_to_http(catch_value_error=400):
            result = await asyncio.to_thread(
                speed_source_service.update_speed_source,
                payload,
            )
        return _speed_source_response(result)

    @router.get("/api/settings/speed-source/status", response_model=SpeedSourceStatusResponse)
    async def get_speed_source_status() -> SpeedSourceStatusResponse:
        """Return the live selected-speed-source connection state and effective speed status."""
        return _speed_source_status_response(speed_status_service.status_snapshot())

    @router.post(
        "/api/settings/obd/scan",
        response_model=ObdScanResponse,
        responses=_OBD_ADMIN_RESPONSES,
    )
    async def scan_obd_devices() -> ObdScanResponse:
        """Scan nearby Bluetooth OBD adapters using the privileged helper."""
        with route_errors_to_http():
            devices = await asyncio.to_thread(obd_admin_service.scan_obd_devices)
        return ObdScanResponse(devices=[_obd_device_response(device) for device in devices])

    @router.post(
        "/api/settings/obd/pair",
        response_model=ObdPairResponse,
        responses={400: {"description": "Invalid Bluetooth MAC address."}, **_OBD_ADMIN_RESPONSES},
    )
    async def pair_obd_device(req: ObdPairRequest) -> ObdPairResponse:
        """Pair, trust, connect, and persist the selected Bluetooth OBD adapter."""
        normalized_mac = normalize_mac_or_400(req.mac_address)
        with route_errors_to_http():
            device = await asyncio.to_thread(obd_admin_service.pair_obd_device, normalized_mac)
            persisted = await asyncio.to_thread(
                speed_source_service.update_speed_source,
                {
                    "obdDeviceMac": device.mac_address,
                    "obdDeviceName": device.name,
                },
            )
        return _obd_pair_response(
            configured_device_mac=str(persisted.get("obdDeviceMac") or device.mac_address),
            configured_device_name=(
                str(persisted.get("obdDeviceName"))
                if persisted.get("obdDeviceName") not in (None, "")
                else device.name
            ),
            snapshot=device,
        )

    @router.get("/api/settings/obd/status", response_model=ObdStatusResponse)
    async def get_obd_status() -> ObdStatusResponse:
        """Return detailed Bluetooth OBD runtime/admin status for diagnostics."""
        return _obd_status_response(await asyncio.to_thread(speed_status_service.obd_status))

    # -- sensors ---------------------------------------------------------------

    def _sensors_response() -> SensorsResponse:
        return SensorsResponse.model_validate({"sensors_by_mac": settings_store.get_sensors()})

    @router.get("/api/settings/sensors", response_model=SensorsResponse)
    async def get_sensors() -> SensorsResponse:
        """List persisted per-sensor settings keyed by normalized MAC address."""
        return _sensors_response()

    @router.post(
        "/api/settings/sensors/{mac}",
        response_model=SensorsResponse,
        responses=_UPDATE_SENSOR_RESPONSES,
    )
    async def update_sensor(mac: str, req: SensorRequest) -> SensorsResponse:
        """Create or update persisted sensor metadata for a specific MAC address."""
        normalized_mac = normalize_mac_or_400(mac)
        payload = _sensor_update_payload(req)
        with route_errors_to_http(catch_value_error=409):
            await asyncio.to_thread(
                settings_store.set_sensor,
                normalized_mac,
                payload,
            )
        return _sensors_response()

    @router.delete(
        "/api/settings/sensors/{mac}",
        response_model=SensorsResponse,
        responses=_DELETE_SENSOR_RESPONSES,
    )
    async def delete_sensor(mac: str) -> SensorsResponse:
        """Delete persisted sensor metadata for a specific MAC address."""
        normalized_mac = normalize_mac_or_400(mac)
        with route_errors_to_http(catch_value_error=400):
            removed = await asyncio.to_thread(settings_store.remove_sensor, normalized_mac)
        if not removed:
            raise HTTPException(status_code=404, detail="Unknown sensor MAC")
        return _sensors_response()

    # -- language & units ------------------------------------------------------

    @router.get("/api/settings/language", response_model=LanguageResponse)
    async def get_language() -> LanguageResponse:
        """Return the currently selected dashboard language code."""
        return LanguageResponse(language=settings_store.language)

    @router.put(
        "/api/settings/language",
        response_model=LanguageResponse,
        responses=_SET_LANGUAGE_RESPONSES,
    )
    async def set_language(req: LanguageRequest) -> LanguageResponse:
        """Update the dashboard language used by the local UI."""
        with route_errors_to_http(catch_value_error=400):
            language = await asyncio.to_thread(settings_store.set_language, req.language)
        return LanguageResponse(language=language)

    @router.get("/api/settings/speed-unit", response_model=SpeedUnitResponse)
    async def get_speed_unit() -> SpeedUnitResponse:
        """Return the speed unit currently used for UI display and input."""
        return SpeedUnitResponse(speed_unit=settings_store.speed_unit)

    @router.put(
        "/api/settings/speed-unit",
        response_model=SpeedUnitResponse,
        responses=_SET_SPEED_UNIT_RESPONSES,
    )
    async def set_speed_unit(req: SpeedUnitRequest) -> SpeedUnitResponse:
        """Update the speed unit used for UI display and manual speed entry."""
        with route_errors_to_http(catch_value_error=400):
            unit = await asyncio.to_thread(settings_store.set_speed_unit, req.speed_unit)
        return SpeedUnitResponse(speed_unit=unit)

    # -- analysis settings -----------------------------------------------------

    @router.get("/api/settings/analysis", response_model=AnalysisSettingsResponse)
    async def get_analysis_settings() -> AnalysisSettingsResponse:
        """Return the validated analysis settings derived from the active car profile."""
        return _analysis_settings_response()

    @router.put(
        "/api/settings/analysis",
        response_model=AnalysisSettingsResponse,
        responses=_SET_ANALYSIS_SETTINGS_RESPONSES,
    )
    async def set_analysis_settings(req: AnalysisSettingsRequest) -> AnalysisSettingsResponse:
        """Update analysis-specific car aspects such as tire geometry and drivetrain ratios."""
        changes = analysis_settings_payload_from_request(req)
        if changes:
            with route_errors_to_http(catch_value_error=400):
                await asyncio.to_thread(settings_store.update_active_car_aspects, changes)
        return _analysis_settings_response()

    return router
