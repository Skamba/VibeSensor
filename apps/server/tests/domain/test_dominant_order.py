"""The diagnosed order label follows the source's louder order, not the better-ranked one."""

from __future__ import annotations

from dataclasses import replace

import pytest
from test_support.findings import make_finding

from vibesensor.domain.finding import Finding
from vibesensor.domain.finding_types import VibrationSource
from vibesensor.domain.order_match import OrderMatchObservation
from vibesensor.domain.run_capture import RunCapture
from vibesensor.domain.test_run import TestRun

_SOURCE_KEYS = {
    VibrationSource.WHEEL_TIRE: "wheel",
    VibrationSource.DRIVELINE: "driveshaft",
    VibrationSource.ENGINE: "engine",
}


def _order(
    finding_id: str,
    source: VibrationSource,
    order: float,
    *,
    confidence: float,
    amps_g: dict[str, float],
    times: range = range(8),
    heard: bool = True,
) -> Finding:
    """An order finding matched at every time in *times* on each location in *amps_g*."""
    points = tuple(
        OrderMatchObservation(
            predicted_hz=12.0 * order,
            matched_hz=12.0 * order,
            rel_error=0.0,
            amp=amp,
            location=location,
            t_s=float(t_s),
            heard=heard,
        )
        for location, amp in amps_g.items()
        for t_s in times
    )
    return make_finding(
        finding_id=finding_id,
        finding_key=f"{_SOURCE_KEYS[source]}_{order:g}x".replace(".", "_"),
        suspected_source=source,
        confidence=confidence,
        strongest_location=max(amps_g, key=lambda location: amps_g[location]),
        matched_points=points,
    )


def _run(*findings: Finding) -> TestRun:
    return TestRun(capture=RunCapture(run_id="r"), findings=findings, top_causes=findings)


def test_level_over_db_compares_peaks_in_the_same_windows() -> None:
    first = _order("F1", VibrationSource.DRIVELINE, 1, confidence=0.5, amps_g={"RR": 0.15})
    second = _order("F2", VibrationSource.DRIVELINE, 2, confidence=0.5, amps_g={"RR": 0.05})
    assert second.level_over_db(first) == pytest.approx(-9.54, abs=0.01)
    assert first.level_over_db(second) == pytest.approx(9.54, abs=0.01)
    assert first.level_over_db(second, location="FL") is None


def test_level_over_db_ignores_windows_only_one_order_matched() -> None:
    # The 1st order also matched quiet road noise in other windows: unpaired, so it
    # does not pull the comparison down.
    loud = _order("F1", VibrationSource.DRIVELINE, 1, confidence=0.5, amps_g={"RR": 0.15})
    noise = _order(
        "F1", VibrationSource.DRIVELINE, 1, confidence=0.5, amps_g={"RR": 0.002}, times=range(8, 40)
    )
    first = replace(loud, matched_points=loud.matched_points + noise.matched_points)
    second = _order("F2", VibrationSource.DRIVELINE, 2, confidence=0.5, amps_g={"RR": 0.05})
    assert first.level_over_db(second) == pytest.approx(9.54, abs=0.01)
    few = _order(
        "F2", VibrationSource.DRIVELINE, 2, confidence=0.5, amps_g={"RR": 0.05}, times=range(3)
    )
    assert first.level_over_db(few) is None


def test_level_over_db_ignores_windows_neither_order_is_heard() -> None:
    # Two floor-level noise peaks say nothing about which order dominates.
    first = _order(
        "F1", VibrationSource.ENGINE, 1, confidence=0.3, amps_g={"RL": 0.004}, heard=False
    )
    noise = _order(
        "F2", VibrationSource.ENGINE, 3, confidence=0.9, amps_g={"RL": 0.003}, heard=False
    )
    assert noise.level_over_db(first) is None
    loud = _order("F2", VibrationSource.ENGINE, 3, confidence=0.9, amps_g={"RL": 0.2})
    assert loud.level_over_db(first) == pytest.approx(33.98, abs=0.01)


