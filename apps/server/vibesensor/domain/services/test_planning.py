"""Domain planning service for next-step diagnostic actions."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from vibesensor.domain.diagnostics.finding import Finding
from vibesensor.domain.diagnostics.recommended_action import RecommendedAction
from vibesensor.domain.diagnostics.test_plan import TestPlan

_ACTION_PRIORITY: dict[str, int] = {
    "wheel_tire_condition": 1,
    "wheel_balance_and_runout": 2,
    "engine_mounts_and_accessories": 3,
    "driveline_mounts_and_fasteners": 3,
    "driveline_inspection": 4,
    "engine_combustion_quality": 5,
    "general_mechanical_inspection": 6,
}


def _normalized_text(value: object) -> str:
    return str(value or "").strip()


def _normalized_action_id(value: object) -> str:
    return _normalized_text(value).lower()


def _fallback_action() -> RecommendedAction:
    return RecommendedAction(
        action_id="general_mechanical_inspection",
        what="COLLECT_A_LONGER_RUN_WITH_STABLE_DRIVING_CONDITIONS",
        why="NO_ACTIONABLE_FINDINGS_WERE_GENERATED_FROM_CURRENT_DATA",
        confirm="CONFIRM_CONCRETE_MECHANICAL_ISSUE_IDENTIFIED",
        falsify="FALSIFY_NO_ABNORMAL_PLAY_WEAR_OR_LOOSENESS",
        eta="20-35 min",
    )


def _actions_for_finding(finding: Finding) -> tuple[RecommendedAction, ...]:
    source = finding.source_normalized
    if source == "wheel/tire":
        return (
            RecommendedAction(
                action_id="wheel_balance_and_runout",
                what="ACTION_WHEEL_BALANCE_WHAT",
                why="ACTION_WHEEL_BALANCE_WHY",
                confirm="ACTION_WHEEL_BALANCE_CONFIRM",
                falsify="ACTION_WHEEL_BALANCE_FALSIFY",
                eta="20-45 min",
            ),
            RecommendedAction(
                action_id="wheel_tire_condition",
                what="ACTION_TIRE_CONDITION_WHAT",
                why="ACTION_TIRE_CONDITION_WHY",
                confirm="ACTION_TIRE_CONDITION_CONFIRM",
                falsify="ACTION_TIRE_CONDITION_FALSIFY",
                eta="10-20 min",
            ),
        )
    if source == "driveline":
        return (
            RecommendedAction(
                action_id="driveline_inspection",
                what="ACTION_DRIVELINE_INSPECTION_WHAT",
                why="ACTION_DRIVELINE_INSPECTION_WHY",
                confirm="ACTION_DRIVELINE_INSPECTION_CONFIRM",
                falsify="ACTION_DRIVELINE_INSPECTION_FALSIFY",
                eta="20-35 min",
            ),
            RecommendedAction(
                action_id="driveline_mounts_and_fasteners",
                what="ACTION_DRIVELINE_MOUNTS_WHAT",
                why="ACTION_DRIVELINE_MOUNTS_WHY",
                confirm="ACTION_DRIVELINE_MOUNTS_CONFIRM",
                falsify="ACTION_DRIVELINE_MOUNTS_FALSIFY",
                eta="10-20 min",
            ),
        )
    if source == "engine":
        return (
            RecommendedAction(
                action_id="engine_mounts_and_accessories",
                what="ACTION_ENGINE_MOUNTS_WHAT",
                why="ACTION_ENGINE_MOUNTS_WHY",
                confirm="ACTION_ENGINE_MOUNTS_CONFIRM",
                falsify="ACTION_ENGINE_MOUNTS_FALSIFY",
                eta="15-30 min",
            ),
            RecommendedAction(
                action_id="engine_combustion_quality",
                what="ACTION_ENGINE_COMBUSTION_WHAT",
                why="ACTION_ENGINE_COMBUSTION_WHY",
                confirm="ACTION_ENGINE_COMBUSTION_CONFIRM",
                falsify="ACTION_ENGINE_COMBUSTION_FALSIFY",
                eta="10-20 min",
            ),
        )
    return (
        RecommendedAction(
            action_id="general_mechanical_inspection",
            what="ACTION_GENERAL_INSPECTION_WHAT",
            why=(
                "ACTION_GENERAL_WEAK_SPATIAL_WHY"
                if finding.weak_spatial_separation
                else "ACTION_GENERAL_FALLBACK_WHY"
            ),
            confirm="ACTION_GENERAL_INSPECTION_CONFIRM",
            falsify="ACTION_GENERAL_INSPECTION_FALSIFY",
            eta="20-35 min",
        ),
    )


def _prioritize_actions(actions: Sequence[RecommendedAction]) -> tuple[RecommendedAction, ...]:
    deduped: dict[str, RecommendedAction] = {}
    ordered: list[RecommendedAction] = []
    for action in actions:
        action_id = _normalized_action_id(action.action_id)
        if not action_id or action_id in deduped:
            continue
        normalized_action = replace(action, action_id=action_id)
        deduped[action_id] = normalized_action
        ordered.append(normalized_action)

    if not ordered:
        ordered = [_fallback_action()]

    ordered.sort(key=lambda action: _ACTION_PRIORITY.get(action.action_id, 99))
    return tuple(
        replace(action, priority=priority) for priority, action in enumerate(ordered[:5], start=1)
    )


def plan_test_actions(
    findings: Sequence[Finding],
) -> TestPlan:
    """Build a domain test plan from domain findings.

    The domain service owns action selection and action priority for the
    migrated finding-based planning path.
    """
    actions: list[RecommendedAction] = []
    for finding in findings:
        actions.extend(_actions_for_finding(finding))
    return TestPlan(
        actions=_prioritize_actions(actions),
        requires_additional_data=not bool(findings),
    )
