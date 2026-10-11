"""Reference-resolution helpers for diagnostics order analysis."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt

from vibesensor.common.units import KMH_TO_MPS, SECONDS_PER_MINUTE
from vibesensor.recording.run_schema import RunMetadata
from vibesensor.recording.sample_columns import first_seen

if TYPE_CHECKING:
    from vibesensor.analysis.drive_table import DriveTable

# Engine RPM derived from vehicle speed, tire size and gear ratios: it moves in
# lockstep with the wheels, so it cannot tell an engine order from a wheel order.
ESTIMATED_RPM_SOURCE = "estimated_from_speed_and_ratios"
ENGINE_OFF_RPM_SOURCE = "engine_off"
_NOT_MEASURED_RPM_SOURCES = frozenset({"", ESTIMATED_RPM_SOURCE, "missing", "context_unaligned"})


def _tire_reference_from_context(context: RunMetadata) -> tuple[float | None, str | None]:
    """Return the wheel reference circumference and the metadata source name."""
    spec = context.order_reference_spec
    if spec is not None and spec.supports_wheel_reference:
        return spec.tire_circumference_m, "order_reference_spec"

    direct = context.tire_circumference_m
    if direct is not None and direct > 0:
        return direct, "diagnostics_context.tire_circumference_m"
    return None, None


@dataclass(frozen=True, slots=True)
class EngineRpm:
    """Each sample's engine RPM as the order analysis resolves it (``effective_engine_rpm``).

    Its RPM (NaN where there is none), whether it has one, and its source (an
    index into *sources*, which come in the order the samples first give them).
    """

    rpm: npt.NDArray[np.float64]
    known: npt.NDArray[np.bool_]
    source_of: npt.NDArray[np.intp]
    sources: Sequence[str]


def effective_engine_rpm(
    table: DriveTable,
    context: RunMetadata,
    tire_circumference_m: float | None,
) -> EngineRpm:
    """Each sample's measured or inferred engine RPM, and where it came from.

    A measured RPM over 0 is taken as it is. A plug-in hybrid's measured 0 rpm
    is the engine off while it drives electrically: no engine order to
    estimate from speed. A combustion engine does not stop while the car
    moves, so there 0 rpm is a bad reading (an OBD glitch, ignition-off data)
    and the RPM is estimated as when none was measured: from the speed through
    the car's order reference at the sample's own ratios, else through the tire
    circumference and the sample's or the run's final-drive and gear ratios.
    """
    speed, has_speed = table.speed_kmh, table.has_speed
    measured_sources = table.engine_rpm_sources
    names = [source or "measured" for source in measured_sources]
    engine_off, estimated, missing = (len(names) + offset for offset in range(3))
    names += [ENGINE_OFF_RPM_SOURCE, ESTIMATED_RPM_SOURCE, "missing"]
    rpm = np.full(table.size, np.nan)
    source = np.full(table.size, missing, dtype=np.intp)

    measured = table.has_engine_rpm & (table.engine_rpm > 0)
    rpm[measured] = table.engine_rpm[measured]
    source[measured] = table.engine_rpm_source_of[measured]
    known = measured.copy()
    if context.fuel_type == "PHEV":
        not_measured = np.array(
            [name in _NOT_MEASURED_RPM_SOURCES for name in measured_sources], dtype=np.bool_
        )
        off = ~measured & table.has_engine_rpm & ~not_measured[table.engine_rpm_source_of]
        source[off] = engine_off
        rest = ~measured & ~off
    else:
        rest = ~measured

    spec = context.order_reference_spec
    if spec is not None:
        # The car's order reference at each sample's own ratios (``order_reference_spec_for``).
        final_drive = np.where(
            table.has_final_drive_ratio, table.final_drive_ratio, spec.final_drive_ratio
        )
        gear = np.where(table.has_gear, table.gear, spec.current_gear_ratio)
        circumference_m = spec.tire_circumference_m
        supports_engine = (circumference_m > 0.0) & (final_drive > 0.0) & (gear != 0.0)
        wheel_hz = wheel_hz_columns(speed, circumference_m)
        with np.errstate(all="ignore"):
            driveshaft_hz = wheel_hz * final_drive
            engine_hz = driveshaft_hz * gear
            from_spec = engine_hz * 60.0
        placed = (
            rest
            & has_speed
            & (speed > 0)
            & supports_engine
            & ~np.isnan(wheel_hz)
            & np.isfinite(driveshaft_hz)
            & np.isfinite(engine_hz)
            & np.isfinite(from_spec)
            & (from_spec > 0)
        )
        rpm[placed] = from_spec[placed]
        source[placed] = estimated
        known |= placed
        rest &= ~placed

    if tire_circumference_m is not None and not tire_circumference_m <= 0:
        context_drive = context.final_drive_ratio
        context_gear = context.current_gear_ratio
        drive_ratio = np.where(
            table.has_final_drive_ratio,
            table.final_drive_ratio,
            context_drive if context_drive is not None else np.nan,
        )
        gear_ratio = np.where(
            table.has_gear, table.gear, context_gear if context_gear is not None else np.nan
        )
        wheel_hz = wheel_hz_columns(speed, tire_circumference_m)
        with np.errstate(all="ignore"):
            from_ratios = wheel_hz * drive_ratio * gear_ratio * SECONDS_PER_MINUTE
        placed = (
            rest
            & has_speed
            & ~(speed <= 0)
            & (table.has_final_drive_ratio | (context_drive is not None))
            & ~(drive_ratio <= 0)
            & (table.has_gear | (context_gear is not None))
            & ~(gear_ratio <= 0)
            & ~np.isnan(wheel_hz)
        )
        rpm[placed] = from_ratios[placed]
        source[placed] = estimated
        known |= placed

    # One code per source name, numbered in the order the samples first give them.
    same_name: dict[str, int] = {}
    canonical = np.array(
        [same_name.setdefault(name, index) for index, name in enumerate(names)], dtype=np.intp
    )
    source_of, sources = first_seen(canonical[source], names)
    return EngineRpm(rpm=rpm, known=known, source_of=source_of, sources=sources)


def wheel_hz_columns(
    speed_kmh: npt.NDArray[np.float64], tire_circumference_m: float | npt.NDArray[np.float64]
) -> npt.NDArray[np.float64]:
    """``wheel_hz_from_speed_kmh`` of each speed: the same values, NaN where it gives ``None``."""
    with np.errstate(all="ignore"):
        speed_mps = speed_kmh * KMH_TO_MPS
        wheel_hz = speed_mps / tire_circumference_m
    placed = (
        np.isfinite(speed_kmh)
        & (speed_kmh > 0)
        & np.isfinite(speed_mps)
        & (speed_mps > 0)
        & np.isfinite(tire_circumference_m)
        & (np.asarray(tire_circumference_m) > 0)
        & np.isfinite(wheel_hz)
    )
    return np.where(placed, wheel_hz, np.nan)
