"""Scenario definitions and materializers for analysis fuzzing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

SENSOR_FIXTURES: tuple[dict[str, str], ...] = (
    {
        "client_id": "fl-wheel",
        "client_name": "Front Left Wheel",
        "location": "front_left_wheel",
    },
    {
        "client_id": "fr-wheel",
        "client_name": "Front Right Wheel",
        "location": "front_right_wheel",
    },
    {
        "client_id": "rl-wheel",
        "client_name": "Rear Left Wheel",
        "location": "rear_left_wheel",
    },
    {
        "client_id": "rr-wheel",
        "client_name": "Rear Right Wheel",
        "location": "rear_right_wheel",
    },
    {
        "client_id": "drive-tunnel",
        "client_name": "Driveshaft Tunnel",
        "location": "driveshaft_tunnel",
    },
    {
        "client_id": "engine-bay",
        "client_name": "Engine Bay",
        "location": "engine_bay",
    },
    {
        "client_id": "driver-seat",
        "client_name": "Driver Seat",
        "location": "driver_seat",
    },
)

SCENARIO_KINDS: tuple[str, ...] = (
    "idle",
    "steady",
    "accel",
    "decel",
    "oscillate",
)

FAULT_KINDS: tuple[str, ...] = (
    "none",
    "wheel",
    "driveline",
    "engine",
    "random",
)

LANGUAGE_CHOICES: tuple[str | None, ...] = (None, "en", "EN", "nl", "NL")
SENSOR_MODELS: tuple[str, ...] = ("ADXL345", "ICM-42688-P", "LSM6DSOX", "unknown")


def timestamp_at(offset_s: float) -> str:
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    return (base + timedelta(seconds=offset_s)).isoformat().replace("+00:00", "Z")


def sample_rate_from_metadata(metadata: Mapping[str, object]) -> int | None:
    raw = metadata.get("raw_sample_rate_hz")
    return int(raw) if isinstance(raw, int) else None


def coerce_include_samples(case: Mapping[str, object], override: bool | None) -> bool:
    if override is not None:
        return override
    raw = case.get("include_samples")
    return bool(raw) if isinstance(raw, bool) else False


def metadata_strategy(st: Any) -> Any:
    positive_int = st.integers(min_value=32, max_value=6400)
    positive_float = st.floats(
        min_value=0.05, max_value=2.0, allow_nan=False, allow_infinity=False
    )
    settings_float = st.floats(
        min_value=0.1,
        max_value=10.0,
        allow_nan=False,
        allow_infinity=False,
    )
    return st.fixed_dictionaries(
        {
            "run_id": st.from_regex(r"[a-z0-9][a-z0-9_-]{2,20}", fullmatch=True),
            "start_time_utc": st.just(timestamp_at(0.0)),
            "end_time_utc": st.one_of(
                st.none(),
                st.just(timestamp_at(60.0)),
                st.just(timestamp_at(180.0)),
            ),
            "sensor_model": st.sampled_from(SENSOR_MODELS),
            "raw_sample_rate_hz": st.one_of(st.none(), positive_int, st.just(0)),
            "feature_interval_s": st.one_of(st.none(), positive_float),
            "fft_window_size_samples": st.one_of(
                st.none(),
                st.sampled_from((128, 256, 512, 1024, 2048, 4096)),
            ),
            "accel_scale_g_per_lsb": st.one_of(
                st.none(),
                st.floats(
                    min_value=1e-5,
                    max_value=0.05,
                    allow_nan=False,
                    allow_infinity=False,
                ),
            ),
            "language": st.one_of(st.none(), st.sampled_from(("en", "nl", "EN", "NL"))),
            "incomplete_for_order_analysis": st.booleans(),
            "tire_width_mm": st.floats(
                min_value=100.0,
                max_value=355.0,
                allow_nan=False,
                allow_infinity=False,
            ),
            "tire_aspect_pct": st.floats(
                min_value=25.0,
                max_value=80.0,
                allow_nan=False,
                allow_infinity=False,
            ),
            "rim_in": st.floats(
                min_value=13.0,
                max_value=24.0,
                allow_nan=False,
                allow_infinity=False,
            ),
            "final_drive_ratio": settings_float,
            "current_gear_ratio": st.floats(
                min_value=0.4,
                max_value=4.8,
                allow_nan=False,
                allow_infinity=False,
            ),
        }
    )


def sensor_selection_strategy(st: Any) -> Any:
    return st.lists(
        st.sampled_from(SENSOR_FIXTURES),
        min_size=1,
        max_size=4,
        unique_by=lambda sensor: sensor["client_id"],
    )


def speed_for_step(
    kind: str,
    step: int,
    total_steps: int,
    low_kmh: float,
    high_kmh: float,
) -> float:
    if total_steps <= 1:
        return low_kmh
    ratio = step / float(total_steps - 1)
    if kind == "idle":
        return 0.0
    if kind == "steady":
        return low_kmh
    if kind == "accel":
        return low_kmh + ((high_kmh - low_kmh) * ratio)
    if kind == "decel":
        return high_kmh - ((high_kmh - low_kmh) * ratio)
    midpoint = 0.5
    swing = abs(ratio - midpoint) / midpoint
    return low_kmh + ((high_kmh - low_kmh) * (1.0 - swing))


def build_peak(
    *,
    hz: float,
    amp_g: float,
    vibration_strength_db_scalar: Any,
    bucket_for_strength: Any,
    floor_amp_g: float,
) -> dict[str, float | str]:
    strength_db = vibration_strength_db_scalar(
        peak_band_rms_amp_g=amp_g,
        floor_amp_g=floor_amp_g,
    )
    return {
        "hz": round(max(0.1, hz), 3),
        "amp": round(max(1e-6, amp_g), 6),
        "vibration_strength_db": round(strength_db, 3),
        "strength_bucket": bucket_for_strength(strength_db),
    }


def order_hz_for_fault(
    *,
    fault_kind: str,
    speed_kmh: float | None,
    metadata: Mapping[str, object],
    AnalysisSettingsSnapshot: Any,
    vehicle_orders_hz: Any,
) -> float | None:
    if speed_kmh is None or speed_kmh <= 0.0:
        return None
    settings = AnalysisSettingsSnapshot.from_dict(metadata)
    order_refs = vehicle_orders_hz(speed_mps=speed_kmh / 3.6, settings=settings)
    if not isinstance(order_refs, Mapping):
        return None
    if fault_kind == "wheel":
        value = order_refs.get("wheel_hz")
        return float(value) if isinstance(value, int | float) else None
    if fault_kind == "driveline":
        value = order_refs.get("drive_hz")
        return float(value) if isinstance(value, int | float) else None
    if fault_kind == "engine":
        value = order_refs.get("engine_hz")
        return float(value) if isinstance(value, int | float) else None
    return None


def sample_case_strategy(st: Any) -> Any:
    @st.composite
    def _build(draw: Any) -> dict[str, object]:
        metadata = draw(metadata_strategy(st))
        sensors = draw(sensor_selection_strategy(st))
        scenario = draw(st.sampled_from(SCENARIO_KINDS))
        fault_kind = draw(st.sampled_from(FAULT_KINDS))
        include_samples = draw(st.booleans())
        lang = draw(st.sampled_from(LANGUAGE_CHOICES))
        steps = draw(st.integers(min_value=0, max_value=28))
        dt_s = draw(
            st.floats(
                min_value=0.2,
                max_value=2.5,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        low_speed = draw(
            st.floats(
                min_value=10.0,
                max_value=90.0,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        high_speed = draw(
            st.floats(
                min_value=max(low_speed + 5.0, 20.0),
                max_value=180.0,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        floor_amp_g = draw(
            st.floats(
                min_value=0.0005,
                max_value=0.05,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        base_fault_amp_g = draw(
            st.floats(
                min_value=0.002,
                max_value=0.4,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        diffuse_excitation = draw(st.booleans())
        missing_speed_ratio = draw(
            st.floats(
                min_value=0.0,
                max_value=0.7,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        blank_location_ratio = draw(
            st.floats(
                min_value=0.0,
                max_value=0.5,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        drop_counter = draw(st.integers(min_value=0, max_value=100))
        overflow_counter = draw(st.integers(min_value=0, max_value=30))
        accel_scale = draw(
            st.floats(
                min_value=0.005,
                max_value=0.35,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        background_hz = draw(
            st.floats(
                min_value=8.0,
                max_value=120.0,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        clutter_hz = draw(
            st.floats(
                min_value=20.0,
                max_value=250.0,
                allow_nan=False,
                allow_infinity=False,
            )
        )

        return {
            "metadata": metadata,
            "sensors": sensors,
            "scenario": scenario,
            "fault_kind": fault_kind,
            "include_samples": include_samples,
            "lang": lang,
            "steps": steps,
            "dt_s": dt_s,
            "low_speed": low_speed,
            "high_speed": high_speed,
            "floor_amp_g": floor_amp_g,
            "base_fault_amp_g": base_fault_amp_g,
            "diffuse_excitation": diffuse_excitation,
            "missing_speed_ratio": missing_speed_ratio,
            "blank_location_ratio": blank_location_ratio,
            "drop_counter": drop_counter,
            "overflow_counter": overflow_counter,
            "accel_scale": accel_scale,
            "background_hz": background_hz,
            "clutter_hz": clutter_hz,
        }

    return _build()


def materialize_samples(
    case: Mapping[str, object],
    *,
    vibration_strength_db_scalar: Any,
    bucket_for_strength: Any,
    AnalysisSettingsSnapshot: Any,
    vehicle_orders_hz: Any,
) -> list[dict[str, object]]:
    metadata = case["metadata"]
    if not isinstance(metadata, Mapping):
        raise TypeError("case metadata must be a mapping")
    sensors = case["sensors"]
    if not isinstance(sensors, Sequence):
        raise TypeError("case sensors must be a sequence")

    scenario = str(case["scenario"])
    fault_kind = str(case["fault_kind"])
    steps = int(case["steps"])
    dt_s = float(case["dt_s"])
    low_speed = float(case["low_speed"])
    high_speed = float(case["high_speed"])
    floor_amp_g = float(case["floor_amp_g"])
    base_fault_amp_g = float(case["base_fault_amp_g"])
    diffuse_excitation = bool(case["diffuse_excitation"])
    missing_speed_ratio = float(case["missing_speed_ratio"])
    blank_location_ratio = float(case["blank_location_ratio"])
    drop_counter = int(case["drop_counter"])
    overflow_counter = int(case["overflow_counter"])
    accel_scale = float(case["accel_scale"])
    background_hz = float(case["background_hz"])
    clutter_hz = float(case["clutter_hz"])
    raw_sample_rate_hz = sample_rate_from_metadata(metadata)

    samples: list[dict[str, object]] = []
    for step in range(steps):
        speed_kmh = speed_for_step(scenario, step, steps, low_speed, high_speed)
        if steps > 0 and (step / max(1, steps)) < missing_speed_ratio:
            sampled_speed_kmh: float | None = None
        else:
            sampled_speed_kmh = round(speed_kmh, 3)

        fault_hz = order_hz_for_fault(
            fault_kind=fault_kind,
            speed_kmh=sampled_speed_kmh,
            metadata=metadata,
            AnalysisSettingsSnapshot=AnalysisSettingsSnapshot,
            vehicle_orders_hz=vehicle_orders_hz,
        )
        timestamp_offset = step * dt_s

        for sensor_index, sensor in enumerate(sensors):
            if not isinstance(sensor, Mapping):
                continue
            dominance = 1.0
            if fault_kind != "none" and not diffuse_excitation:
                dominance = (
                    1.65 if sensor_index == 0 else (0.55 + (sensor_index * 0.12))
                )

            base_amp_g = max(1e-6, floor_amp_g * (1.2 + (sensor_index * 0.18)))
            fault_amp_g = max(1e-6, base_fault_amp_g * dominance)
            if fault_kind == "none":
                fault_amp_g = base_amp_g * 1.35

            if scenario == "idle":
                fault_amp_g *= 0.65

            vibration_strength_db = vibration_strength_db_scalar(
                peak_band_rms_amp_g=max(base_amp_g, fault_amp_g),
                floor_amp_g=floor_amp_g,
            )
            peaks = [
                build_peak(
                    hz=fault_hz or background_hz,
                    amp_g=max(base_amp_g, fault_amp_g),
                    vibration_strength_db_scalar=vibration_strength_db_scalar,
                    bucket_for_strength=bucket_for_strength,
                    floor_amp_g=floor_amp_g,
                ),
                build_peak(
                    hz=background_hz + (sensor_index * 3.0) + (step % 5),
                    amp_g=max(1e-6, base_amp_g * 0.85),
                    vibration_strength_db_scalar=vibration_strength_db_scalar,
                    bucket_for_strength=bucket_for_strength,
                    floor_amp_g=floor_amp_g,
                ),
                build_peak(
                    hz=clutter_hz + (sensor_index * 1.5),
                    amp_g=max(1e-6, base_amp_g * 0.45),
                    vibration_strength_db_scalar=vibration_strength_db_scalar,
                    bucket_for_strength=bucket_for_strength,
                    floor_amp_g=floor_amp_g,
                ),
            ]

            sample: dict[str, object] = {
                "run_id": str(metadata.get("run_id") or ""),
                "timestamp_utc": timestamp_at(timestamp_offset),
                "t_s": round(timestamp_offset, 3),
                "client_id": str(sensor.get("client_id") or ""),
                "client_name": str(sensor.get("client_name") or ""),
                "location": (
                    ""
                    if (sensor_index / max(1, len(sensors))) < blank_location_ratio
                    else str(sensor.get("location") or "")
                ),
                "sample_rate_hz": raw_sample_rate_hz,
                "speed_kmh": sampled_speed_kmh,
                "gps_speed_kmh": sampled_speed_kmh,
                "speed_source": "gps" if sampled_speed_kmh is not None else "none",
                "engine_rpm": (
                    round((sampled_speed_kmh or 0.0) * 35.0, 3)
                    if fault_kind == "engine" and sampled_speed_kmh is not None
                    else None
                ),
                "engine_rpm_source": (
                    "estimated_from_speed_and_ratios"
                    if fault_kind == "engine" and sampled_speed_kmh is not None
                    else "missing"
                ),
                "gear": float(metadata.get("current_gear_ratio") or 0.0) or None,
                "final_drive_ratio": float(metadata.get("final_drive_ratio") or 0.0)
                or None,
                "accel_x_g": round(base_amp_g * (0.8 + accel_scale), 6),
                "accel_y_g": round(base_amp_g * (0.6 + (accel_scale * 0.5)), 6),
                "accel_z_g": round(1.0 + base_amp_g * (0.4 + accel_scale), 6),
                "dominant_freq_hz": round(fault_hz or background_hz, 3),
                "dominant_axis": "combined",
                "top_peaks": peaks,
                "vibration_strength_db": round(vibration_strength_db, 3),
                "strength_bucket": bucket_for_strength(vibration_strength_db),
                "strength_peak_amp_g": round(max(base_amp_g, fault_amp_g), 6),
                "strength_floor_amp_g": round(floor_amp_g, 6),
                "frames_dropped_total": drop_counter + step,
                "queue_overflow_drops": overflow_counter + (step // 3),
            }
            samples.append(sample)
    return samples
