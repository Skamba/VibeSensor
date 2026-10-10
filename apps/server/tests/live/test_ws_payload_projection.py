from __future__ import annotations

import numpy as np
import pytest

from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.domain.car import CarSnapshot
from vibesensor.domain.engine_profile import EngineProfile
from vibesensor.dsp.fft_analysis import SpectralAnalysisComputer
from vibesensor.ingest.registry import ClientSnapshot
from vibesensor.live import ws_payload_projection
from vibesensor.live.order_hearing import LiveSpectrum
from vibesensor.live.ws_payload_projection import LiveWsPayloadProjector
from vibesensor.speed.speed_source_config import SpeedSourceConfig


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
        self.recent_data_ages: list[float] = []
        self.spectra_requests: list[list[str]] = []
        self.latest: dict[str, object] = {}

    def clients_with_recent_data(self, _client_ids: list[str], *, max_age_s: float) -> list[str]:
        self.recent_data_ages.append(max_age_s)
        return list(self._fresh_ids)

    def multi_spectrum_payload(self, fresh_ids: list[str]) -> dict[str, object]:
        self.spectra_requests.append(list(fresh_ids))
        return dict(self._spectra_payload)

    def latest_spectra(self, client_ids: list[str]) -> dict[str, object]:
        return {
            client_id: self.latest[client_id]
            for client_id in client_ids
            if client_id in self.latest
        }


class _FakeGpsMonitor:
    def __init__(self, resolution: _SpeedResolution) -> None:
        self._resolution = resolution
        self.engine_rpm = None

    def resolve_speed(self) -> _SpeedResolution:
        return self._resolution


class _FakeSettingsReader:
    def __init__(self, car: CarSnapshot | None = None) -> None:
        self._car = car

    def analysis_settings_snapshot(self) -> AnalysisSettingsSnapshot:
        return _analysis_settings()

    def active_car_snapshot(self) -> CarSnapshot | None:
        return self._car


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
    car: CarSnapshot | None = None,
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
        settings_reader=_FakeSettingsReader(car),
        speed_source_reader=_FakeSpeedSourceReader(),
        bundled_firmware_version=lambda: "",
    )
    return projector, processor, gps_monitor


def test_build_shared_payload_projects_live_rows_without_broadcaster() -> None:
    projector, processor, _gps_monitor = _build_projector()

    payload = projector.build_shared_payload(include_heavy=True)

    # Only sensors with data in the last 2 s are live and get spectra.
    assert processor.recent_data_ages == [2.0]
    assert processor.spectra_requests == [["aaaaaaaaaaaa"]]

    assert payload["selected_client_id"] is None
    assert payload["speed_mps"] == 12.5
    assert payload["clients"][0]["id"] == "aaaaaaaaaaaa"
    assert payload["clients"][0]["name"] == "front-left"
    assert payload["rotational_speeds"]["basis_speed_source"] == "gps"
    assert "spectra" in payload
    assert payload["spectra"]["frame_fingerprint"] == "aaaaaaaaaaaa:0:0:0"


@pytest.mark.parametrize(
    ("profile", "engine_bands"),
    [
        (None, ["engine_1x", "engine_2x"]),
        (EngineProfile("inline", 6), ["engine_1x", "engine_3x"]),
    ],
    ids=["engine-not-known", "inline-6"],
)
def test_the_live_engine_bands_follow_the_active_cars_engine(
    profile: EngineProfile | None, engine_bands: list[str]
) -> None:
    car = CarSnapshot(
        car_id="car-1", name="Six-cylinder saloon", car_type="sedan", engine_profile=profile
    )
    projector, _processor, _gps_monitor = _build_projector(car=car)

    bands = projector.build_shared_payload(include_heavy=False)["rotational_speeds"]["order_bands"]

    assert bands is not None
    assert [band["key"] for band in bands if band["key"].startswith("engine_")] == engine_bands


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
    from vibesensor.history.history_db import HistoryDB
    from vibesensor.ingest.protocol_messages import HelloMessage
    from vibesensor.ingest.registry import ClientRegistry

    db = HistoryDB(tmp_path / "history.db")
    try:
        registry = ClientRegistry(
            db=db,
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
        monkeypatch.setattr("vibesensor.ingest.registry.time.time", lambda: now["wall"])
        monkeypatch.setattr("vibesensor.ingest.registry.time.monotonic", lambda: now["mono"])

        processor = _FakeProcessor(fresh_ids=[], spectra_payload={"freq": [], "clients": {}})
        gps_monitor = _FakeGpsMonitor(_SpeedResolution(12.5))
        projector = LiveWsPayloadProjector(
            registry=registry,
            processor=processor,
            gps_monitor=gps_monitor,
            gps_enabled=True,
            settings_reader=_FakeSettingsReader(),
            speed_source_reader=_FakeSpeedSourceReader(),
            bundled_firmware_version=lambda: "",
        )

        payload = projector.build_shared_payload(include_heavy=False)

        assert len(payload["clients"]) == 1
        assert payload["clients"][0]["connected"] is False
        assert payload["clients"][0]["last_seen_age_ms"] == 8000
    finally:
        db.close()


def test_spectra_only_cover_sensors_with_recent_data() -> None:
    projector, processor, _gps_monitor = _build_projector()
    processor._fresh_ids = []

    projector.build_shared_payload(include_heavy=True)

    assert processor.spectra_requests == [[]]


def test_a_band_names_the_sensors_whose_recent_spectra_hear_its_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [1000.0]
    monkeypatch.setattr(ws_payload_projection.time, "monotonic", lambda: now[0])
    projector, processor, _gps_monitor = _build_projector(speed_mps=30.0)
    wheel = next(
        band
        for band in projector.build_shared_payload(include_heavy=False)["rotational_speeds"][
            "order_bands"
        ]
        if band["key"] == "wheel_1x"
    )
    computer = SpectralAnalysisComputer(fft_n=2048, spectrum_min_hz=5.0, spectrum_max_hz=200.0)
    rng = np.random.default_rng(4)
    t = np.arange(2048) / 800
    bands = []
    for generation in range(10):
        block = rng.normal(0.0, 0.002, size=(3, 2048))
        block[2] += 0.02 * np.sin(2 * np.pi * wheel["center_hz"] * t)
        spectrum = computer.combined_spectrum(block.astype(np.float32), 800)
        assert spectrum is not None
        processor.latest = {"aaaaaaaaaaaa": LiveSpectrum(generation, spectrum, window_s=2048 / 800)}
        bands = projector.build_shared_payload(include_heavy=False)["rotational_speeds"][
            "order_bands"
        ]
        now[0] += 1.0

    by_key = {band["key"]: band for band in bands}
    assert by_key["wheel_1x"]["heard_at"] == ["aaaaaaaaaaaa"]
    assert "heard_at" not in by_key["engine_1x"]
