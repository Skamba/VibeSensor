from __future__ import annotations

import pytest

from vibesensor.domain import FindingKind, VibrationSource
from vibesensor.use_cases.diagnostics.post_run_dense_findings import (
    classify_post_run_dense_findings,
    dense_finding_debug_rows,
)
from vibesensor.use_cases.diagnostics.post_run_order_bands import (
    OrderBand,
    OrderBandSource,
    OrderBandUnavailableReason,
    OrderBandWindow,
    PostRunOrderBandsConfig,
    PostRunOrderBandTimeline,
)
from vibesensor.use_cases.diagnostics.post_run_vibration_episodes import (
    VibrationEpisode,
)

_RUN_ID = "run-dense-findings"


def _episode(
    *,
    episode_id: str = "episode-1",
    frequency_hz: float = 10.0,
    windows: tuple[int, ...] = (0, 1, 2, 3),
    strength_db: float = 24.0,
    quality_penalty: float = 0.0,
    transient: bool = False,
    affected_sensors: tuple[str, ...] = ("sensor-a",),
) -> VibrationEpisode:
    return VibrationEpisode(
        episode_id=episode_id,
        run_id=_RUN_ID,
        client_id="sensor-a",
        location="front_left",
        start_t_s=float(windows[0]) * 0.5,
        end_t_s=(float(windows[-1]) * 0.5) + 0.5,
        duration_s=((float(windows[-1]) - float(windows[0])) * 0.5) + 0.5,
        start_window_index=windows[0],
        end_window_index=windows[-1],
        supporting_window_ids=windows,
        frequency_path_hz=tuple(frequency_hz for _ in windows),
        median_frequency_hz=frequency_hz,
        peak_frequency_hz=frequency_hz,
        frequency_slope_hz_per_s=0.0,
        median_strength_db=strength_db,
        peak_strength_db=strength_db,
        peak_count=len(windows),
        axis_dominance="x",
        affected_sensors=affected_sensors,
        quality_penalties=("quality_flags_present",) if quality_penalty else (),
        quality_penalty=quality_penalty,
        transient=transient,
    )


def _band(
    label: str,
    source: OrderBandSource,
    center_hz: float,
    *,
    half_width_hz: float = 0.4,
    unavailable: OrderBandUnavailableReason | None = None,
) -> OrderBand:
    return OrderBand(
        label=label,
        source=source,
        harmonic=1,
        center_hz=center_hz,
        min_hz=center_hz - half_width_hz if unavailable is None else None,
        max_hz=center_hz + half_width_hz if unavailable is None else None,
        uncertainty_pct=0.02 if unavailable is None else None,
        tolerance=0.04 if unavailable is None else None,
        unavailable_reason=unavailable,
        reference_source="test",
    )


def _timeline(
    *,
    windows: tuple[int, ...] = (0, 1, 2, 3),
    wheel_hz: float = 10.0,
    driveshaft_hz: float = 30.0,
    engine_hz: float = 50.0,
    unavailable_source: str | None = None,
) -> PostRunOrderBandTimeline:
    band_windows = []
    for window_index in windows:
        bands = (
            _band(
                "wheel_1x",
                "wheel",
                wheel_hz,
                unavailable="missing_speed" if unavailable_source == "wheel" else None,
            ),
            _band(
                "driveshaft_1x",
                "driveshaft",
                driveshaft_hz,
                unavailable=("unknown_final_drive" if unavailable_source == "driveshaft" else None),
            ),
            _band(
                "engine_1x",
                "engine",
                engine_hz,
                unavailable="missing_rpm" if unavailable_source == "engine" else None,
            ),
        )
        band_windows.append(
            OrderBandWindow(
                run_id=_RUN_ID,
                window_index=window_index,
                window_start_t_s=float(window_index) * 0.5,
                window_end_t_s=(float(window_index) * 0.5) + 0.5,
                window_center_t_s=(float(window_index) * 0.5) + 0.25,
                bands=bands,
            )
        )
    return PostRunOrderBandTimeline(
        run_id=_RUN_ID,
        config=PostRunOrderBandsConfig(),
        windows=tuple(band_windows),
    )


