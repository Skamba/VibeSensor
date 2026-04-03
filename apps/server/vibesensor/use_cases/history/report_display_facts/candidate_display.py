"""Candidate ranking and path-description builders for report display facts."""

from __future__ import annotations

from collections.abc import Callable

from vibesensor.domain import Finding, TestRun
from vibesensor.report_i18n import human_source
from vibesensor.shared.report_presentation import (
    candidate_signal_text,
    confidence_pct_text,
    display_location,
    uses_shared_overlap_wording,
)

from .models import PreparedRankedCandidateDisplay

__all__ = [
    "build_ranked_candidates",
    "next_if_primary_clean",
]


def build_ranked_candidates(
    aggregate: TestRun,
    *,
    tr: Callable[..., str],
) -> tuple[PreparedRankedCandidateDisplay, ...]:
    candidates = list(aggregate.effective_top_causes()[:3])
    rows: list[PreparedRankedCandidateDisplay] = []
    primary_finding = candidates[0] if candidates else None
    for index, finding in enumerate(candidates):
        use_shared_overlap_wording = (
            index > 0
            and primary_finding is not None
            and uses_shared_overlap_wording(primary_finding, finding, tr=tr)
        )
        rows.append(
            PreparedRankedCandidateDisplay(
                source_name=human_source(finding.suspected_source, tr=tr),
                confidence_pct=confidence_pct_text(finding),
                inspect_first=display_location(finding.strongest_location, tr=tr),
                path_role=f"{index + 1}. {_path_role_text(index, tr=tr)}",
                reason=_candidate_reason_text(
                    finding,
                    tr=tr,
                    use_shared_overlap_wording=use_shared_overlap_wording,
                ),
            ),
        )
    return tuple(rows)


def next_if_primary_clean(
    aggregate: TestRun,
    *,
    tr: Callable[..., str],
) -> str | None:
    candidates = list(aggregate.effective_top_causes()[:2])
    if len(candidates) < 2:
        return None
    alternative = candidates[1]
    use_shared_overlap_wording = uses_shared_overlap_wording(candidates[0], alternative, tr=tr)
    return _candidate_reason_text(
        alternative,
        tr=tr,
        use_shared_overlap_wording=use_shared_overlap_wording,
    )


def _candidate_reason_text(
    finding: Finding,
    *,
    tr: Callable[..., str],
    use_shared_overlap_wording: bool = False,
) -> str:
    speed_window = (
        str(
            finding.evidence.focused_speed_band
            if finding.evidence and finding.evidence.focused_speed_band
            else ""
        ).strip()
        or str(finding.strongest_speed_band or "").strip()
    )
    location = display_location(finding.strongest_location, tr=tr)
    signal = candidate_signal_text(finding, tr=tr)
    if use_shared_overlap_wording:
        return tr(
            "REPORT_CANDIDATE_REASON_OVERLAP",
            signal=signal,
            speed=speed_window or tr("UNKNOWN"),
        )
    if finding.weak_spatial_separation:
        return tr(
            "REPORT_CANDIDATE_REASON_WEAK",
            signal=signal,
            speed=speed_window or tr("UNKNOWN"),
        )
    return tr(
        "REPORT_CANDIDATE_REASON_STRONG",
        signal=signal,
        location=location,
        speed=speed_window or tr("UNKNOWN"),
    )


def _path_role_text(index: int, *, tr: Callable[..., str]) -> str:
    if index == 0:
        return tr("REPORT_PATH_ROLE_PRIMARY")
    if index == 1:
        return tr("REPORT_PATH_ROLE_ALTERNATIVE")
    return tr("REPORT_PATH_ROLE_LOW_CONFIDENCE")
