from __future__ import annotations

from dataclasses import dataclass

from vibesensor.common.units import KMH_TO_MPS
from vibesensor.domain.analysis_settings import ANALYSIS_SETTINGS_DEFAULTS, AnalysisSettingsSnapshot
from vibesensor.dsp.order_bands import vehicle_orders_hz
from vibesensor.settings.analysis_settings_codec import (
    analysis_settings_snapshot_from_mapping,
)

DEFAULT_SPEED_KMH = 100.0


SIMULATOR_CAR_ASPECTS: dict[str, float] = {
    **ANALYSIS_SETTINGS_DEFAULTS,
    "tire_width_mm": 285.0,
    "tire_aspect_pct": 30.0,
    "rim_in": 21.0,
    "final_drive_ratio": 3.08,
    "current_gear_ratio": 0.64,
}
"""The simulated car's specs, used until the server's active car provides all of its own."""


def calc_order_hz(
    settings: AnalysisSettingsSnapshot,
    *,
    speed_kmh: float = DEFAULT_SPEED_KMH,
) -> dict[str, float] | None:
    """Return wheel/shaft/engine order frequencies for a car at ``speed_kmh``.

    Uses the same order-reference math as the analysis, so simulated order
    tones land exactly on the orders the server tracks for that car. Returns
    ``None`` unless the car has every reference (tire, final drive, gear).
    """
    orders = vehicle_orders_hz(speed_mps=speed_kmh * KMH_TO_MPS, settings=settings)
    wheel_1x = orders.get("wheel_hz")
    shaft_1x = orders.get("drive_hz")
    engine_1x = orders.get("engine_hz")
    if wheel_1x is None or shaft_1x is None or engine_1x is None:
        return None
    return {
        "wheel_1x": wheel_1x,
        "wheel_2x": wheel_1x * 2.0,
        "shaft_1x": shaft_1x,
        "engine_1x": engine_1x,
        "engine_2x": engine_1x * 2.0,
    }


def calc_default_orders() -> dict[str, float]:
    orders = calc_order_hz(analysis_settings_snapshot_from_mapping(SIMULATOR_CAR_ASPECTS))
    if orders is None:
        raise ValueError("Failed to compute order frequencies from the simulator car specs")
    return orders


DEFAULT_ORDER_HZ = calc_default_orders()


@dataclass(frozen=True, slots=True)
class Profile:
    name: str
    # Fixed-frequency tones ``(hz, amps_xyz)``: body resonances and idle shake,
    # the same frequency at every speed.
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
    # Road noise grows with speed: the broadband noise is scaled by
    # ``(speed / DEFAULT_SPEED_KMH) ** noise_speed_exponent`` (0: flat).
    noise_speed_exponent: float = 0.0
    # An unbalanced mass shakes harder the faster it turns: order-tone
    # amplitudes are scaled by ``(speed / reference_speed) ** order_speed_exponent``
    # (0: the same amplitude at every speed).
    order_speed_exponent: float = 0.0
    # ``(low_kmh, high_kmh, gain)``: a suspension or body resonance the order
    # passes through amplifies its tones by ``gain`` inside that speed band.
    order_resonance_kmh: tuple[float, float, float] | None = None

    def order_amplitude_gain(self, speed_kmh: float) -> float:
        """How much the order tones are amplified at *speed_kmh* (1 at the reference speed)."""
        gain = 1.0
        if self.order_speed_exponent and self.reference_speed_kmh:
            gain = (max(0.0, speed_kmh) / self.reference_speed_kmh) ** self.order_speed_exponent
        if self.order_resonance_kmh is not None:
            low_kmh, high_kmh, resonance_gain = self.order_resonance_kmh
            if low_kmh <= speed_kmh <= high_kmh:
                gain *= resonance_gain
        return gain

    def noise_gain(self, speed_kmh: float) -> float:
        """How much the broadband noise grows with *speed_kmh* (1 at ``DEFAULT_SPEED_KMH``)."""
        if not self.noise_speed_exponent:
            return 1.0
        return float((max(0.0, speed_kmh) / DEFAULT_SPEED_KMH) ** self.noise_speed_exponent)


# A profile only carries the tones of the source it simulates. Road and body
# profiles are broadband noise plus impacts: a healthy car has no order tones,
# so fault-free sensors and scenarios stay free of wheel/driveshaft/engine orders.
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
        # A 4-stroke 4-cylinder fires twice per crank revolution, so its
        # load-dependent vibration is dominated by the 2nd engine order (E2).
        order_tones=(
            ("engine_2x", 1.0, (185.0, 128.0, 248.0)),
            ("engine_1x", 1.0, (62.0, 46.0, 92.0)),
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
        tones=(),
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
        ),
        noise_std=14.0,
        bump_probability=0.001,
        bump_decay=0.96,
        bump_strength=(10.0, 8.0, 14.0),
        modulation_hz=0.18,
        modulation_depth=0.08,
        reference_speed_kmh=DEFAULT_SPEED_KMH,
    ),
    "driveshaft_imbalance": Profile(
        name="driveshaft_imbalance",
        tones=(),
        order_tones=(
            ("shaft_1x", 1.0, (150.0, 120.0, 190.0)),
            ("shaft_1x", 2.0, (45.0, 36.0, 60.0)),
        ),
        noise_std=20.0,
        bump_probability=0.002,
        bump_decay=0.95,
        bump_strength=(18.0, 15.0, 26.0),
        modulation_hz=0.2,
        modulation_depth=0.10,
        reference_speed_kmh=DEFAULT_SPEED_KMH,
    ),
    "rear_body": Profile(
        name="rear_body",
        tones=(),
        noise_std=22.0,
        bump_probability=0.006,
        bump_decay=0.95,
        bump_strength=(30.0, 34.0, 50.0),
        modulation_hz=0.28,
        modulation_depth=0.14,
    ),
}
