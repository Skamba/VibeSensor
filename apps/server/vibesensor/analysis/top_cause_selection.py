"""Top-cause selection, ranking helpers, and confidence presentation.

Ranking helper ``group_findings_by_source`` was previously in a separate
``ranking`` module but merged here because this module is its primary
consumer and no other production module needs it independently.

Core selection and ranking logic operates on domain ``Finding`` objects.
Payload enrichment (confidence labels, phase evidence) is applied only
for serialization-boundary output.
"""

from __future__ import annotations

import math
from collections import defaultdict

from ..domain import Finding
from ._types import FindingPayload

# ---------------------------------------------------------------------------
# Top-cause building (payload enrichment for serialization boundary)
# ---------------------------------------------------------------------------


def _enrich_top_cause_payload(
    finding: FindingPayload,
    domain: Finding,
    *,
    strength_band_key: str | None = None,
) -> FindingPayload:
    """Enrich a finding payload with confidence presentation fields for serialization."""
    label_key, tone, pct_text = domain.confidence_label(
        strength_band_key=strength_band_key,
    )
    result: FindingPayload = {**finding}
    result["confidence_label_key"] = label_key
    result["confidence_tone"] = tone
    result["confidence_pct"] = pct_text
    # Normalize order: prefer domain.order, fall back to payload's
    # frequency_hz_or_order — the payload may carry the order text there
    # while Finding.from_payload only reads from the ``order`` key.
    order = domain.order or str(finding.get("frequency_hz_or_order") or finding.get("order") or "")
    result["order"] = order
    result["phase_evidence"] = (
        {"cruise_fraction": domain.cruise_fraction} if domain.cruise_fraction else None
    )
    return result


# ---------------------------------------------------------------------------
# Source grouping (domain-first)
# ---------------------------------------------------------------------------


def group_findings_by_source(
    diag_findings: list[FindingPayload],
    *,
    domain_findings: tuple[Finding, ...] | None = None,
) -> list[tuple[float, FindingPayload, Finding]]:
    """Group findings by source and return ranked representatives.

    When *domain_findings* is provided it must correspond 1:1 with
    *diag_findings* and avoids repeated ``from_payload()`` calls.

    Returns ``(score, representative_payload, representative_domain)``
    triples sorted by score descending.
    """
    # Pair payloads with domain objects
    if domain_findings is not None and len(domain_findings) == len(diag_findings):
        pairs = list(zip(diag_findings, domain_findings, strict=True))
    else:
        pairs = [(f, Finding.from_payload(f)) for f in diag_findings]

    groups: dict[str, list[tuple[FindingPayload, Finding]]] = defaultdict(list)
    for payload, domain in pairs:
        groups[domain.source_normalized].append((payload, domain))

    grouped: list[tuple[float, FindingPayload, Finding]] = []
    for members in groups.values():
        members_scored = sorted(
            members,
            key=lambda item: item[1].phase_adjusted_score,
            reverse=True,
        )
        best_payload, best_domain = members_scored[0]
        representative: FindingPayload = {**best_payload}
        signatures: list[str] = []
        seen_signatures: set[str] = set()
        for payload, _domain in members_scored:
            signature = str(payload.get("frequency_hz_or_order") or "").strip()
            if signature and signature not in seen_signatures:
                signatures.append(signature)
                seen_signatures.add(signature)
        representative["signatures_observed"] = signatures
        representative["grouped_count"] = len(members_scored)
        grouped.append((best_domain.phase_adjusted_score, representative, best_domain))

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

    Delegates to :meth:`Finding.confidence_label` so the threshold
    rules have a single source of truth in the domain model.
    """
    raw = float(conf_0_to_1) if conf_0_to_1 is not None else 0.0
    # Clamp to valid Finding range; Finding validates [0, 1].
    clamped = max(0.0, min(1.0, raw)) if math.isfinite(raw) else 0.0
    f = Finding(confidence=clamped)
    return f.confidence_label(strength_band_key=strength_band_key)


def select_top_causes(
    findings: list[FindingPayload],
    *,
    domain_findings: tuple[Finding, ...] | None = None,
    drop_off_points: float = 15.0,
    max_causes: int = 3,
    strength_band_key: str | None = None,
) -> tuple[list[FindingPayload], tuple[Finding, ...]]:
    """Group findings by source, rank, and trim by drop-off.

    When *domain_findings* is provided it must correspond 1:1 with
    *findings* and avoids repeated ``from_payload()`` calls.

    Returns ``(enriched_payloads, domain_top_causes)``.
    """
    # Pair payloads with domain objects
    if domain_findings is not None and len(domain_findings) == len(findings):
        pairs = list(zip(findings, domain_findings, strict=True))
    else:
        pairs = [(f, Finding.from_payload(f)) for f in findings if isinstance(f, dict)]

    surfaceable = [(payload, domain) for payload, domain in pairs if domain.should_surface]
    if not surfaceable:
        return [], ()

    surfaceable_payloads = [p for p, _d in surfaceable]
    surfaceable_domains = tuple(d for _p, d in surfaceable)

    grouped = group_findings_by_source(surfaceable_payloads, domain_findings=surfaceable_domains)
    best_score_pct = grouped[0][0] * 100.0
    threshold_pct = best_score_pct - drop_off_points

    selected_payloads: list[FindingPayload] = []
    selected_domains: list[Finding] = []
    for score, representative, domain in grouped:
        if (score * 100.0) >= threshold_pct or not selected_payloads:
            selected_payloads.append(representative)
            selected_domains.append(domain)
        if len(selected_payloads) >= max_causes:
            break

    enriched = [
        _enrich_top_cause_payload(f, d, strength_band_key=strength_band_key)
        for f, d in zip(selected_payloads, selected_domains, strict=True)
    ]
    return enriched, tuple(selected_domains)
