"""Opt-in weird-sensor-mix diagnostic matrix.

Ambiguity-aware localization across non-standard topologies stays available
outside default backend CI; the core matrix keeps default wheel/no-fault risks.
"""

from __future__ import annotations

import pytest
from test_support.analysis import extract_top, run_analysis
from test_support.assertions import (
    assert_confidence_between,
    assert_has_warnings,
    assert_max_wheel_confidence,
    assert_no_exact_corner_claim,
    assert_wheel_weak_spatial,
)
from test_support.core import (
    assert_summary_sections,
    profile_metadata,
)
from test_support.diagnostic_matrix_catalogs import (
    WEIRD_ASYMMETRIC_COMBOS as _ASYMMETRIC_COMBOS,
)
from test_support.diagnostic_matrix_catalogs import (
    WEIRD_CABIN_SENSOR_MIXES as _CABIN_SENSOR_MIXES,
)
from test_support.diagnostic_matrix_catalogs import (
    WEIRD_CABIN_WHEEL_COMBOS as _CABIN_COMBOS_FOR_WHEEL,
)
from test_support.diagnostic_matrix_catalogs import (
    WEIRD_CONTRADICTORY_MIXES as _CONTRA_MIXES,
)
from test_support.diagnostic_matrix_catalogs import (
    WEIRD_GRANULARITY_SCENARIOS as _GRANULARITY_SCENARIOS,
)
from test_support.diagnostic_matrix_catalogs import (
    WEIRD_HIGH_TRANSFER_CASES as _HIGH_TRANSFERS,
)
from test_support.diagnostic_matrix_catalogs import (
    WEIRD_NOISE_LEVEL_CASES as _NOISE_LEVELS,
)
from test_support.diagnostic_matrix_catalogs import (
    WEIRD_PHASED_SCENARIOS as _PHASED_SCENARIOS,
)
from test_support.diagnostic_matrix_catalogs import (
    WEIRD_RESOLVE_COMBOS as _RESOLVE_COMBOS,
)
from test_support.diagnostic_matrix_catalogs import (
    WEIRD_SPARSE_SENSOR_CASES as _SPARSE_SENSORS,
)
from test_support.diagnostic_matrix_catalogs import (
    WEIRD_SPARSE_SPEED_IDS as _SPARSE_SPEED_IDS,
)
from test_support.diagnostic_matrix_catalogs import (
    WEIRD_SPARSE_SPEEDS as _SPARSE_SPEEDS,
)
from test_support.diagnostic_matrix_catalogs import (
    WEIRD_SPEED_IDS as _SPEED_IDS,
)
from test_support.diagnostic_matrix_catalogs import (
    WEIRD_SPEEDS as _SPEEDS,
)
from test_support.diagnostic_matrix_catalogs import (
    WEIRD_STRONG_AMPLITUDE_CASES as _STRONG_AMPS,
)
from test_support.diagnostic_matrix_catalogs import (
    WEIRD_TOPOLOGY_PROFILE_IDS as _TOPOLOGY_PROFILE_IDS,
)
from test_support.diagnostic_matrix_catalogs import (
    WEIRD_TOPOLOGY_PROFILES as _TOPOLOGY_PROFILES,
)
from test_support.diagnostic_matrix_catalogs import (
    WEIRD_WEAK_AMPLITUDE_CASES as _WEAK_AMPS,
)
from test_support.diagnostic_matrix_catalogs import (
    WEIRD_WHEEL_CORNER_CASES as _WHEEL_CORNERS,
)
from test_support.fault_scenarios import make_fault_samples
from test_support.sample_scenarios import make_diffuse_samples, make_noise_samples

pytestmark = pytest.mark.diagnostic_matrix

# ===================================================================
# 1. test_cabin_only_no_exact_corner — 45 cases
#    (5 mixes × 3 speeds × 3 profiles)
# ===================================================================


