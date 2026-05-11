"""Engine-order fault sample builders."""

from __future__ import annotations

from typing import Any

from test_support.core import _stable_hash, engine_hz
from test_support.sample_scenarios import make_sample


def make_engine_order_samples(
    *,
    sensors: list[str],
    speed_kmh: float = 80.0,
    n_samples: int = 30,
    dt_s: float = 1.0,
    start_t_s: float = 0.0,
    engine_amp: float = 0.05,
    engine_vib_db: float = 24.0,
    noise_amp: float = 0.004,
    _engine_hz_override: float | None = None,
) -> list[dict[str, Any]]:
    """Generate engine-order harmonics on all sensors."""
    ehz = _engine_hz_override if _engine_hz_override is not None else engine_hz(speed_kmh)
    samples: list[dict[str, Any]] = []
    for i in range(n_samples):
        t = start_t_s + i * dt_s
        for sensor in sensors:
            jitter = (_stable_hash(sensor + str(i)) % 10) * 0.001
            peaks = [
                {"hz": ehz, "amp": engine_amp + jitter},
                {"hz": ehz * 2, "amp": (engine_amp + jitter) * 0.5},
                {"hz": ehz * 0.5, "amp": (engine_amp + jitter) * 0.3},
                {"hz": 200.0, "amp": noise_amp},
            ]
            samples.append(
                make_sample(
                    t_s=t,
                    speed_kmh=speed_kmh,
                    client_name=sensor,
                    top_peaks=peaks,
                    vibration_strength_db=engine_vib_db,
                    strength_floor_amp_g=noise_amp,
                    engine_rpm=ehz * 60.0,
                ),
            )
    return samples
