"""Regression sample builders for order-tracking and phase tests."""

from __future__ import annotations

from typing import Any

from test_support.sample_builders import make_sample
from vibesensor.shared.constants.units import KMH_TO_MPS

_ORDER_SOURCES: set[str] = {"wheel/tire", "driveline", "engine"}


def max_order_source_conf(
    summary: dict[str, Any],
    sources: set[str] = _ORDER_SOURCES,
) -> float:
    """Return max confidence among non-reference order-tracking findings."""
    return max(
        (
            float(finding.get("confidence") or 0.0)
            for finding in summary.get("findings", [])
            if not str(finding.get("finding_id", "")).startswith("REF_")
            and str(finding.get("suspected_source") or "").strip().lower() in sources
        ),
        default=0.0,
    )


def build_speed_sweep_samples(
    *,
    n: int = 40,
    speed_start_kmh: float = 30.0,
    speed_end_kmh: float = 120.0,
    dt: float = 1.0,
    tire_circumference_m: float = 2.036,
    client_name: str = "Front Left Wheel",
    peak_amp: float = 0.05,
    add_wheel_1x: bool = True,
    vib_db: float = 18.0,
) -> list[dict[str, Any]]:
    """Create samples with linearly increasing speed and optional wheel-1x peaks."""
    samples: list[dict[str, Any]] = []
    for idx in range(n):
        t = idx * dt
        speed = speed_start_kmh + (speed_end_kmh - speed_start_kmh) * (idx / max(1, n - 1))
        peaks: list[dict[str, float]] = []
        if add_wheel_1x:
            w_hz = speed * KMH_TO_MPS / tire_circumference_m if tire_circumference_m > 0 else None
            if w_hz and w_hz > 0:
                peaks.append({"hz": w_hz, "amp": peak_amp})
        peaks.append({"hz": 142.5, "amp": 0.003})
        samples.append(
            make_sample(
                t_s=t,
                speed_kmh=speed,
                vibration_strength_db=vib_db,
                client_name=client_name,
                top_peaks=peaks,
                strength_floor_amp_g=0.003,
            ),
        )
    return samples


def build_phased_samples(
    phase_segments: list[tuple[int, float, float]],
    *,
    start_t_s: float = 0.0,
    dt_s: float = 1.0,
    client_name: str = "Front Left Wheel",
) -> list[dict[str, Any]]:
    """Build samples from phase segments expressed as ``(count, start, end)``."""
    samples: list[dict[str, Any]] = []
    t_s = start_t_s
    for count, speed_start, speed_end in phase_segments:
        if count <= 0:
            continue
        for idx in range(count):
            if count == 1:
                speed_kmh = float(speed_end)
            else:
                ratio = idx / (count - 1)
                speed_kmh = float(speed_start + ((speed_end - speed_start) * ratio))
            samples.append(make_sample(t_s=t_s, speed_kmh=speed_kmh, client_name=client_name))
            t_s += dt_s
    return samples
