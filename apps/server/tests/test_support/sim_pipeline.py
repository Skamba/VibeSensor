"""Drive simulator sensors through the real server pipeline in-process, on virtual time.

The simulator's own sensor model (``SimClient.make_frame``, its device clock and
its ``CMD_SYNC_CLOCK`` handling) talks to the production services built by
``build_runtime()``: HELLO/ACK over ``ControlDatagramProtocol``, clock sync from
``UDPControlPlane``, DATA through ``DataDatagramProtocol`` into the DSP and the
raw capture, processing ticks from ``ProcessingTickRunner`` and sample flushes from
``RunRecorder.flush_tick()``. Post-analysis then runs on the persisted run, and the
report view is built from the stored diagnosis, exactly as for a real recording.

Datagrams are delivered by a small event scheduler with a fixed network latency
while ``time.monotonic``, ``time.time`` and ``utc_now_iso`` follow a virtual
clock, so a 25 s drive records in about 3 s of wall time.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import math
import random
import sys
import time
import tracemalloc
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from vibesensor.app.composition import AppRuntime, build_runtime
from vibesensor.app.config_loader import load_config
from vibesensor.common.time_utils import utc_now_iso
from vibesensor.dsp.constants import FFT_N, FFT_UPDATE_HZ
from vibesensor.history.history_db import HistoryDB
from vibesensor.ingest.protocol_packing import pack_data, pack_hello
from vibesensor.ingest.protocol_wire import HELLO_CAP_EXPLICIT_ACK
from vibesensor.ingest.udp_data_rx import DataDatagramProtocol
from vibesensor.live.processing_loop import (
    CLOCK_SYNC_INTERVAL_S,
    ProcessingLoopState,
    ProcessingTickRunner,
)
from vibesensor.recording.lifecycle_state import RecordingStopReason
from vibesensor.recording.recorder import RunRecorder
from vibesensor.recording.run_schema import RunMetadata
from vibesensor.report.view_model import ReportView, build_report_view
from vibesensor.simulator.scripted_scenario_models import ScenarioPhase, phase_speed_kmh
from vibesensor.simulator.scripted_targeting import apply_phase, target_clients
from vibesensor.simulator.sim_client import SimClient, make_client_id
from vibesensor.simulator.sim_runtime import ClientProtocol
from vibesensor.speed.gps_speed import GPSSpeedMonitor
from vibesensor.speed.obd.polling import ObdPidPollResult, ObdPollResult
from vibesensor.speed.obd.service import ObdService
from vibesensor.summary.persisted_analysis import PersistedAnalysis

__all__ = [
    "BenchCar",
    "BenchSensor",
    "SimPipelineResult",
    "run_sim_pipeline",
]

_SERVER_HOST = "10.4.0.1"
_SERVER_DATA_PORT = 9000
_SERVER_CONTROL_PORT = 9001
_SENSOR_HOST = "10.4.0.20"
_SENSOR_CONTROL_BASE = 9100
_NETWORK_LATENCY_S = 0.0015
_LATENCY_SPIKE_SHARE = 0.3
_HELLO_INTERVAL_S = 2.0
# Firmware DATA retransmission (firmware/esp/src/runtime_config.h).
_DATA_RETRANSMIT_S = 0.120
_DATA_MAX_RETRANSMITS = 4
_DATA_MAX_FRAME_AGE_S = 0.750
_HANDSHAKE_POLL_S = 0.05
_SPEED_UPDATE_PERIOD_S = 0.5
_SAMPLE_RATE_HZ = 800
_FRAME_SAMPLES = 200
_VIRTUAL_CLOCK_START_S = 50_000.0
# Sensors apply the server's clock offset from their second sync exchange.
_CLOCK_SYNC_WARMUP_S = 2.0 * CLOCK_SYNC_INTERVAL_S + 1.0
# At car start the Pi and the sensors power up together, so a sensor's bare
# device timer reads within a couple of seconds of the server's monotonic clock.
_CAR_START_BOOT_SPREAD_S = 2.0
_POST_ANALYSIS_TIMEOUT_S = 90.0
_POST_ANALYSIS_S_PER_DRIVE_S = 0.5
# A paired Bluetooth OBD adapter.
_OBD_ADAPTER = {"obdDeviceMac": "00:1D:A5:68:98:8A", "obdDeviceName": "OBDII"}

SpeedSource = Literal["gps", "obd2"]


@dataclass(frozen=True, slots=True)
class BenchCar:
    """A car profile; its order frequencies are computed here, independent of the server."""

    name: str
    tire_width_mm: float
    tire_aspect_pct: float
    rim_in: float
    final_drive_ratio: float
    current_gear_ratio: float
    tire_deflection_factor: float = 0.97

    @property
    def tire_circumference_m(self) -> float:
        diameter_mm = self.rim_in * 25.4 + 2.0 * self.tire_width_mm * self.tire_aspect_pct / 100.0
        return diameter_mm / 1000.0 * math.pi * self.tire_deflection_factor

    def wheel_hz(self, speed_kmh: float) -> float:
        return speed_kmh / 3.6 / self.tire_circumference_m

    def order_hz(self, speed_kmh: float) -> dict[str, float]:
        """Order frequencies at *speed_kmh*, keyed like ``SimClient.order_hz``."""
        wheel = self.wheel_hz(speed_kmh)
        shaft = wheel * self.final_drive_ratio
        engine = shaft * self.current_gear_ratio
        return {
            "wheel_1x": wheel,
            "wheel_2x": 2.0 * wheel,
            "shaft_1x": shaft,
            "engine_1x": engine,
            "engine_2x": 2.0 * engine,
        }

    def aspects(self) -> dict[str, float]:
        return {
            "tire_width_mm": self.tire_width_mm,
            "tire_aspect_pct": self.tire_aspect_pct,
            "rim_in": self.rim_in,
            "final_drive_ratio": self.final_drive_ratio,
            "current_gear_ratio": self.current_gear_ratio,
            "tire_deflection_factor": self.tire_deflection_factor,
        }


@dataclass(frozen=True, slots=True)
class BenchSensor:
    """One simulated sensor: its advertised name (the simulator target) and mounting point."""

    advertised_name: str
    location_code: str
    # Share of DATA frames lost on the way to the server (poor Wi-Fi).
    frame_loss: float = 0.0
    # Extra delay of some control replies (sync ACKs) on the way to the server.
    uplink_latency_spike_s: float = 0.0
    # Share of DATA transmissions lost on congested Wi-Fi; the sensor retransmits
    # them (stop-and-wait), delaying the frames queued behind.
    wifi_retry_loss: float = 0.0


@dataclass(slots=True)
class SimPipelineResult:
    run_id: str
    analysis: PersistedAnalysis
    report: ReportView
    client_ids: dict[str, str]
    history_db: HistoryDB
    metadata: RunMetadata
    post_analysis_s: float
    post_analysis_peak_bytes: int | None
    stop_reason: RecordingStopReason | None

    @property
    def diagnosis(self) -> dict[str, Any]:
        diagnosis = self.analysis.payload.get("diagnosis")
        assert isinstance(diagnosis, dict)
        return diagnosis


class _VirtualClock:
    def __init__(self, start_s: float) -> None:
        self.now_s = start_s

    def monotonic(self) -> float:
        return self.now_s


class _EventLoop:
    """Discrete-event scheduler on the virtual clock."""

    def __init__(self, clock: _VirtualClock) -> None:
        self._clock = clock
        self._heap: list[tuple[float, int, Callable[[], None]]] = []
        self._order = itertools.count()

    def at(self, t_s: float, action: Callable[[], None]) -> None:
        heapq.heappush(self._heap, (max(t_s, self._clock.now_s), next(self._order), action))

    def after(self, delay_s: float, action: Callable[[], None]) -> None:
        self.at(self._clock.now_s + delay_s, action)

    def every(self, period_s: float, action: Callable[[], None], *, first_s: float) -> None:
        def tick() -> None:
            action()
            self.after(period_s, tick)

        self.at(first_s, tick)

    def run_until(self, end_s: float) -> None:
        while self._heap and self._heap[0][0] <= end_s:
            t_s, _order, action = heapq.heappop(self._heap)
            self._clock.now_s = t_s
            action()
        self._clock.now_s = end_s


class _LatencyTransport:
    """``sendto`` that delivers each datagram to *deliver* after the network latency.

    With *spike_s*, a share of the datagrams waits that much longer (Wi-Fi
    retries), which makes clock-sync round trips slow and asymmetric.
    """

    def __init__(
        self,
        loop: _EventLoop,
        deliver: Callable[[bytes, tuple[str, int]], None],
        *,
        spike_s: float = 0.0,
        seed: int = 0,
    ) -> None:
        self._loop = loop
        self._deliver = deliver
        self._spike_s = spike_s
        self._rng = random.Random(seed)

    def sendto(self, data: bytes, addr: tuple[str, int] | None = None) -> None:
        target = addr if addr is not None else ("", 0)
        delay_s = _NETWORK_LATENCY_S
        if self._spike_s > 0 and self._rng.random() < _LATENCY_SPIKE_SHARE:
            delay_s += self._spike_s
        self._loop.after(delay_s, lambda: self._deliver(data, target))

    def close(self) -> None:
        return None


class _DiscardTransport:
    def sendto(self, data: bytes, addr: tuple[str, int] | None = None) -> None:
        del data, addr

    def close(self) -> None:
        return None


@dataclass(slots=True)
class _Sensor:
    spec: BenchSensor
    sim: SimClient
    protocol: ClientProtocol
    frame_index: int = 0
    first_due_us: float | None = None
    addr: tuple[str, int] = field(default=("", 0))


def _runtime_config(tmp_path: Path, max_recording_duration_s: float | None) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "config.yaml"
    config: dict[str, Any] = {
        "logging": {"history_db_path": str(tmp_path / "history.db")},
        "gps": {"gps_enabled": False},
    }
    if max_recording_duration_s is not None:
        config["recording"] = {"max_duration_s": max_recording_duration_s}
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path


_VIRTUAL_WALL_START = datetime(2026, 5, 4, 9, 30, tzinfo=UTC)


@contextmanager
def _virtual_time(clock: _VirtualClock) -> Iterator[None]:
    """Run ``time.monotonic``, ``time.time`` and ``utc_now_iso`` on the virtual clock.

    Wall-clock stamps matter: post-analysis takes the run duration from the
    recorded start/end UTC times, so they must advance with the drive, not with
    however long the test machine took to simulate it.
    """
    wall_offset_s = _VIRTUAL_WALL_START.timestamp() - clock.now_s

    def virtual_wall() -> float:
        return clock.now_s + wall_offset_s

    def virtual_utc_now_iso() -> str:
        return datetime.fromtimestamp(virtual_wall(), UTC).isoformat()

    real_monotonic, real_time = time.monotonic, time.time
    patched = [
        module
        for name, module in list(sys.modules.items())
        if name.startswith("vibesensor.") and getattr(module, "utc_now_iso", None) is utc_now_iso
    ]
    time.monotonic = clock.monotonic  # type: ignore[assignment]
    time.time = virtual_wall  # type: ignore[assignment]
    for module in patched:
        module.utc_now_iso = virtual_utc_now_iso  # type: ignore[attr-defined]
    try:
        yield
    finally:
        time.monotonic, time.time = real_monotonic, real_time  # type: ignore[assignment]
        for module in patched:
            module.utc_now_iso = utc_now_iso  # type: ignore[attr-defined]


def run_sim_pipeline(
    tmp_path: Path,
    *,
    car: BenchCar,
    sensors: Sequence[BenchSensor],
    scenario_name: str,
    phases: Sequence[ScenarioPhase],
    client_seed: int,
    lang: str = "en",
    trace_post_analysis_memory: bool = False,
    car_start: bool = False,
    speed_source: SpeedSource = "gps",
    max_recording_duration_s: float | None = None,
) -> SimPipelineResult:
    """Record one simulated drive through the production pipeline and return its analysis.

    With *car_start*, everything powers up together and the recording starts as
    soon as the sensors show up, before their clocks are synced: their first
    chunks carry bare device time that reads close to (but not at) server time.

    The drive's speed reaches the server as a measured speed: from gpsd (a 3D fix,
    as the GPS receiver reports it) or, with *speed_source* ``"obd2"``, from a
    connected OBD adapter (speed PID only).
    *max_recording_duration_s* sets the server's ``recording.max_duration_s`` cap.
    """
    runtime = build_runtime(load_config(_runtime_config(tmp_path, max_recording_duration_s)))
    try:
        return _record(
            runtime,
            car=car,
            sensors=sensors,
            scenario_name=scenario_name,
            phases=phases,
            client_seed=client_seed,
            lang=lang,
            trace_post_analysis_memory=trace_post_analysis_memory,
            car_start=car_start,
            speed_source=speed_source,
        )
    finally:
        runtime.lifecycle.run_recorder.raw_capture.shutdown()


def _record(
    runtime: AppRuntime,
    *,
    car: BenchCar,
    sensors: Sequence[BenchSensor],
    scenario_name: str,
    phases: Sequence[ScenarioPhase],
    client_seed: int,
    lang: str,
    trace_post_analysis_memory: bool,
    car_start: bool,
    speed_source: SpeedSource,
) -> SimPipelineResult:
    web = runtime.web
    lifecycle = runtime.lifecycle
    registry = lifecycle.registry
    recorder = lifecycle.run_recorder
    history_db = lifecycle.history_db

    snapshot = web.car_settings.add_car(
        {"name": car.name, "type": "sedan", "aspects": car.aspects()}  # type: ignore[typeddict-item]
    )
    web.car_settings.set_active_car(snapshot.cars[-1]["id"])

    clock = _VirtualClock(_VIRTUAL_CLOCK_START_S)
    loop = _EventLoop(clock)
    tick_runner = ProcessingTickRunner(
        state=ProcessingLoopState(),
        sample_rate_hz=_SAMPLE_RATE_HZ,
        fft_n=FFT_N,
        registry=registry,
        processor=lifecycle.processor,
        control_plane=lifecycle.control_plane,
    )
    data_protocol = DataDatagramProtocol(
        registry=registry,
        processor=lifecycle.processor,
        raw_capture_sink=recorder.raw_capture,
        ingest_diagnostics=lifecycle.ingest_diagnostics,
    )
    data_protocol.connection_made(_DiscardTransport())  # type: ignore[arg-type]

    with _virtual_time(clock), asyncio.Runner() as runner:
        sims: dict[int, _Sensor] = {}
        control_protocol = lifecycle.control_plane.protocol

        def deliver_to_sensor(data: bytes, addr: tuple[str, int]) -> None:
            sensor = sims.get(addr[1])
            if sensor is not None:
                sensor.protocol.datagram_received(data, (_SERVER_HOST, _SERVER_CONTROL_PORT))

        to_sensors = _LatencyTransport(loop, deliver_to_sensor)
        control_protocol.connection_made(to_sensors)  # type: ignore[arg-type]
        lifecycle.control_plane.transport = to_sensors  # type: ignore[assignment]

        clients: list[SimClient] = []
        for index, spec in enumerate(sensors):
            control_port = _SENSOR_CONTROL_BASE + index
            sim = SimClient(
                name=spec.advertised_name,
                client_id=make_client_id(client_seed * 16 + index + 1),
                control_port=control_port,
                sample_rate_hz=_SAMPLE_RATE_HZ,
                frame_samples=_FRAME_SAMPLES,
                server_host=_SERVER_HOST,
                server_data_port=_SERVER_DATA_PORT,
                server_control_port=_SERVER_CONTROL_PORT,
                profile_name="rough_road",
            )
            sim.order_hz = car.order_hz(100.0)
            if car_start:
                boot_rng = random.Random(client_seed * 16 + index)
                sim.device_boot_mono_s = boot_rng.uniform(
                    -_CAR_START_BOOT_SPREAD_S, _CAR_START_BOOT_SPREAD_S
                )
            addr = (_SENSOR_HOST, control_port)

            def deliver_to_server(
                data: bytes, _target: tuple[str, int], addr: tuple[str, int] = addr
            ) -> None:
                control_protocol.datagram_received(data, addr)

            sim.control_transport = _LatencyTransport(  # type: ignore[assignment]
                loop,
                deliver_to_server,
                spike_s=spec.uplink_latency_spike_s,
                seed=index,
            )
            sensor = _Sensor(spec=spec, sim=sim, protocol=ClientProtocol(sim), addr=addr)
            sims[control_port] = sensor
            clients.append(sim)

        start_s = clock.now_s
        for sensor in sims.values():
            _start_sensor(loop, clock, sensor, data_protocol)

        loop.every(
            1.0 / FFT_UPDATE_HZ,
            _processing_ticker(runner, tick_runner, clock),
            first_s=start_s + 0.1,
        )
        loop.every(
            1.0 / recorder.metrics_log_hz,
            lambda: _flush_tick(recorder),
            first_s=start_s + 0.12,
        )

        # Before the drive: the simulator starts in its first phase, the user
        # assigns locations once the sensors show up.
        if speed_source == "obd2":
            web.speed_source_service.update_speed_source({"speedSource": "obd2", **_OBD_ADAPTER})  # type: ignore[typeddict-item]
            lifecycle.obd_runner.mark_connected()
        else:
            web.speed_source_service.update_speed_source({"speedSource": "gps"})
            lifecycle.gps_monitor.gps_enabled = True
            lifecycle.gps_monitor.connection_state = "connected"
        set_speed = _speed_setter(
            lifecycle.gps_monitor, lifecycle.obd_runner, clients, speed_source
        )
        apply_phase(clients, scenario_name, phases[0])
        set_speed(phases[0].speed_start_kmh)
        loop.run_until(start_s + 1.0)
        client_ids: dict[str, str] = {}
        for sensor in sims.values():
            client_id = sensor.sim.client_id.hex()
            assert registry.get(client_id) is not None, sensor.spec
            _assign_location(runtime, client_id, sensor.spec.location_code)
            client_ids[sensor.spec.location_code] = client_id
        if not car_start:
            loop.run_until(start_s + _CLOCK_SYNC_WARMUP_S)

        drive_s = sum(phase.duration_s for phase in phases)
        post_analysis_timeout_s = max(
            _POST_ANALYSIS_TIMEOUT_S, drive_s * _POST_ANALYSIS_S_PER_DRIVE_S
        )
        recorder.start_recording()
        run_id = recorder.status().run_id
        assert run_id is not None
        guided = any(phase.guided_phase is not None for phase in phases)
        phase_start = clock.now_s
        for phase in phases:
            _schedule_phase(
                loop, set_speed, clients, scenario_name, phase, phase_start, guided, recorder
            )
            phase_start += phase.duration_s
        loop.run_until(phase_start)
        if guided:
            recorder.mark_guided_phase(None)
        if trace_post_analysis_memory:
            tracemalloc.start()
        analysis_started = time.perf_counter()
        recorder.stop_recording(_only_if_run_id=run_id)

    assert recorder.post_analysis.wait(timeout_s=post_analysis_timeout_s)
    post_analysis_s = time.perf_counter() - analysis_started
    peak_bytes: int | None = None
    if trace_post_analysis_memory:
        peak_bytes = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
    run = history_db.get_run(run_id)
    assert run is not None and run.analysis is not None, run
    report = build_report_view(run.analysis.payload, run.metadata, lang=lang)
    return SimPipelineResult(
        run_id=run_id,
        analysis=run.analysis,
        report=report,
        client_ids=client_ids,
        history_db=history_db,
        metadata=run.metadata,
        post_analysis_s=post_analysis_s,
        post_analysis_peak_bytes=peak_bytes,
        stop_reason=recorder.status().last_stop_reason,
    )


def _start_sensor(
    loop: _EventLoop,
    clock: _VirtualClock,
    sensor: _Sensor,
    data_protocol: DataDatagramProtocol,
) -> None:
    sim = sensor.sim

    def hello() -> None:
        assert sim.control_transport is not None
        sim.control_transport.sendto(
            pack_hello(
                client_id=sim.client_id,
                control_port=sim.control_port,
                sample_rate_hz=sim.sample_rate_hz,
                name=sim.name,
                frame_samples=sim.frame_samples,
                firmware_version="sim-0.2",
                capabilities=HELLO_CAP_EXPLICIT_ACK,
            ),
            (_SERVER_HOST, _SERVER_CONTROL_PORT),
        )

    loop.every(_HELLO_INTERVAL_S, hello, first_s=clock.now_s + sim.start_offset_s)
    frame_duration_us = sim.frame_samples * 1_000_000.0 / sim.sample_rate_hz
    loss_rng = random.Random(sim.client_id)
    retry_rng = random.Random(sim.client_id[::-1])
    data_addr = (_SENSOR_HOST, 40_000 + sim.control_port)
    # Like the firmware (runtime_queue.cpp / runtime_transport.cpp): a frame is
    # stamped with the clock offset in effect when it is queued, and the queue is
    # sent stop-and-wait, the head retransmitted until the server acknowledges it.
    queue: deque[tuple[bytes, float]] = deque()
    head_attempts = [0]

    def enqueue() -> None:
        assert sensor.first_due_us is not None and sim.rng is not None
        frame_start_us = sensor.first_due_us + sensor.frame_index * frame_duration_us
        packet = pack_data(
            client_id=sim.client_id,
            seq=sim.seq,
            t0_us=max(0, int(round(frame_start_us)) + sim.clock_offset_us),
            samples=sim.make_frame(),
        )
        sim.seq = (sim.seq + 1) & 0xFFFFFFFF
        sensor.frame_index += 1
        tx_delay_s = pending_tx_delay[0]
        schedule_next()
        if loss_rng.random() < sensor.spec.frame_loss:
            return  # lost for good (before it reached the radio)
        queue.append((packet, clock.now_s))
        if len(queue) == 1:
            loop.after(tx_delay_s, transmit)

    def transmit() -> None:
        packet, queued_s = queue[0]
        head_attempts[0] += 1
        if retry_rng.random() < sensor.spec.wifi_retry_loss:
            if (
                head_attempts[0] <= _DATA_MAX_RETRANSMITS
                and clock.now_s + _DATA_RETRANSMIT_S - queued_s < _DATA_MAX_FRAME_AGE_S
            ):
                loop.after(_DATA_RETRANSMIT_S, transmit)
                return
            next_head()
            return
        loop.after(
            _NETWORK_LATENCY_S,
            lambda: data_protocol._process_datagram(packet, data_addr, received_mono_s=clock.now_s),
        )
        # The server's DATA_ACK comes back one more network hop later.
        loop.after(2 * _NETWORK_LATENCY_S, next_head)

    def next_head() -> None:
        queue.popleft()
        head_attempts[0] = 0
        if queue:
            transmit()

    pending_tx_delay = [0.0]

    def schedule_next() -> None:
        assert sensor.first_due_us is not None and sim.rng is not None
        frame_start_us = sensor.first_due_us + sensor.frame_index * frame_duration_us
        ready_s = sim.monotonic_at_device_us(frame_start_us + frame_duration_us)
        pending_tx_delay[0] = float(sim.rng.uniform(0.0, sim.send_jitter_s))
        loop.at(ready_s, enqueue)

    def wait_handshake() -> None:
        if not sim.handshake_complete:
            loop.after(_HANDSHAKE_POLL_S, wait_handshake)
            return
        sensor.first_due_us = float(sim.device_time_us()) + sim.start_offset_s * 1_000_000.0
        schedule_next()

    loop.after(_HANDSHAKE_POLL_S, wait_handshake)


def _processing_ticker(
    runner: asyncio.Runner,
    tick_runner: ProcessingTickRunner,
    clock: _VirtualClock,
) -> Callable[[], None]:
    next_sync_s: list[float | None] = [None]

    def tick() -> None:
        now_s = clock.now_s
        if next_sync_s[0] is None:
            next_sync_s[0] = now_s + CLOCK_SYNC_INTERVAL_S
        sync_clock = now_s >= next_sync_s[0]
        if sync_clock:
            next_sync_s[0] += CLOCK_SYNC_INTERVAL_S
        runner.run(tick_runner.run(sync_clock=sync_clock))

    return tick


def _flush_tick(recorder: RunRecorder) -> None:
    """One pass of ``_recorder_runtime.run_loop``: flush, and stop at the recording cap."""
    run_id, auto_stop_reason = recorder.flush_tick()
    if auto_stop_reason is None:
        return
    # The sensors stream through the whole drive, so only the cap may stop it.
    assert auto_stop_reason == "max_duration", (run_id, auto_stop_reason)
    recorder.stop_recording(_only_if_run_id=run_id, reason=auto_stop_reason)


def _speed_setter(
    gps: GPSSpeedMonitor, obd: ObdService, clients: Sequence[SimClient], speed_source: SpeedSource
) -> Callable[[float], None]:
    def set_speed(speed_kmh: float) -> None:
        for client in clients:
            client.current_speed_kmh = speed_kmh
        if speed_source == "obd2":
            # One completed speed PID read, as ``ObdConnectionExecutor`` polls it.
            speed = ObdPidPollResult(
                value=float(round(speed_kmh)),
                raw_response=None,
                error=None,
                duration_s=0.0,
                executed=True,
                started_at_s=time.monotonic(),
            )
            obd.apply_poll_cycle(ObdPollResult(rpm=ObdPidPollResult.skipped(), speed=speed))
            return
        # One gpsd TPV report with a 3D fix, as ``GPSTransportRunner`` reads it.
        gps._transport.ingest_message({"class": "TPV", "mode": 3, "speed": speed_kmh / 3.6})

    return set_speed


def _assign_location(runtime: AppRuntime, client_id: str, location_code: str) -> None:
    """Mirror ``POST /api/clients/{id}/location``."""
    web = runtime.web
    stored = web.sensor_metadata_store.assign_sensor_location(client_id, location_code)
    stored_sensor = stored[client_id]
    web.registry.set_location(client_id, stored_sensor["location_code"])
    web.registry.set_name(client_id, stored_sensor["name"])


def _schedule_phase(
    loop: _EventLoop,
    set_speed: Callable[[float], None],
    clients: list[SimClient],
    scenario_name: str,
    phase: ScenarioPhase,
    phase_start_s: float,
    guided: bool,
    recorder: RunRecorder,
) -> None:
    """Replay one scripted phase the way ``run_scripted_scenario`` does."""

    def begin() -> None:
        apply_phase(clients, scenario_name, phase)
        if guided:
            recorder.mark_guided_phase(phase.guided_phase)

    loop.at(phase_start_s, begin)
    for pulse in phase.pulses:
        loop.at(
            phase_start_s + pulse.at_s,
            lambda pulse=pulse: [
                client.pulse(pulse.strength) for client in target_clients(clients, pulse.target)
            ],
        )
    elapsed = 0.0
    while elapsed <= phase.duration_s:
        speed = phase_speed_kmh(phase, elapsed)
        loop.at(
            phase_start_s + elapsed + 1e-6,
            lambda speed=speed: set_speed(speed),
        )
        elapsed += _SPEED_UPDATE_PERIOD_S