def test_louder_fundamental_names_the_diagnosis_over_a_better_ranked_harmonic() -> None:
    harmonic = _order("F001", VibrationSource.DRIVELINE, 2, confidence=0.52, amps_g={"RR": 0.05})
    fundamental = _order("F002", VibrationSource.DRIVELINE, 1, confidence=0.39, amps_g={"RR": 0.15})
    run = _run(harmonic, fundamental)
    assert run.diagnosis_candidate is harmonic
    assert run.diagnosis_order_finding is fundamental


def test_harmonic_clearly_louder_than_the_fundamental_keeps_its_label() -> None:
    # A 4-cylinder engine's 2nd order dominates its 1st.
    first = _order("F001", VibrationSource.ENGINE, 1, confidence=0.62, amps_g={"FL": 0.06})
    second = _order("F002", VibrationSource.ENGINE, 2, confidence=0.60, amps_g={"FL": 0.18})
    run = _run(first, second)
    assert run.diagnosis_order_finding is second


@pytest.mark.parametrize(("firing_g", "label"), [(0.06, "E1"), (0.17, "E1.5")])
def test_engine_firing_order_is_compared_with_e1(firing_g: float, label: str) -> None:
    # An inline-3 fires at E1.5. Both orders saturate their confidence, so E1 can
    # rank first on a coin toss; the louder firing order still names the diagnosis.
    first = _order("F001", VibrationSource.ENGINE, 1, confidence=0.97, amps_g={"FL": 0.06})
    firing = _order("F002", VibrationSource.ENGINE, 1.5, confidence=0.97, amps_g={"FL": firing_g})
    finding = _run(first, firing).diagnosis_order_finding
    assert finding is not None
    assert finding.order_code == label
    finding = _run(firing, first).diagnosis_order_finding
    assert finding is not None
    assert finding.order_code == label


@pytest.mark.parametrize(("harmonic_g", "label"), [(0.141, "T1"), (0.142, "T2")])
def test_harmonic_needs_three_db_over_the_fundamental(harmonic_g: float, label: str) -> None:
    second = _order(
        "F001", VibrationSource.WHEEL_TIRE, 2, confidence=0.8, amps_g={"FL": harmonic_g}
    )
    first = _order("F002", VibrationSource.WHEEL_TIRE, 1, confidence=0.7, amps_g={"FL": 0.1})
    finding = _run(second, first).diagnosis_order_finding
    assert finding is not None
    assert finding.order_code == label


def test_compares_at_the_diagnosed_corner_when_the_orders_share_windows_there() -> None:
    # At the diagnosed front-left corner the 2nd order is louder; elsewhere the
    # 1st order picked up louder road noise. The corner decides.
    second = _order(
        "F001", VibrationSource.WHEEL_TIRE, 2, confidence=0.8, amps_g={"FL": 0.2, "RR": 0.01}
    )
    first = _order(
        "F002",
        VibrationSource.WHEEL_TIRE,
        1,
        confidence=0.7,
        amps_g={"FL": 0.05, "RR": 0.1, "RL": 0.1, "FR": 0.1},
    )
    assert _run(second, first).diagnosis_order_finding is second


def test_candidate_stays_without_shared_windows_or_a_sibling_order() -> None:
    second = _order("F001", VibrationSource.DRIVELINE, 2, confidence=0.5, amps_g={"RR": 0.05})
    apart = _order(
        "F002",
        VibrationSource.DRIVELINE,
        1,
        confidence=0.45,
        amps_g={"RR": 0.15},
        times=range(20, 30),
    )
    assert _run(second, apart).diagnosis_order_finding is second
    other_source = _order("F003", VibrationSource.WHEEL_TIRE, 1, confidence=0.4, amps_g={"RR": 0.3})
    assert _run(second, other_source).diagnosis_order_finding is second
    faint = _order("F004", VibrationSource.DRIVELINE, 1, confidence=0.1, amps_g={"RR": 0.3})
    assert _run(second, faint).diagnosis_order_finding is second
