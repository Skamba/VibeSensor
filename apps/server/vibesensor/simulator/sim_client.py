from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from vibesensor.ingest.protocol_messages import client_id_mac
from vibesensor.simulator.profiles import (
    DEFAULT_ORDER_HZ,
    DEFAULT_SPEED_KMH,
    PROFILE_LIBRARY,
    Profile,
)

__all__ = ["SimClient", "make_client_id"]

_TWO_PI = 2.0 * np.pi

# ESP32 crystals are specified around ±10-40 ppm; stay within that envelope.
_MAX_CLOCK_DRIFT_PPM = 40.0

# Driveline orders shared by every sensor, as (order_key, multiple, amps_xyz).
_COMMON_ORDER_TONES: tuple[tuple[str, float, tuple[float, float, float]], ...] = (
    ("wheel_1x", 1.0, (70.0, 58.0, 82.0)),
    ("wheel_2x", 1.0, (46.0, 38.0, 54.0)),
    ("shaft_1x", 1.0, (95.0, 76.0, 110.0)),
    ("engine_2x", 1.0, (64.0, 52.0, 78.0)),
)


@dataclass(slots=True)
class SimClient:
    name: str
    client_id: bytes
    control_port: int
    sample_rate_hz: int
    frame_samples: int
    server_host: str
    server_data_port: int
    server_control_port: int
    profile_name: str
    seq: int = 0
    phase_s: float = 0.0
    amp_scale: float = 1.0
    noise_scale: float = 1.0
    noise_floor_std: float = 3.5
    scene_gain: float = 1.0
    scene_noise_gain: float = 1.0
    scene_mode: str = "all"
    common_event_gain: float = 0.0
    paused: bool = False
    # Current simulated speed – used to scale order-based profile tones.
    current_speed_kmh: float = DEFAULT_SPEED_KMH
    # Sensor-clock model mirroring the ESP firmware (see firmware/esp/src):
    # samples are scheduled on the device's own microsecond timer, which
    # drifts by a few tens of ppm against the server clock; ``t0_us`` is the
    # first sample's due time plus the server-provided clock offset.
    clock_drift_ppm: float = 0.0
    device_boot_mono_s: float = 0.0
    clock_offset_us: int = 0
    handshake_complete: bool = False
    # Network/scheduling delay between a frame completing and its transmit.
    # It only affects arrival time, never the frame's sample timestamps.
    send_jitter_s: float = 0.0
    start_offset_s: float = 0.0
    control_transport: asyncio.DatagramTransport | None = None
    data_transport: asyncio.DatagramTransport | None = None
    bump_state: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float32))
    phase_offsets: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float32))
    rng: np.random.Generator | None = None
    # Order frequencies at DEFAULT_SPEED_KMH for the simulated car; the
    # simulator refreshes them from the server's active car when reachable.
    order_hz: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_ORDER_HZ))

    def __post_init__(self) -> None:
        seed = int.from_bytes(self.client_id, "little")
        self.rng = np.random.default_rng(seed)
        self.phase_offsets = np.asarray(self.rng.uniform(0.0, np.pi, size=3), dtype=np.float32)
        # Per-sensor crystal error, like real ESP32 boards (tens of ppm), so
        # sensors run at slightly different true rates, as in real deployments.
        self.clock_drift_ppm = float(self.rng.uniform(-_MAX_CLOCK_DRIFT_PPM, _MAX_CLOCK_DRIFT_PPM))
        self.send_jitter_s = float(self.rng.uniform(0.001, 0.007))
        self.start_offset_s = float(self.rng.uniform(0.0, 0.045))
        # The device timer counts from its own boot, unrelated to the server
        # clock, so t0_us only becomes server-relative after clock sync.
        self.device_boot_mono_s = time.monotonic() - float(self.rng.uniform(1.0, 30.0))

    @property
    def profile(self) -> Profile:
        return PROFILE_LIBRARY[self.profile_name]

    @property
    def mac_address(self) -> str:
        return client_id_mac(self.client_id)

    @property
    def _device_clock_scale(self) -> float:
        return 1.0 + (self.clock_drift_ppm * 1e-6)

    def device_time_us(self, mono_s: float | None = None) -> int:
        """Return the simulated device timer (``esp_timer_get_time``) in µs."""
        now_s = time.monotonic() if mono_s is None else mono_s
        return int((now_s - self.device_boot_mono_s) * 1_000_000.0 * self._device_clock_scale)

    def monotonic_at_device_us(self, device_us: float) -> float:
        """Return the host monotonic time at which the device timer reads *device_us*."""
        return self.device_boot_mono_s + (device_us / (1_000_000.0 * self._device_clock_scale))

    def pulse(self, strength: float) -> None:
        vec = np.asarray(self.profile.bump_strength, dtype=np.float32)
        self.bump_state += vec * np.float32(strength)

    def summary(self) -> str:
        return (
            f"{self.name} id={self.client_id.hex()} "
            f"mac={self.mac_address} profile={self.profile_name} "
            f"amp={self.amp_scale:.2f} noise={self.noise_scale:.2f} "
            f"floor={self.noise_floor_std:.1f} "
            f"scene={self.scene_mode}:{self.scene_gain:.2f} "
            f"common={self.common_event_gain:.2f} paused={self.paused} "
            f"clock_drift={self.clock_drift_ppm:+.1f}ppm "
            f"tx_jitter={self.send_jitter_s * 1000:.1f}ms "
            f"offset={self.start_offset_s * 1000:.1f}ms"
        )

    def make_frame(self) -> np.ndarray:
        if self.paused:
            self.phase_s += self.frame_samples / self.sample_rate_hz
            return np.zeros((self.frame_samples, 3), dtype=np.int16)

        assert self.rng is not None  # guaranteed by __post_init__
        profile = self.profile

        dt = 1.0 / self.sample_rate_hz
        t = self.phase_s + np.arange(self.frame_samples, dtype=np.float32) * dt

        modulation = 1.0 + profile.modulation_depth * np.sin(_TWO_PI * profile.modulation_hz * t)
        local_signal: np.ndarray[Any, np.dtype[Any]] = np.zeros(
            (self.frame_samples, 3), dtype=np.float32
        )
        common_signal: np.ndarray[Any, np.dtype[Any]] = np.zeros(
            (self.frame_samples, 3), dtype=np.float32
        )

        # Order tones are defined at the reference speed; scale them
        # proportionally to the current speed.
        speed_ratio = 1.0
        if profile.reference_speed_kmh and profile.reference_speed_kmh > 0:
            speed_ratio = max(0.0, self.current_speed_kmh) / profile.reference_speed_kmh

        _sin = np.sin
        _phase = self.phase_offsets
        order_hz = self.order_hz
        local_tones = [(freq_hz * speed_ratio, amps_xyz) for freq_hz, amps_xyz in profile.tones]
        local_tones.extend(
            (order_hz[order_key] * multiple * speed_ratio, amps_xyz)
            for order_key, multiple, amps_xyz in profile.order_tones
        )
        for effective_hz, amps_xyz in local_tones:
            if effective_hz <= 0:
                continue
            omega_t = _TWO_PI * effective_hz * t
            local_signal[:, 0] += amps_xyz[0] * _sin(omega_t + _phase[0])
            local_signal[:, 1] += amps_xyz[1] * _sin(omega_t + _phase[1])
            local_signal[:, 2] += amps_xyz[2] * _sin(omega_t + _phase[2])

        if self.common_event_gain > 0:
            # Common order tones shared by all sensors.
            # Scale by current speed vs DEFAULT_SPEED_KMH reference.
            common_speed_ratio = (
                max(0.0, self.current_speed_kmh) / DEFAULT_SPEED_KMH
                if DEFAULT_SPEED_KMH > 0
                else 1.0
            )
            _gain = self.common_event_gain
            for order_key, multiple, amps_xyz in _COMMON_ORDER_TONES:
                effective_hz = order_hz[order_key] * multiple * common_speed_ratio
                if effective_hz <= 0:
                    continue
                omega_t = _TWO_PI * effective_hz * t
                common_signal[:, 0] += _gain * amps_xyz[0] * _sin(omega_t)
                common_signal[:, 1] += _gain * amps_xyz[1] * _sin(omega_t + 0.2)
                common_signal[:, 2] += _gain * amps_xyz[2] * _sin(omega_t + 0.4)

        local_signal *= modulation[:, None]

        for i in range(self.frame_samples):
            if self.rng.random() < profile.bump_probability:
                jitter = self.rng.uniform(0.85, 1.15, size=3).astype(np.float32)
                self.bump_state += np.asarray(profile.bump_strength, dtype=np.float32) * jitter
            local_signal[i] += self.bump_state
            self.bump_state *= profile.bump_decay

        noise = self.rng.normal(
            0.0,
            profile.noise_std * self.noise_scale * self.scene_noise_gain,
            size=local_signal.shape,
        ).astype(np.float32)
        local_signal += noise
        local_signal *= self.amp_scale * self.scene_gain
        # Keep shared/common tones independent from the local corner gain so
        # generic driveline content does not inherit wheel-fault amplification.
        signal = local_signal + common_signal
        # Keep a minimum broadband floor on every sensor even in quiet/low-gain scenes.
        floor_noise = self.rng.normal(
            0.0,
            self.noise_floor_std,
            size=signal.shape,
        ).astype(np.float32)
        signal += floor_noise

        self.phase_s = float(t[-1] + dt)
        result: np.ndarray[Any, np.dtype[Any]] = np.clip(signal, -32768, 32767).astype(np.int16)
        return result


def make_client_id(seed: int) -> bytes:
    rng = random.Random(seed)
    return bytes(
        [
            0x02,  # locally administered unicast
            0x5A,
            rng.randrange(0, 255),
            rng.randrange(0, 255),
            rng.randrange(0, 255),
            seed & 0xFF,
        ]
    )
