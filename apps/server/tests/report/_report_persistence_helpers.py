from __future__ import annotations

from _report_helpers import analysis_metadata as make_metadata
from _report_helpers import analysis_sample_with_peaks as sample

from vibesensor.analysis import summarize_run_data
from vibesensor.analysis.findings.persistent_findings import _build_persistent_peak_findings
from vibesensor.analysis.phase_segmentation import DrivingPhase


def uniform_samples(
    n: int,
    freq: float,
    amp: float,
    *,
    speed: float = 80.0,
    dt: float = 0.5,
    **kwargs: object,
) -> list[dict]:
    return [sample(float(i) * dt, speed, [{"hz": freq, "amp": amp}], **kwargs) for i in range(n)]


def build_findings(
    samples: list[dict],
    *,
    order_finding_freqs: set[float] | None = None,
    per_sample_phases: list[DrivingPhase] | None = None,
) -> list[dict]:
    return _build_persistent_peak_findings(
        samples=samples,
        order_finding_freqs=order_finding_freqs or set(),
        lang="en",
        per_sample_phases=per_sample_phases,
    )


def findings_at_freq(findings: list[dict], *freq_strs: str) -> list[dict]:
    return [
        finding
        for finding in findings
        if any(freq_str in str(finding.get("frequency_hz_or_order", "")) for freq_str in freq_strs)
    ]


def summarize(samples: list[dict], **meta_overrides: object) -> dict:
    return summarize_run_data(make_metadata(**meta_overrides), samples, lang="en")
