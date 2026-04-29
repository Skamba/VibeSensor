from __future__ import annotations

from vibesensor.domain import AnalysisSettingsSnapshot
from vibesensor.infra.runtime.client_snapshot import ClientSnapshot
from vibesensor.infra.runtime.processing_tick import STALE_DATA_AGE_S
from vibesensor.infra.runtime.ws_payload_projection import LiveWsPayloadProjector
from vibesensor.shared.types.speed_source_config import SpeedSourceConfig


class _SpeedResolution:
    def __init__(self, speed_mps: float | None, source: str = "gps") -> None:
        self.speed_mps = speed_mps
        self.source = source


class _FakeRegistry:
    def __init__(self, snapshots: list[ClientSnapshot]) -> None:
        self._snapshots = snapshots

    def client_snapshots(self, **_kwargs: object) -> list[ClientSnapshot]:
        return list(self._snapshots)


class _FakeProcessor:
    def __init__(
        self,
        *,
        fresh_ids: list[str],
        spectra_payload: dict[str, object],
    ) -> None:
        self._fresh_ids = fresh_ids
        self._spectra_payload = spectra_payload

    def clients_with_recent_data(self, _client_ids: list[str], *, max_age_s: float) -> list[str]:
        assert max_age_s == STALE_DATA_AGE_S
        return list(self._fresh_ids)

    def multi_spectrum_payload(self, _fresh_ids: list[str]) -> dict[str, object]:
        return dict(self._spectra_payload)


class _FakeGpsMonitor:
    def __init__(self, resolution: _SpeedResolution) -> None:
        self._resolution = resolution
        self.engine_rpm = None

    def resolve_speed(self) -> _SpeedResolution:
        return self._resolution


class _FakeSettingsReader:
    def analysis_settings_snapshot(self) -> AnalysisSettingsSnapshot:
        return _analysis_settings()


class _FakeSpeedSourceReader:
    def speed_source_config(self) -> SpeedSourceConfig:
        return SpeedSourceConfig.default()


def _analysis_settings() -> AnalysisSettingsSnapshot:
    return AnalysisSettingsSnapshot(
        tire_width_mm=285.0,
        tire_aspect_pct=30.0,
        rim_in=21.0,
        final_drive_ratio=3.08,
        current_gear_ratio=0.64,
    )


def _build_projector(
    *,
    speed_mps: float | None = 12.5,
    speed_source: str = "gps",
) -> tuple[LiveWsPayloadProjector, _FakeProcessor, _FakeGpsMonitor]:
    registry = _FakeRegistry(
        [
            ClientSnapshot(
                client_id="aaaaaaaaaaaa",
                name="front-left",
                connected=True,
                sample_rate_hz=800,
                frame_samples=256,
                frames_total=12,
            )
        ]
    )
    processor = _FakeProcessor(
        fresh_ids=["aaaaaaaaaaaa"],
        spectra_payload={
            "frame_fingerprint": "aaaaaaaaaaaa:0:0:0",
            "freq": [],
            "clients": {"aaaaaaaaaaaa": {}},
        },
    )
    gps_monitor = _FakeGpsMonitor(_SpeedResolution(speed_mps, speed_source))
    projector = LiveWsPayloadProjector(
        registry=registry,
        processor=processor,
        gps_monitor=gps_monitor,
        gps_enabled=True,
        settings_reader=_FakeSettingsReader(),
        speed_source_reader=_FakeSpeedSourceReader(),
    )
    return projector, processor, gps_monitor


def test_build_shared_payload_projects_live_rows_without_broadcaster() -> None:
    projector, _processor, _gps_monitor = _build_projector()

    payload = projector.build_shared_payload(include_heavy=True)

    assert payload["selected_client_id"] is None
    assert payload["speed_mps"] == 12.5
    assert payload["clients"][0]["id"] == "aaaaaaaaaaaa"
    assert payload["clients"][0]["name"] == "front-left"
    assert payload["rotational_speeds"]["basis_speed_source"] == "gps"
    assert "spectra" in payload
    assert payload["spectra"]["frame_fingerprint"] == "aaaaaaaaaaaa:0:0:0"


def test_build_shared_payload_light_tick_omits_spectra() -> None:
    projector, _processor, _gps_monitor = _build_projector()

    payload = projector.build_shared_payload(include_heavy=False)

    assert "spectra" not in payload


def test_build_shared_payload_carries_speed_unavailable_reason() -> None:
    projector, _processor, _gps_monitor = _build_projector(speed_mps=None)

    payload = projector.build_shared_payload(include_heavy=False)

    assert payload["speed_mps"] is None
    assert payload["rotational_speeds"]["wheel"]["reason"] == "speed_unavailable"


def test_build_shared_payload_marks_retained_stale_clients_disconnected(
    tmp_path,
    monkeypatch,
) -> None:
    from vibesensor.adapters.persistence.history_db import create_history_persistence_adapters
    from vibesensor.adapters.udp.protocol import HelloMessage
    from vibesensor.infra.runtime.registry import ClientRegistry

    db = create_history_persistence_adapters(tmp_path / "history.db")
    try:
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

        processor = _FakeProcessor(fresh_ids=[], spectra_payload={"freq": [], "clients": {}})
        gps_monitor = _FakeGpsMonitor(_SpeedResolution(12.5))
        projector = LiveWsPayloadProjector(
            registry=registry,
            processor=processor,
            gps_monitor=gps_monitor,
            gps_enabled=True,
            settings_reader=_FakeSettingsReader(),
            speed_source_reader=_FakeSpeedSourceReader(),
        )

        payload = projector.build_shared_payload(include_heavy=False)

        assert len(payload["clients"]) == 1
        assert payload["clients"][0]["connected"] is False
        assert payload["clients"][0]["last_seen_age_ms"] == 8000
    finally:
        db.lifecycle.close()
