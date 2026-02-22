# ruff: noqa: E501
"""Analysis-contract test – direct-injection validation of the full pipeline.

This test exercises the full analysis pipeline end-to-end with a realistic
multi-sensor scenario including transient events.  It validates:
- Phase segmentation
- Finding generation
- Top-cause ranking
- Report fields (findings, speed breakdown, confidence, origin)
- Data quality assessment

NOTE: This is NOT a true integration/E2E test (it uses direct data injection,
not the simulator or server). It is an analysis-pipeline contract test.
For true simulator→ingestion→analysis E2E, see test_level_sim_ingestion.py.
"""

from __future__ import annotations

from typing import Any

from builders import (
    ALL_WHEEL_SENSORS,
    SENSOR_FL,
    SENSOR_FR,
    SENSOR_RR,
    make_fault_samples,
    make_idle_samples,
    make_ramp_samples,
    make_transient_samples,
    run_analysis,
    standard_metadata,
)


def _build_full_scenario() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build a complete multi-sensor scenario with transients.

    Timeline (120s total):
      0-10s:  idle (4 sensors)
     10-25s:  ramp 0→80 km/h (all sensors, road noise)
     25-70s:  cruise at 80 km/h with FL wheel fault
     45-47s:  transient spike on FR (impact event)
     70-85s:  deceleration 80→30 km/h (fault fading)
     85-100s: cruise at 30 km/h (FL fault at lower speed)
     95-97s:  transient spike on RR (second impact)
    100-120s: idle (cooling down)
    """
    sensors = ALL_WHEEL_SENSORS[:]
    samples: list[dict[str, Any]] = []

    # Phase 1: Idle (0-10s)
    samples.extend(make_idle_samples(sensors=sensors, n_samples=10, start_t_s=0))

    # Phase 2: Ramp up (10-25s) - no fault
    samples.extend(
        make_ramp_samples(
            sensors=sensors,
            speed_start=0,
            speed_end=80,
            n_samples=15,
            start_t_s=10,
            noise_amp=0.004,
            vib_db=10.0,
        )
    )

    # Phase 3: Cruise at 80 km/h with FL fault (25-70s)
    samples.extend(
        make_fault_samples(
            fault_sensor=SENSOR_FL,
            sensors=sensors,
            speed_kmh=80.0,
            n_samples=45,
            start_t_s=25,
            fault_amp=0.07,
            fault_vib_db=28.0,
            noise_vib_db=8.0,
        )
    )

    # Phase 3b: Transient on FR at 45-47s (mid-cruise)
    samples.extend(
        make_transient_samples(
            sensor=SENSOR_FR,
            speed_kmh=80.0,
            n_samples=3,
            start_t_s=45,
            spike_amp=0.20,
            spike_vib_db=38.0,
        )
    )

    # Phase 4: Deceleration (70-85s) - no fault peaks
    samples.extend(
        make_ramp_samples(
            sensors=sensors,
            speed_start=80,
            speed_end=30,
            n_samples=15,
            start_t_s=70,
            noise_amp=0.004,
            vib_db=10.0,
        )
    )

    # Phase 5: Low-speed cruise with FL fault (85-100s)
    samples.extend(
        make_fault_samples(
            fault_sensor=SENSOR_FL,
            sensors=sensors,
            speed_kmh=30.0,
            n_samples=15,
            start_t_s=85,
            fault_amp=0.05,
            fault_vib_db=22.0,
            noise_vib_db=8.0,
        )
    )

    # Phase 5b: Transient on RR at 95-97s
    samples.extend(
        make_transient_samples(
            sensor=SENSOR_RR,
            speed_kmh=30.0,
            n_samples=3,
            start_t_s=95,
            spike_amp=0.15,
            spike_vib_db=35.0,
        )
    )

    # Phase 6: Final idle (100-120s)
    samples.extend(make_idle_samples(sensors=sensors, n_samples=20, start_t_s=100))

    meta = standard_metadata(language="en")
    return meta, samples


def test_integration_full_scenario() -> None:
    """Full ingestion+analysis integration: multi-sensor + transient scenario."""
    meta, samples = _build_full_scenario()
    summary = run_analysis(samples, metadata=meta)

    # --- 1. Summary structure is complete ---
    assert isinstance(summary, dict)
    for key in (
        "top_causes",
        "findings",
        "speed_breakdown",
        "data_quality",
        "most_likely_origin",
    ):
        assert key in summary, f"Missing key '{key}' in summary"

    # --- 2. Top cause should involve wheel/tire ---
    causes = summary["top_causes"]
    assert isinstance(causes, list) and len(causes) > 0, "No top causes"
    top = causes[0]
    src = (top.get("source") or "").lower()
    assert "wheel" in src or "tire" in src, f"Expected wheel/tire source, got '{src}'"

    # --- 3. Confidence is reasonable ---
    conf = float(top.get("confidence", 0))
    assert 0.1 < conf <= 1.0, f"Confidence out of expected range: {conf}"

    # --- 4. Confidence label inside top cause ---
    assert top.get("confidence_label_key") in (
        "CONFIDENCE_HIGH",
        "CONFIDENCE_MEDIUM",
        "CONFIDENCE_LOW",
    ), f"Bad confidence label: {top.get('confidence_label_key')}"

    # --- 5. Speed breakdown is non-empty ---
    sb = summary["speed_breakdown"]
    assert len(sb) > 0, "Speed breakdown is empty"

    # --- 6. Findings include order findings ---
    findings = summary["findings"]
    assert len(findings) > 0, "No findings generated"
    has_order = any(
        "order" in str(f.get("type", "")).lower()
        or "wheel" in str(f.get("suspected_source", "")).lower()
        for f in findings
    )
    assert has_order, "Expected order findings"

    # --- 7. Data quality assessment ---
    dq = summary["data_quality"]
    assert isinstance(dq, dict)

    # --- 8. Most likely origin ---
    origin = summary["most_likely_origin"]
    assert isinstance(origin, dict)
    assert "source" in origin

    # --- 9. Phase timeline should exist ---
    pt = summary.get("phase_timeline")
    assert pt is not None, "Missing phase_timeline"
    assert isinstance(pt, list)

    # --- 10. Sensor intensity by location ---
    sil = summary.get("sensor_intensity_by_location")
    assert sil is not None, "Missing sensor_intensity_by_location"
    assert isinstance(sil, list) and len(sil) > 0
