from __future__ import annotations

from dataclasses import dataclass

from vibesensor.common.units import KMH_TO_MPS
from vibesensor.domain.analysis_settings import ANALYSIS_SETTINGS_DEFAULTS, AnalysisSettingsSnapshot
from vibesensor.dsp.order_bands import vehicle_orders_hz
from vibesensor.settings.analysis_settings_codec import (
    analysis_settings_snapshot_from_mapping,
)

DEFAULT_SPEED_KMH = 100.0


def calc_order_hz(
    settings: AnalysisSettingsSnapshot,
    *,
    speed_kmh: float = DEFAULT_SPEED_KMH,
) -> dict[str, float] | None:
    """Return wheel/shaft/engine order frequencies for a car at ``speed_kmh``.

    Uses the same order-reference math as the analysis, so simulated order
    tones land exactly on the orders the server tracks for that car.
    """
    orders = vehicle_orders_hz(speed_mps=speed_kmh * KMH_TO_MPS, settings=settings)
    if orders is None:
        return None
    wheel_1x = float(orders["wheel_hz"])
    engine_1x = float(orders["engine_hz"])
    return {
        "wheel_1x": wheel_1x,
        "wheel_2x": wheel_1x * 2.0,
        "shaft_1x": float(orders["drive_hz"]),
        "engine_1x": engine_1x,
        "engine_2x": engine_1x * 2.0,
    }


def calc_default_orders() -> dict[str, float]:
    orders = calc_order_hz(analysis_settings_snapshot_from_mapping(ANALYSIS_SETTINGS_DEFAULTS))
    if orders is None:
        raise ValueError("Failed to compute order frequencies from default car specs")
    return orders


DEFAULT_ORDER_HZ = calc_default_orders()


@dataclass(frozen=True, slots=True)
class Profile:
    name: str
    tones: tuple[tuple[float, tuple[float, float, float]], ...]
    noise_std: float
    bump_probability: float
    bump_decay: float
    bump_strength: tuple[float, float, float]
    modulation_hz: float
    modulation_depth: float
    # Order-locked tones as ``(order_key, multiple, amps_xyz)``; ``order_key``
    # indexes the client's ``order_hz`` (orders at ``reference_speed_kmh`` for
    # the simulated car), so they track both speed and the active car.
    order_tones: tuple[tuple[str, float, tuple[float, float, float]], ...] = ()
    # Speed at which ``order_hz`` is defined; ``make_frame()`` scales order
    # tones by ``current_speed / reference_speed``. ``None`` means the
    # profile has only absolute tones (e.g. engine_idle, rough_road).
    reference_speed_kmh: float | None = None


PROFILE_LIBRARY: dict[str, Profile] = {
    "engine_idle": Profile(
        name="engine_idle",
        tones=(
            (13.0, (170.0, 120.0, 250.0)),
            (26.0, (55.0, 40.0, 85.0)),
            (39.0, (30.0, 24.0, 45.0)),
        ),
        noise_std=22.0,
        bump_probability=0.001,
        bump_decay=0.96,
        bump_strength=(18.0, 15.0, 28.0),
        modulation_hz=0.35,
        modulation_depth=0.10,
    ),
    "engine_order": Profile(
        name="engine_order",
        tones=(),
        order_tones=(
            ("engine_1x", 1.0, (185.0, 128.0, 248.0)),
            ("engine_2x", 1.0, (62.0, 46.0, 92.0)),
            ("engine_1x", 0.5, (30.0, 22.0, 44.0)),
        ),
        noise_std=18.0,
        bump_probability=0.001,
        bump_decay=0.96,
        bump_strength=(16.0, 13.0, 24.0),
        modulation_hz=0.24,
        modulation_depth=0.10,
        reference_speed_kmh=DEFAULT_SPEED_KMH,
    ),
    "rough_road": Profile(
        name="rough_road",
        tones=(
            (8.0, (80.0, 90.0, 130.0)),
            (15.0, (105.0, 95.0, 140.0)),
            (34.0, (55.0, 45.0, 85.0)),
        ),
        noise_std=28.0,
        bump_probability=0.012,
        bump_decay=0.92,
        bump_strength=(45.0, 55.0, 80.0),
        modulation_hz=0.45,
        modulation_depth=0.16,
    ),
    "wheel_imbalance": Profile(
        name="wheel_imbalance",
        tones=(),
        order_tones=(
            ("wheel_1x", 1.0, (220.0, 125.0, 170.0)),
            ("wheel_2x", 1.0, (80.0, 52.0, 72.0)),
            ("wheel_1x", 0.52, (24.0, 18.0, 30.0)),
        ),
        noise_std=24.0,
        bump_probability=0.004,
        bump_decay=0.94,
        bump_strength=(30.0, 24.0, 45.0),
        modulation_hz=0.22,
        modulation_depth=0.12,
        reference_speed_kmh=DEFAULT_SPEED_KMH,
    ),
    "wheel_mild_imbalance": Profile(
        name="wheel_mild_imbalance",
        tones=(),
        order_tones=(
            ("wheel_1x", 1.0, (105.0, 62.0, 80.0)),
            ("wheel_2x", 1.0, (28.0, 18.0, 24.0)),
            ("wheel_1x", 0.52, (8.0, 6.0, 10.0)),
        ),
        noise_std=14.0,
        bump_probability=0.001,
        bump_decay=0.96,
        bump_strength=(10.0, 8.0, 14.0),
        modulation_hz=0.18,
        modulation_depth=0.08,
        reference_speed_kmh=DEFAULT_SPEED_KMH,
    ),
    "rear_body": Profile(
        name="rear_body",
        tones=(
            (6.5, (70.0, 88.0, 120.0)),
            (14.0, (48.0, 60.0, 82.0)),
            (28.0, (34.0, 28.0, 50.0)),
        ),
        noise_std=22.0,
        bump_probability=0.006,
        bump_decay=0.95,
        bump_strength=(30.0, 34.0, 50.0),
        modulation_hz=0.28,
        modulation_depth=0.14,
    ),
}
