"""Top-cause selection, ranking helpers, and confidence presentation.

Ranking helper ``group_findings_by_source`` was previously in a separate
``ranking`` module but merged here because this module is its primary
consumer and no other production module needs it independently.

Core selection and ranking logic operates on domain ``Finding`` objects.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import replace as _dc_replace

from ..domain import Finding
from ..domain.signature import Signature

# ---------------------------------------------------------------------------
# Source grouping (domain-first)
# ---------------------------------------------------------------------------


def group_findings_by_source(
    findings: tuple[Finding, ...],
) -> list[tuple[float, Finding]]:
    """Group findings by source and return ranked representatives.

    Collects unique order labels from all members of a source group
    and attaches them as signatures on the representative Finding.

    Returns ``(score, representative_domain)``
    pairs sorted by score descending.
    """
    groups: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        groups[f.source_normalized].append(f)

    grouped: list[tuple[float, Finding]] = []
    for members in groups.values():
        members_sorted = sorted(
            members,
            key=lambda f: f.phase_adjusted_score,
            reverse=True,
        )
        best = members_sorted[0]
        # Collect unique order labels from all group members as signatures
        seen: set[str] = set()
        sigs: list[Signature] = []
        for m in members_sorted:
            label = m.order.strip() if m.order else ""
            if label and label not in seen:
                seen.add(label)
                sigs.append(Signature.from_label(label, source=best.suspected_source))
        if sigs:
            best = _dc_replace(best, signatures=tuple(sigs))
        grouped.append((best.phase_adjusted_score, best))

    grouped.sort(key=lambda item: item[0], reverse=True)
    return grouped


# ---------------------------------------------------------------------------
# Confidence and top-cause selection
# ---------------------------------------------------------------------------


def confidence_label(
    conf_0_to_1: float | None,
    *,
    strength_band_key: str | None = None,
) -> tuple[str, str, str]:
    """Return ``(label_key, tone, pct_text)`` for a 0–1 confidence value.

    Delegates to :meth:`Finding.classify_confidence` so the threshold
    rules have a single source of truth in the domain model.
    """
    raw = float(conf_0_to_1) if conf_0_to_1 is not None else 0.0
    # Clamp to valid range; Finding validates [0, 1].
    clamped = max(0.0, min(1.0, raw)) if math.isfinite(raw) else 0.0
    return Finding.classify_confidence(clamped, strength_band_key=strength_band_key)


def select_top_causes(
    findings: tuple[Finding, ...],
    *,
    drop_off_points: float = 15.0,
    max_causes: int = 3,
) -> tuple[Finding, ...]:
    """Group findings by source, rank, and trim by drop-off.

    Returns domain Finding objects for the selected top causes.
    """
    surfaceable = [f for f in findings if f.should_surface]
    if not surfaceable:
        return ()

    grouped = group_findings_by_source(tuple(surfaceable))
    best_score_pct = grouped[0][0] * 100.0
    threshold_pct = best_score_pct - drop_off_points

    selected: list[Finding] = []
    for score, finding in grouped:
        if (score * 100.0) >= threshold_pct or not selected:
            selected.append(finding)
        if len(selected) >= max_causes:
            break

    return tuple(selected)