@pytest.mark.parametrize(
    ("mix_id", "sensors"),
    _CABIN_SENSOR_MIXES,
    ids=[m[0] for m in _CABIN_SENSOR_MIXES],
)
@pytest.mark.parametrize("speed", _SPEEDS, ids=_SPEED_IDS)
@pytest.mark.parametrize("profile", _TOPOLOGY_PROFILES, ids=_TOPOLOGY_PROFILE_IDS)
def test_cabin_only_no_exact_corner(
    mix_id: str,
    sensors: list[str],
    speed: float,
    profile: dict[str, float | str],
) -> None:
    """Cabin-only sensors should not claim an exact wheel corner."""
    samples = make_fault_samples(
        fault_sensor=sensors[0],
        sensors=sensors,
        speed_kmh=speed,
        n_samples=30,
        fault_amp=0.06,
        fault_vib_db=26.0,
        transfer_fraction=0.3,
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    tag = f"{mix_id}@{speed}/{profile['name']}"
    assert_summary_sections(summary)
    assert_no_exact_corner_claim(summary, confidence_threshold=0.25, msg=tag)
    assert_wheel_weak_spatial(summary, msg=tag)
    assert_has_warnings(summary, msg=tag)


# ===================================================================
# 2. test_cabin_only_weak_evidence — 10 cases (5 mixes × 2 amps)
# ===================================================================


@pytest.mark.parametrize(
    ("mix_id", "sensors"),
    _CABIN_SENSOR_MIXES,
    ids=[m[0] for m in _CABIN_SENSOR_MIXES],
)
@pytest.mark.parametrize(
    ("amp_id", "fault_amp", "fault_vib_db"),
    _WEAK_AMPS,
    ids=[a[0] for a in _WEAK_AMPS],
)
def test_cabin_only_weak_evidence(
    mix_id: str,
    sensors: list[str],
    amp_id: str,
    fault_amp: float,
    fault_vib_db: float,
) -> None:
    """Weak cabin-only evidence should yield bounded wheel confidence."""
    samples = make_fault_samples(
        fault_sensor=sensors[0],
        sensors=sensors,
        speed_kmh=80.0,
        n_samples=30,
        fault_amp=fault_amp,
        fault_vib_db=fault_vib_db,
        transfer_fraction=0.2,
    )
    summary = run_analysis(samples)
    tag = f"{mix_id}/{amp_id}"
    assert_summary_sections(summary)
    assert_no_exact_corner_claim(summary, confidence_threshold=0.25, msg=tag)
    assert_max_wheel_confidence(summary, 0.45, msg=tag)


# ===================================================================
# 3. test_one_wheel_plus_cabin_correct_localization — 12 cases
#    (4 corners × 3 cabin combos)
# ===================================================================


@pytest.mark.parametrize(
    ("corner_id", "wheel_sensor"),
    _WHEEL_CORNERS,
    ids=[c[0] for c in _WHEEL_CORNERS],
)
@pytest.mark.parametrize(
    ("cabin_id", "cabin_sensors"),
    _CABIN_COMBOS_FOR_WHEEL,
    ids=[c[0] for c in _CABIN_COMBOS_FOR_WHEEL],
)
def test_one_wheel_plus_cabin_correct_localization(
    corner_id: str,
    wheel_sensor: str,
    cabin_id: str,
    cabin_sensors: list[str],
) -> None:
    """One wheel sensor + cabin should produce reasonable confidence."""
    all_sensors = [wheel_sensor] + cabin_sensors
    samples = make_fault_samples(
        fault_sensor=wheel_sensor,
        sensors=all_sensors,
        speed_kmh=80.0,
        n_samples=30,
        fault_amp=0.06,
        fault_vib_db=26.0,
        transfer_fraction=0.3,
    )
    summary = run_analysis(samples)
    tag = f"{corner_id}+{cabin_id}"
    assert_summary_sections(summary, min_findings=1, min_top_causes=1)
    assert_confidence_between(summary, 0.15, 1.0, msg=tag)
    top = extract_top(summary)
    assert top is not None, f"Expected a top cause for {tag}"
    assert str(top.get("strongest_location") or "").lower() == wheel_sensor.lower()


# ===================================================================
# 4. test_cabin_high_transfer_ambiguous — 10 cases
#    (5 mixes × 2 transfer fractions)
# ===================================================================


@pytest.mark.parametrize(
    ("mix_id", "sensors"),
    _CABIN_SENSOR_MIXES,
    ids=[m[0] for m in _CABIN_SENSOR_MIXES],
)
@pytest.mark.parametrize(
    ("tf_id", "transfer_fraction"),
    _HIGH_TRANSFERS,
    ids=[t[0] for t in _HIGH_TRANSFERS],
)
def test_cabin_high_transfer_ambiguous(
    mix_id: str,
    sensors: list[str],
    tf_id: str,
    transfer_fraction: float,
) -> None:
    """Near-equal transfer across cabin sensors should remain ambiguous."""
    samples = make_fault_samples(
        fault_sensor=sensors[0],
        sensors=sensors,
        speed_kmh=80.0,
        n_samples=30,
        fault_amp=0.05,
        fault_vib_db=22.0,
        transfer_fraction=transfer_fraction,
    )
    summary = run_analysis(samples)
    tag = f"{mix_id}/{tf_id}"
    assert_summary_sections(summary)
    assert_no_exact_corner_claim(summary, confidence_threshold=0.25, msg=tag)
    assert_max_wheel_confidence(summary, 0.50, msg=tag)


# ===================================================================
# 5. test_asymmetric_cabin_front_vs_rear — 12 cases
#    (4 combos × 3 speeds)
# ===================================================================


@pytest.mark.parametrize(
    ("combo_id", "sensors"),
    _ASYMMETRIC_COMBOS,
    ids=[c[0] for c in _ASYMMETRIC_COMBOS],
)
@pytest.mark.parametrize("speed", _SPEEDS, ids=_SPEED_IDS)
def test_asymmetric_cabin_front_vs_rear(combo_id: str, sensors: list[str], speed: float) -> None:
    """Asymmetric front/rear cabin mixes should not pinpoint a corner."""
    samples = make_fault_samples(
        fault_sensor=sensors[0],
        sensors=sensors,
        speed_kmh=speed,
        n_samples=30,
        fault_amp=0.06,
        fault_vib_db=26.0,
        transfer_fraction=0.2,
    )
    summary = run_analysis(samples)
    tag = f"{combo_id}@{speed}"
    assert_summary_sections(summary)
    assert_no_exact_corner_claim(summary, confidence_threshold=0.25, msg=tag)


# ===================================================================
# 6. test_sparse_single_non_wheel — 36 cases
#    (6 sensors × 2 speeds × 3 profiles)
# ===================================================================


@pytest.mark.parametrize(
    ("sensor_id", "sensor"),
    _SPARSE_SENSORS,
    ids=[s[0] for s in _SPARSE_SENSORS],
)
@pytest.mark.parametrize("speed", _SPARSE_SPEEDS, ids=_SPARSE_SPEED_IDS)
@pytest.mark.parametrize("profile", _TOPOLOGY_PROFILES, ids=_TOPOLOGY_PROFILE_IDS)
def test_sparse_single_non_wheel(
    sensor_id: str,
    sensor: str,
    speed: float,
    profile: dict[str, float | str],
) -> None:
    """A single non-wheel sensor should not claim an exact corner."""
    samples = make_fault_samples(
        fault_sensor=sensor,
        sensors=[sensor],
        speed_kmh=speed,
        n_samples=30,
        fault_amp=0.06,
        fault_vib_db=26.0,
        transfer_fraction=0.0,
    )
    summary = run_analysis(samples, metadata=profile_metadata(profile))
    tag = f"{sensor_id}@{speed}/{profile['name']}"
    assert_summary_sections(summary)
    assert_no_exact_corner_claim(summary, confidence_threshold=0.25, msg=tag)


# ===================================================================
# 7. test_phased_fault_cabin_only — 7 cases
# ===================================================================


@pytest.mark.parametrize(
    ("scenario_id", "sensors", "speed"),
    _PHASED_SCENARIOS,
    ids=[s[0] for s in _PHASED_SCENARIOS],
)
def test_phased_fault_cabin_only(scenario_id: str, sensors: list[str], speed: float) -> None:
    """Phased runs (noise then fault) should not claim exact corner."""
    noise_phase = make_noise_samples(
        sensors=sensors,
        speed_kmh=speed,
        n_samples=15,
        start_t_s=0.0,
    )
    fault_phase = make_fault_samples(
        fault_sensor=sensors[0],
        sensors=sensors,
        speed_kmh=speed,
        n_samples=15,
        start_t_s=15.0,
        fault_amp=0.06,
        fault_vib_db=26.0,
        transfer_fraction=0.3 if len(sensors) > 1 else 0.0,
    )
    summary = run_analysis(noise_phase + fault_phase)
    assert_summary_sections(summary)
    assert_no_exact_corner_claim(summary, confidence_threshold=0.30, msg=scenario_id)


# ===================================================================
# 8. test_contradictory_noisy_mixes — 10 cases
#    (5 scenarios × 2 noise levels)
# ===================================================================


@pytest.mark.parametrize(
    ("mix_id", "sensors"),
    _CONTRA_MIXES,
    ids=[m[0] for m in _CONTRA_MIXES],
)
@pytest.mark.parametrize(
    ("noise_id", "noise_amp", "noise_db"),
    _NOISE_LEVELS,
    ids=[n[0] for n in _NOISE_LEVELS],
)
def test_contradictory_noisy_mixes(
    mix_id: str,
    sensors: list[str],
    noise_id: str,
    noise_amp: float,
    noise_db: float,
) -> None:
    """Diffuse noise overlaid on fault should not yield exact corner claim."""
    fault_samples = make_fault_samples(
        fault_sensor=sensors[0],
        sensors=sensors,
        speed_kmh=80.0,
        n_samples=20,
        fault_amp=0.05,
        fault_vib_db=22.0,
        transfer_fraction=0.3 if len(sensors) > 1 else 0.0,
    )
    diffuse = make_diffuse_samples(
        sensors=sensors,
        speed_kmh=80.0,
        n_samples=20,
        start_t_s=20.0,
        amp=noise_amp,
        vib_db=noise_db,
    )
    summary = run_analysis(fault_samples + diffuse)
    tag = f"{mix_id}/{noise_id}"
    assert_summary_sections(summary)
    assert_no_exact_corner_claim(summary, confidence_threshold=0.30, msg=tag)


# ===================================================================
# 9. test_stronger_evidence_resolves_system — 10 cases
#    (5 amplitude levels × 2 sensor combos)
# ===================================================================


@pytest.mark.parametrize(
    ("amp_id", "fault_amp", "fault_vib_db"),
    _STRONG_AMPS,
    ids=[a[0] for a in _STRONG_AMPS],
)
@pytest.mark.parametrize(
    ("combo_id", "sensors"),
    _RESOLVE_COMBOS,
    ids=[c[0] for c in _RESOLVE_COMBOS],
)
def test_stronger_evidence_resolves_system(
    amp_id: str,
    fault_amp: float,
    fault_vib_db: float,
    combo_id: str,
    sensors: list[str],
) -> None:
    """Stronger cabin fault evidence should still not claim exact corner."""
    samples = make_fault_samples(
        fault_sensor=sensors[0],
        sensors=sensors,
        speed_kmh=80.0,
        n_samples=30,
        fault_amp=fault_amp,
        fault_vib_db=fault_vib_db,
        transfer_fraction=0.3,
    )
    summary = run_analysis(samples)
    tag = f"{amp_id}/{combo_id}"
    assert_summary_sections(summary)
    assert_no_exact_corner_claim(summary, confidence_threshold=0.25, msg=tag)


# ===================================================================
# 10. test_report_granularity_consistency — 2 cases
# ===================================================================


@pytest.mark.parametrize(
    ("scenario_id", "sensors", "speed"),
    _GRANULARITY_SCENARIOS,
    ids=[s[0] for s in _GRANULARITY_SCENARIOS],
)
def test_report_granularity_consistency(scenario_id: str, sensors: list[str], speed: float) -> None:
    """Findings and top_causes should agree on weak_spatial_separation."""
    samples = make_fault_samples(
        fault_sensor=sensors[0],
        sensors=sensors,
        speed_kmh=speed,
        n_samples=30,
        fault_amp=0.06,
        fault_vib_db=26.0,
        transfer_fraction=0.3,
    )
    summary = run_analysis(samples)
    assert_summary_sections(summary)

    # Collect weak-spatial flags from findings
    findings = summary.get("findings") or []
    wheel_findings_weak = [
        f.get("weak_spatial_separation", False)
        for f in findings
        if "wheel" in str(f.get("suspected_source", "")).lower()
        and not str(f.get("finding_id", "")).startswith("REF_")
    ]

    # Collect from top_causes
    causes = summary.get("top_causes") or []
    wheel_causes_weak = [
        c.get("weak_spatial_separation", False)
        for c in causes
        if "wheel" in str(c.get("suspected_source", "")).lower()
    ]

    # Both should be consistent: if findings say weak, causes should too
    if wheel_findings_weak and wheel_causes_weak:
        assert all(wheel_findings_weak) == all(wheel_causes_weak), (
            f"Findings weak_spatial={wheel_findings_weak} vs "
            f"causes weak_spatial={wheel_causes_weak} for {scenario_id}"
        )