def test_dense_findings_classify_clear_wheel_episode() -> None:
    findings = classify_post_run_dense_findings((_episode(frequency_hz=10.0),), _timeline())

    assert len(findings) == 1
    finding = findings[0]
    assert finding.likely_origin is VibrationSource.WHEEL_TIRE
    assert finding.confidence_label == "high"
    assert finding.confidence_score >= 0.7
    assert finding.alternatives[0].best_band_label == "wheel_1x"
    assert all(window.matched for window in finding.evidence_windows)


def test_dense_findings_classify_clear_driveshaft_episode() -> None:
    findings = classify_post_run_dense_findings((_episode(frequency_hz=30.0),), _timeline())

    assert findings[0].likely_origin is VibrationSource.DRIVELINE
    assert findings[0].alternatives[0].best_band_label == "driveshaft_1x"


def test_dense_findings_classify_clear_engine_episode() -> None:
    findings = classify_post_run_dense_findings((_episode(frequency_hz=50.0),), _timeline())

    assert findings[0].likely_origin is VibrationSource.ENGINE
    assert findings[0].alternatives[0].best_band_label == "engine_1x"


def test_dense_findings_preserve_unknown_for_unmatched_strong_episode() -> None:
    findings = classify_post_run_dense_findings(
        (_episode(frequency_hz=17.0, strength_db=26.0),),
        _timeline(),
    )

    assert findings[0].likely_origin is VibrationSource.UNKNOWN_RESONANCE
    assert "unmatched_strong_episode" in findings[0].caveats
    assert not any(window.matched for window in findings[0].evidence_windows)


def test_dense_findings_mark_ambiguous_close_source_match() -> None:
    findings = classify_post_run_dense_findings(
        (_episode(frequency_hz=10.0),),
        _timeline(wheel_hz=10.0, driveshaft_hz=10.0, engine_hz=40.0),
    )

    assert findings[0].likely_origin in (VibrationSource.WHEEL_TIRE, VibrationSource.DRIVELINE)
    assert "ambiguous_origin" in findings[0].caveats
    assert len(findings[0].alternatives) == 3


def test_dense_findings_penalize_poor_quality_and_missing_references() -> None:
    episode = _episode(frequency_hz=10.0, quality_penalty=0.3)
    findings = classify_post_run_dense_findings(
        (episode,),
        _timeline(windows=(0, 1), wheel_hz=10.0),
    )

    finding = findings[0]
    assert finding.likely_origin is VibrationSource.WHEEL_TIRE
    assert "missing_reference_data" in finding.caveats
    assert "poor_quality" in finding.caveats
    assert finding.confidence_score < 0.7


def test_dense_findings_penalize_conflicting_sensor_evidence() -> None:
    episode = _episode(
        frequency_hz=10.0,
        affected_sensors=("sensor-a", "sensor-b", "sensor-c"),
    )

    finding = classify_post_run_dense_findings((episode,), _timeline())[0]

    assert finding.likely_origin is VibrationSource.WHEEL_TIRE
    assert "conflicting_sensor_evidence" in finding.caveats
    assert finding.confidence_score < 0.9


def test_dense_finding_maps_to_domain_finding() -> None:
    finding = classify_post_run_dense_findings((_episode(frequency_hz=10.0),), _timeline())[0]

    domain_finding = finding.to_domain_finding()

    assert domain_finding.kind is FindingKind.DIAGNOSTIC
    assert domain_finding.suspected_source is VibrationSource.WHEEL_TIRE
    assert domain_finding.confidence == pytest.approx(finding.confidence_score)
    assert domain_finding.frequency_hz == pytest.approx(finding.median_frequency_hz)


def test_dense_finding_debug_rows_are_stable() -> None:
    findings = classify_post_run_dense_findings((_episode(frequency_hz=10.0),), _timeline())

    rows = dense_finding_debug_rows(findings)

    assert rows[0]["likely_origin"] == "wheel/tire"
    assert rows[0]["evidence_window_count"] == 4
