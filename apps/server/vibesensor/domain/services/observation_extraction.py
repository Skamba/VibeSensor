"""Observation extraction service."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ..driving_phase import DrivingPhase
from ..finding import Finding
from ..observation import Observation


def extract_observations_from_findings(
    findings: Sequence[Finding],
    payloads: Sequence[Mapping[str, object]] | None = None,
) -> tuple[Observation, ...]:
    """Derive diagnostically meaningful observations from finding evidence."""
    payload_map = list(payloads or ())
    observations: list[Observation] = []
    for idx, finding in enumerate(findings, start=1):
        payload = payload_map[idx - 1] if idx - 1 < len(payload_map) else {}
        dominant_phase = str(payload.get("dominant_phase") or "").upper() if payload else ""
        phase = DrivingPhase[dominant_phase] if dominant_phase in DrivingPhase.__members__ else None
        signature_labels = finding.signature_labels or (
            str(payload.get("frequency_hz_or_order") or ""),
        )
        for sig_idx, signature_label in enumerate(signature_labels, start=1):
            if not signature_label.strip():
                continue
            observations.append(
                Observation(
                    observation_id=f"{finding.finding_id or idx}-obs-{sig_idx}",
                    kind="signature-support",
                    source=finding.suspected_source,
                    signature_key=signature_label.strip().lower().replace(" ", "_"),
                    magnitude_db=finding.vibration_strength_db,
                    speed_band=finding.strongest_speed_band,
                    phase=phase,
                    location=finding.strongest_location,
                    support_score=finding.effective_confidence,
                )
            )
    return tuple(observations)
