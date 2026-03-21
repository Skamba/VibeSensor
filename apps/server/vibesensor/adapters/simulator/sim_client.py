from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from vibesensor.adapters.simulator.profiles import (
    DEFAULT_ORDER_HZ,
    DEFAULT_SPEED_KMH,
    PROFILE_LIBRARY,
    Profile,
)
from vibesensor.adapters.udp.protocol import client_id_mac

__all__ = ["SimClient", "make_client_id"]

_TWO_PI = 2.0 * np.pi

_COMMON_TONES: tuple[tuple[float, tuple[float, float, float]], ...] = (
    (DEFAULT_ORDER_HZ["wheel_1x"], (70.0, 58.0, 82.0)),
    (DEFAULT_ORDER_HZ["wheel_2x"], (46.0, 38.0, 54.0)),
    (DEFAULT_ORDER_HZ["shaft_1x"], (95.0, 76.0, 110.0)),
    (DEFAULT_ORDER_HZ["engine_2x"], (64.0, 52.0, 78.0)),
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
    send_period_scale: float = 1.0
    send_jitter_s: float = 0.0
    start_offset_s: float = 0.0
    control_transport: asyncio.DatagramTransport | None = None
    data_transport: asyncio.DatagramTransport | None = None
    bump_state: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float32))
    phase_offsets: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=np.float32))
    rng: np.random.Generator | None = None

    def __post_init__(self) -> None:
        seed = int.from_bytes(self.client_id, "little")
        self.rng = np.random.default_rng(seed)
        self.phase_offsets = np.asarray(self.rng.uniform(0.0, np.pi, size=3), dtype=np.float32)
        # Intentional slight timing mismatch between sensors to mimic real deployments.
        self.send_period_scale = float(self.rng.uniform(0.997, 1.003))
        self.send_jitter_s = float(self.rng.uniform(0.001, 0.007))
        self.start_offset_s = float(self.rng.uniform(0.0, 0.045))

    @property
    def profile(self) -> Profile:
        return PROFILE_LIBRARY[self.profile_name]

    @property
    def mac_address(self) -> str:
        return client_id_mac(self.client_id)

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
            f"tx_scale={self.send_period_scale:.5f} "
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
        signal: np.ndarray[Any, np.dtype[Any]] = np.zeros((self.frame_samples, 3), dtype=np.float32)

        # Compute speed-scaling ratio for order-based profiles.
        # Tones in wheel_imbalance / wheel_mild_imbalance were defined at the
        # reference speed; scale them proportionally to the current speed.
        speed_ratio = 1.0
        if profile.reference_speed_kmh and profile.reference_speed_kmh > 0:
            speed_ratio = max(0.0, self.current_speed_kmh) / profile.reference_speed_kmh

        _sin = np.sin
        _phase = self.phase_offsets
        for freq_hz, amps_xyz in profile.tones:
            effective_hz = freq_hz * speed_ratio
            if effective_hz <= 0:
                continue
            omega_t = _TWO_PI * effective_hz * t
            signal[:, 0] += amps_xyz[0] * _sin(omega_t + _phase[0])
            signal[:, 1] += amps_xyz[1] * _sin(omega_t + _phase[1])
            signal[:, 2] += amps_xyz[2] * _sin(omega_t + _phase[2])

        if self.common_event_gain > 0:
            # Common order tones shared by all sensors.
            # Scale by current speed vs DEFAULT_SPEED_KMH reference.
            common_speed_ratio = (
                max(0.0, self.current_speed_kmh) / DEFAULT_SPEED_KMH
                if DEFAULT_SPEED_KMH > 0
                else 1.0
            )
            _gain = self.common_event_gain
            for freq_hz, amps_xyz in _COMMON_TONES:
                effective_hz = freq_hz * common_speed_ratio
                if effective_hz <= 0:
                    continue
                omega_t = _TWO_PI * effective_hz * t
                signal[:, 0] += _gain * amps_xyz[0] * _sin(omega_t)
                signal[:, 1] += _gain * amps_xyz[1] * _sin(omega_t + 0.2)
                signal[:, 2] += _gain * amps_xyz[2] * _sin(omega_t + 0.4)

        signal *= modulation[:, None]

        for i in range(self.frame_samples):
            if self.rng.random() < profile.bump_probability:
                jitter = self.rng.uniform(0.85, 1.15, size=3).astype(np.float32)
                self.bump_state += np.asarray(profile.bump_strength, dtype=np.float32) * jitter
            signal[i] += self.bump_state
            self.bump_state *= profile.bump_decay

        noise = self.rng.normal(
            0.0,
            profile.noise_std * self.noise_scale * self.scene_noise_gain,
            size=signal.shape,
        ).astype(np.float32)
        signal += noise
        signal *= self.amp_scale * self.scene_gain
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
