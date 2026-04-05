"""Live WebSocket payload projection from runtime collaborators."""

from __future__ import annotations

from typing import TYPE_CHECKING

from vibesensor.infra.runtime.processing_tick import STALE_DATA_AGE_S
from vibesensor.infra.runtime.rotational_speeds import (
    build_rotational_speeds_payload,
    rotational_basis_speed_source,
)
from vibesensor.shared.boundaries.clients import snapshot_for_api
from vibesensor.shared.ports import (
    SensorMetadataReader,
    SettingsReader,
    SpeedProvider,
    SpeedSourceSettingsReader,
)
from vibesensor.shared.time_utils import utc_now_iso
from vibesensor.shared.types.payload_types import SCHEMA_VERSION, LiveWsPayload

if TYPE_CHECKING:
    from vibesensor.infra.processing import SignalProcessor
    from vibesensor.infra.runtime.registry import ClientRegistry


class LiveWsPayloadProjector:
    """Project runtime state into the shared live WebSocket payload."""

    __slots__ = (
        "_gps_enabled",
        "_gps_monitor",
        "_processor",
        "_registry",
        "_sensor_metadata_reader",
        "_settings_reader",
        "_speed_source_reader",
    )

    def __init__(
        self,
        *,
        registry: ClientRegistry,
        processor: SignalProcessor,
        gps_monitor: SpeedProvider,
        gps_enabled: bool,
        settings_reader: SettingsReader,
        speed_source_reader: SpeedSourceSettingsReader,
        sensor_metadata_reader: SensorMetadataReader | None = None,
    ) -> None:
        self._gps_enabled = gps_enabled
        self._registry = registry
        self._processor = processor
        self._gps_monitor = gps_monitor
        self._sensor_metadata_reader = sensor_metadata_reader
        self._settings_reader = settings_reader
        self._speed_source_reader = speed_source_reader

    def build_shared_payload(self, *, include_heavy: bool) -> LiveWsPayload:
        """Assemble the shared live payload before per-subscriber selection."""

        clients = snapshot_for_api(
            self._registry,
            include_metrics=False,
            sensor_metadata_reader=self._sensor_metadata_reader,
        )
        client_ids = [client["id"] for client in clients]
        fresh_ids = self._processor.clients_with_recent_data(
            client_ids,
            max_age_s=STALE_DATA_AGE_S,
        )

        resolution = self._gps_monitor.resolve_speed()
        speed_mps = resolution.speed_mps
        analysis_settings_snapshot = self._settings_reader.analysis_settings_snapshot()
        speed_source = self._speed_source_reader.speed_source_config()
        basis = rotational_basis_speed_source(
            str(speed_source.speed_source),
            gps_enabled=self._gps_enabled,
            resolution_source=resolution.source,
        )
        payload: LiveWsPayload = {
            "schema_version": SCHEMA_VERSION,
            "server_time": utc_now_iso(),
            "speed_mps": speed_mps,
            "clients": clients,
            "selected_client_id": None,
            "rotational_speeds": build_rotational_speeds_payload(
                basis_speed_source=basis,
                speed_mps=speed_mps,
                measured_engine_rpm=self._gps_monitor.engine_rpm,
                analysis_settings=analysis_settings_snapshot,
            ),
        }
        if include_heavy:
            payload["spectra"] = self._processor.multi_spectrum_payload(fresh_ids)
        return payload
