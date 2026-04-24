from __future__ import annotations

from unittest.mock import MagicMock

from vibesensor.domain import AnalysisSettingsSnapshot
from vibesensor.infra.runtime.client_snapshot import ClientSnapshot
from vibesensor.infra.runtime.processing_tick import STALE_DATA_AGE_S
from vibesensor.infra.runtime.ws_payload_projection import LiveWsPayloadProjector
from vibesensor.shared.types.speed_source_config import SpeedSourceConfig


class _SpeedResolution:
    def __init__(self, speed_mps: float | None, source: str = "gps") -> None:
        self.speed_mps = speed_mps
        self.source = source


def _analysis_settings() -> AnalysisSettingsSnapshot:
    return AnalysisSettingsSnapshot(
        tire_width_mm=285.0,
        tire_aspect_pct=30.0,
        rim_in=21.0,
        final_drive_ratio=3.08,
        current_gear_ratio=0.64,
    )


def _build_projector() -> tuple[LiveWsPayloadProjector, MagicMock, MagicMock, MagicMock]:
    registry = MagicMock()
    registry.client_snapshots.return_value = [
        ClientSnapshot(
            client_id="aaaaaaaaaaaa",
            name="front-left",
            connected=True,
            sample_rate_hz=800,
            frame_samples=256,
            frames_total=12,
        )
    ]
    processor = MagicMock()
    processor.clients_with_recent_data.return_value = ["aaaaaaaaaaaa"]
    processor.multi_spectrum_payload.return_value = {
        "frame_fingerprint": "aaaaaaaaaaaa:0:0:0",
        "freq": [],
        "clients": {"aaaaaaaaaaaa": {}},
    }
    gps_monitor = MagicMock()
    gps_monitor.resolve_speed.return_value = _SpeedResolution(12.5)
    gps_monitor.engine_rpm = None
    settings_reader = MagicMock()
    settings_reader.analysis_settings_snapshot.return_value = _analysis_settings()
    speed_source_reader = MagicMock()
    speed_source_reader.speed_source_config.return_value = SpeedSourceConfig.default()
    projector = LiveWsPayloadProjector(
        registry=registry,
        processor=processor,
        gps_monitor=gps_monitor,
        gps_enabled=True,
        settings_reader=settings_reader,
        speed_source_reader=speed_source_reader,
    )
    return projector, processor, registry, gps_monitor


def test_build_shared_payload_projects_live_rows_without_broadcaster() -> None:
    projector, processor, registry, _gps_monitor = _build_projector()

    payload = projector.build_shared_payload(include_heavy=True)

    assert payload["selected_client_id"] is None
    assert payload["speed_mps"] == 12.5
    assert payload["clients"][0]["id"] == "aaaaaaaaaaaa"
    assert payload["clients"][0]["name"] == "front-left"
    assert payload["rotational_speeds"]["basis_speed_source"] == "gps"
    assert "spectra" in payload
    assert payload["spectra"]["frame_fingerprint"] == "aaaaaaaaaaaa:0:0:0"
    registry.client_snapshots.assert_called_once_with(
        now=None,
        now_mono=None,
        metrics_by_client=None,
    )
    processor.clients_with_recent_data.assert_called_once_with(
        ["aaaaaaaaaaaa"],
        max_age_s=STALE_DATA_AGE_S,
    )


def test_build_shared_payload_light_tick_omits_spectra() -> None:
    projector, processor, _registry, _gps_monitor = _build_projector()

    payload = projector.build_shared_payload(include_heavy=False)

    assert "spectra" not in payload
    processor.multi_spectrum_payload.assert_not_called()


def test_build_shared_payload_carries_speed_unavailable_reason() -> None:
    projector, _processor, _registry, gps_monitor = _build_projector()
    gps_monitor.resolve_speed.return_value = _SpeedResolution(None)

    payload = projector.build_shared_payload(include_heavy=False)

    assert payload["rotational_speeds"]["wheel"]["reason"] == "speed_unavailable"


def test_build_shared_payload_marks_retained_stale_clients_disconnected(
    tmp_path,
    monkeypatch,
) -> None:
    from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
    from vibesensor.adapters.udp.protocol import HelloMessage
    from vibesensor.infra.runtime.registry import ClientRegistry

    db = create_history_persistence_adapters(tmp_path / "history.db")
    registry = ClientRegistry(
        db=db.client_name_repository,
        live_ttl_seconds=5.0,
        retention_ttl_seconds=30.0,
    )
    hello = HelloMessage(
        client_id=bytes.fromhex("001122334455"),
        control_port=9010,
        sample_rate_hz=800,
        name="sensor",
        firmware_version="fw",
    )
    registry.update_from_hello(hello, ("10.4.0.2", 9010), now=1.0, now_mono=1.0)

    now = {"wall": 9.0, "mono": 9.0}
    monkeypatch.setattr("vibesensor.infra.runtime.registry.time.time", lambda: now["wall"])
    monkeypatch.setattr("vibesensor.infra.runtime.registry.time.monotonic", lambda: now["mono"])

    processor = MagicMock()
    processor.clients_with_recent_data.return_value = []
    processor.multi_spectrum_payload.return_value = {"freq": [], "clients": {}}
    gps_monitor = MagicMock()
    gps_monitor.resolve_speed.return_value = _SpeedResolution(12.5)
    gps_monitor.engine_rpm = None
    settings_reader = MagicMock()
    settings_reader.analysis_settings_snapshot.return_value = _analysis_settings()
    speed_source_reader = MagicMock()
    speed_source_reader.speed_source_config.return_value = SpeedSourceConfig.default()
    projector = LiveWsPayloadProjector(
        registry=registry,
        processor=processor,
        gps_monitor=gps_monitor,
        gps_enabled=True,
        settings_reader=settings_reader,
        speed_source_reader=speed_source_reader,
    )

    payload = projector.build_shared_payload(include_heavy=False)

    assert len(payload["clients"]) == 1
    assert payload["clients"][0]["connected"] is False
    assert payload["clients"][0]["last_seen_age_ms"] == 8000
