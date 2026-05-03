"""Section builders extracted from the PDF report mapper."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from vibesensor.domain import RecommendedAction, SuitabilityCheck
from vibesensor.report_i18n import (
    is_body_like_location,
    is_composite_location,
    is_i18n_ref,
    resolve_i18n,
)
from vibesensor.shared.boundaries.reporting.document import DataTrustItem, NextStep
from vibesensor.shared.report_diagnostics import localized_diagnostics
from vibesensor.shared.report_presentation import display_location
from vibesensor.shared.run_context_warning import RunContextWarning

__all__ = [
    "build_data_trust",
    "build_next_steps",
]

_REPORT_FOCUSED_ACTION_LIMIT = 3
_REPORT_FOCUSED_ACTION_SPECS: dict[str, tuple[str, bool]] = {
    "driveline_inspection": ("REPORT_NEXT_STEP_DRIVELINE_INSPECTION_WHAT", True),
    "driveline_mounts_and_fasteners": ("REPORT_NEXT_STEP_DRIVELINE_MOUNTS_WHAT", True),
    "engine_combustion_quality": ("REPORT_NEXT_STEP_ENGINE_COMBUSTION_WHAT", False),
    "engine_mounts_and_accessories": ("REPORT_NEXT_STEP_ENGINE_MOUNTS_WHAT", False),
    "general_mechanical_inspection": ("REPORT_NEXT_STEP_GENERAL_INSPECTION_WHAT", True),
    "wheel_balance_and_runout": ("REPORT_NEXT_STEP_WHEEL_BALANCE_WHAT", True),
    "wheel_tire_condition": ("REPORT_NEXT_STEP_TIRE_CONDITION_WHAT", True),
}
_PRIMARY_SOURCE_ACTION_IDS: dict[str, tuple[str, ...]] = {
    "wheel/tire": ("wheel_balance_and_runout", "wheel_tire_condition"),
    "driveline": ("driveline_inspection", "driveline_mounts_and_fasteners"),
    "engine": ("engine_mounts_and_accessories", "engine_combustion_quality"),
    "body resonance": ("general_mechanical_inspection",),
    "unknown resonance": ("general_mechanical_inspection",),
    "transient_impact": ("general_mechanical_inspection",),
    "unknown": ("general_mechanical_inspection",),
}


def build_next_steps(
    *,
    recommended_actions: Sequence[RecommendedAction],
    primary_source: object | None = None,
    primary_location: str | None = None,
    tier: str,
    cert_reason: str,
    recapture_mode: bool = False,
    lang: str,
    tr: Callable[..., str],
) -> list[NextStep]:
    """Build next-step actions from prepared report facts."""
    if tier == "A" or recapture_mode:
        return [
            NextStep(action=action, why=cert_reason)
            for action in (
                tr("TIER_A_CAPTURE_WIDER_SPEED"),
                tr("TIER_A_CAPTURE_MORE_SENSORS"),
                tr("TIER_A_CAPTURE_REFERENCE_DATA"),
            )
        ]

    report_actions = _report_actions_for_report(
        recommended_actions,
        primary_source=primary_source,
    )
    location_hint = _usable_primary_location(primary_location, tr=tr)
    next_steps: list[NextStep] = []
    for action in report_actions:
        next_steps.append(
            NextStep(
                action=_resolve_step_value(
                    _report_action_value(action, primary_location=location_hint),
                    lang=lang,
                    tr=tr,
                ),
                why=_resolve_optional_step_value(action.rationale, lang=lang, tr=tr),
                confirm=_resolve_optional_step_value(
                    action.confirmation_signal,
                    lang=lang,
                    tr=tr,
                ),
                falsify=_resolve_optional_step_value(
                    action.falsification_signal,
                    lang=lang,
                    tr=tr,
                ),
            ),
        )
    return next_steps


def _report_actions_for_report(
    recommended_actions: Sequence[RecommendedAction],
    *,
    primary_source: object | None,
) -> tuple[RecommendedAction, ...]:
    """Return the report-facing action list without disturbing custom summary steps."""
    actions = tuple(recommended_actions)
    if _uses_generated_action_plan(actions):
        source_actions = _source_aligned_report_actions(actions, primary_source)
        if source_actions:
            return source_actions[:_REPORT_FOCUSED_ACTION_LIMIT]
        return actions[:_REPORT_FOCUSED_ACTION_LIMIT]
    return actions


def _uses_generated_action_plan(actions: Sequence[RecommendedAction]) -> bool:
    """Return whether the actions came from the built-in planner action set."""
    return bool(actions) and all(
        _normalized_action_id(action.action_id) in _REPORT_FOCUSED_ACTION_SPECS
        for action in actions
    )


def _source_aligned_report_actions(
    actions: Sequence[RecommendedAction],
    primary_source: object | None,
) -> tuple[RecommendedAction, ...]:
    action_ids = _PRIMARY_SOURCE_ACTION_IDS.get(str(primary_source or "").strip().lower(), ())
    if not action_ids:
        return ()
    return tuple(
        action for action in actions if _normalized_action_id(action.action_id) in action_ids
    )


def _report_action_value(
    action: RecommendedAction,
    *,
    primary_location: str | None,
) -> object:
    """Return focused report wording when the action came from the built-in planner."""
    spec = _REPORT_FOCUSED_ACTION_SPECS.get(_normalized_action_id(action.action_id))
    if spec is None:
        return action.instruction
    key, needs_location = spec
    if not needs_location:
        return key
    if primary_location is None:
        return action.instruction
    return {"_i18n_key": key, "location": primary_location}


def _usable_primary_location(
    primary_location: str | None,
    *,
    tr: Callable[..., str],
) -> str | None:
    """Return the report hotspot when it is known enough to render directly."""
    location = str(primary_location or "").strip()
    if not location:
        return None
    unknown_tokens = {"unknown", str(tr("UNKNOWN")).strip().lower()}
    if location.lower() in unknown_tokens:
        return None
    if is_composite_location(location) or is_body_like_location(location):
        return None
    return display_location(location, tr=tr)


def _normalized_action_id(value: object) -> str:
    """Return the canonical action identifier for planner/report matching."""
    return str(value or "").strip().lower()


def _resolve_step_value(value: object, *, lang: str, tr: Callable[..., str]) -> str:
    """Resolve a required step field into report text."""
    if isinstance(value, str) and value.isupper() and "_" in value:
        translated = str(tr(value))
        if translated and translated != value:
            return translated
    return resolve_i18n(lang, value, tr=tr) if is_i18n_ref(value) else str(value or "")


def _resolve_optional_step_value(
    value: object,
    *,
    lang: str,
    tr: Callable[..., str],
) -> str | None:
    """Resolve an optional step field into report text or ``None``."""
    resolved = _resolve_step_value(value, lang=lang, tr=tr).strip()
    return resolved or None


def build_data_trust(
    *,
    suitability_checks: Sequence[SuitabilityCheck],
    warnings: Sequence[RunContextWarning],
    lang: str,
    tr: Callable[..., str],
) -> list[DataTrustItem]:
    """Build the data-trust checklist from prepared report facts."""
    return [
        DataTrustItem(
            check=diagnostic.label,
            state=diagnostic.state,
            detail=diagnostic.detail,
        )
        for diagnostic in localized_diagnostics(
            suitability_checks=suitability_checks,
            warnings=warnings,
            lang=lang,
            tr=tr,
        )
    ]
