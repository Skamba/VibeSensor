from __future__ import annotations

from test_support.report_helpers import analysis_metadata as make_metadata
from test_support.report_helpers import analysis_sample_with_peaks as sample

from vibesensor.use_cases.diagnostics import summarize_run_data
from vibesensor.use_cases.diagnostics.findings import _build_persistent_peak_findings
from vibesensor.use_cases.diagnostics.phase_segmentation import DrivingPhase


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


def findings_at_freq(findings: tuple | list, *freq_strs: str) -> list:
    from vibesensor.domain.finding import Finding

    def _matches(finding: object) -> bool:
        if isinstance(finding, Finding):
            sources = [finding.order or ""]
            if finding.frequency_hz is not None:
                sources.append(str(finding.frequency_hz))
            return any(fs in s for s in sources for fs in freq_strs)
        return any(fs in str(finding.get("frequency_hz_or_order", "")) for fs in freq_strs)  # type: ignore[union-attr]

    return [f for f in findings if _matches(f)]


def summarize(samples: list[dict], **meta_overrides: object) -> dict:
    return summarize_run_data(make_metadata(**meta_overrides), samples, lang="en")
