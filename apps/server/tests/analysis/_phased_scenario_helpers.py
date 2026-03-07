from __future__ import annotations

from typing import Any

from builders import make_fault_samples as make_fault_samples
from builders import make_sample as make_sample
from builders import make_speed_sweep_fault_samples as make_speed_sweep_fault_samples
from builders import standard_metadata as standard_metadata
from builders import wheel_hz as wheel_hz

from vibesensor.analysis.findings.persistent_findings import _classify_peak_type
from vibesensor.analysis.summary import summarize_run_data


def build_fault_samples_at_speed(
    *,
    speed_kmh: float,
    fault_sensor: str,
    other_sensors: list[str],
    n_samples: int = 30,
    dt_s: float = 1.0,
    start_t_s: float = 0.0,
    fault_amp: float = 0.06,
    noise_amp: float = 0.004,
    fault_vib_db: float = 24.0,
    noise_vib_db: float = 8.0,
    add_wheel_2x: bool = True,
    transfer_fraction: float = 0.20,
) -> list[dict[str, Any]]:
    sensors = [fault_sensor, *other_sensors]
    return make_fault_samples(
        fault_sensor=fault_sensor,
        sensors=sensors,
        speed_kmh=speed_kmh,
        n_samples=n_samples,
        dt_s=dt_s,
        start_t_s=start_t_s,
        fault_amp=fault_amp,
        noise_amp=noise_amp,
        fault_vib_db=fault_vib_db,
        noise_vib_db=noise_vib_db,
        add_wheel_2x=add_wheel_2x,
        transfer_fraction=transfer_fraction,
    )


def build_speed_sweep_fault_samples(
    *,
    speed_start_kmh: float,
    speed_end_kmh: float,
    fault_sensor: str,
    other_sensors: list[str],
    n_samples: int = 40,
    dt_s: float = 1.0,
    start_t_s: float = 0.0,
    fault_amp: float = 0.06,
    noise_amp: float = 0.004,
    fault_vib_db: float = 24.0,
    noise_vib_db: float = 8.0,
    transfer_fraction: float = 0.20,
) -> list[dict[str, Any]]:
    sensors = [fault_sensor, *other_sensors]
    return make_speed_sweep_fault_samples(
        fault_sensor=fault_sensor,
        sensors=sensors,
        speed_start=speed_start_kmh,
        speed_end=speed_end_kmh,
        n_steps=n_samples,
        samples_per_step=1,
        dt_s=dt_s,
        start_t_s=start_t_s,
        fault_amp=fault_amp,
        noise_amp=noise_amp,
        fault_vib_db=fault_vib_db,
        noise_vib_db=noise_vib_db,
    )


def extract_top_finding(summary: dict[str, Any]) -> dict[str, Any] | None:
    findings = summary.get("findings", [])
    non_ref = [
        finding
        for finding in findings
        if isinstance(finding, dict) and not str(finding.get("finding_id", "")).startswith("REF_")
    ]
    if not non_ref:
        return None
    return max(non_ref, key=lambda finding: float(finding.get("confidence_0_to_1") or 0))


def assert_finding_location(summary: dict[str, Any], expected: str, label: str = "") -> dict[str, Any]:
    top = extract_top_finding(summary)
    assert top is not None, f"{label}: Should produce at least one diagnostic finding"
    location = str(top.get("strongest_location") or "").lower()
    assert expected in location, f"{label}: Expected '{expected}', got '{top.get('strongest_location')}'"
    return top


def assert_finding_source(
    summary: dict[str, Any],
    expected_sources: tuple[str, ...] = ("wheel", "tire"),
    label: str = "",
) -> dict[str, Any]:
    top = extract_top_finding(summary)
    assert top is not None, f"{label}: Should produce a finding"
    source = str(top.get("suspected_source") or "").lower()
    assert any(expected in source for expected in expected_sources), (
        f"{label}: Expected one of {expected_sources}, got '{top.get('suspected_source')}'"
    )
    return top


def parse_speed_band(finding: dict[str, Any]) -> tuple[float, float]:
    speed_band = str(finding.get("strongest_speed_band") or "")
    parts = speed_band.replace("km/h", "").strip().split("-")
    try:
        low = float(parts[0].strip())
        high = float(parts[-1].strip()) if len(parts) > 1 else low
    except (ValueError, IndexError):
        low = high = 0.0
    return low, high