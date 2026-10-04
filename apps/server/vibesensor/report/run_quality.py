"""Run-suitability wording shared by the PDF quality page and the History run detail."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from vibesensor.report.i18n import resolve_i18n, tr

__all__ = [
    "failing_suitability_warnings",
    "suitability_check_detail",
    "warning_codes_stated_by_checks",
]

# Suitability explanations that say nothing beyond their plain QUALITY_* sentence.
_RESTATING_EXPLANATIONS = frozenset(
    {
        "SUITABILITY_SENSOR_COVERAGE_WARN",
        "SUITABILITY_REFERENCE_COMPLETENESS_WARN",
        "SUITABILITY_RUN_DURATION_WARNING",
    }
)
# Run warnings that a failing check's explanation already states in full.
_WARNINGS_STATED_BY_EXPLANATION = {
    "SUITABILITY_FRAME_INTEGRITY_REPLAY_WARN": frozenset({"raw_replay_coverage_incomplete"}),
}


def _text(value: object) -> str:
    return value if isinstance(value, str) else str(value)


def _tr(lang: str, key: str, **kwargs: object) -> str:
    return tr(lang, key, **{name: _text(value) for name, value in kwargs.items()})


def _check_name(check: Mapping[str, object]) -> str:
    return str(check["check_key"]).removeprefix("SUITABILITY_CHECK_")


def _explanation_key(check: Mapping[str, object]) -> str | None:
    raw = check.get("explanation")
    return str(raw["_i18n_key"]) if isinstance(raw, Mapping) and "_i18n_key" in raw else None


def _failing(checks: Iterable[Mapping[str, object]]) -> list[Mapping[str, object]]:
    return [check for check in checks if check.get("state") != "pass"]


def suitability_check_detail(
    lang: str, check: Mapping[str, object], *, electric: bool = False
) -> str:
    """Plain meaning of one suitability check; a warning keeps its cause and specifics.

    The stored explanation is appended unless it only restates the plain sentence.
    A battery-electric car (*electric*) gets the sentence's ``_EV`` wording where
    one exists: it has an electric motor, not an engine and a drivetrain.
    """
    key = _check_name(check)
    passed = check["state"] == "pass"
    explanation = resolve_i18n(
        lang, check.get("explanation"), tr=lambda k, **kw: _tr(lang, k, **kw)
    ).strip()
    plain_key = f"QUALITY_{key}_{'PASS' if passed else 'WARN'}"
    if electric and _tr(lang, f"{plain_key}_EV") != f"{plain_key}_EV":
        plain_key = f"{plain_key}_EV"
    plain = _tr(lang, plain_key)
    if plain == plain_key:
        plain = explanation
    restates = _explanation_key(check) in _RESTATING_EXPLANATIONS
    if passed or restates or not explanation or explanation == plain:
        return plain
    return f"{plain} {explanation}"


def warning_codes_stated_by_checks(checks: Iterable[Mapping[str, object]]) -> frozenset[str]:
    """Codes of run warnings whose whole message a failing check already gives."""
    return frozenset(
        code
        for check in _failing(checks)
        for code in _WARNINGS_STATED_BY_EXPLANATION.get(_explanation_key(check) or "", ())
    )


def failing_suitability_warnings(
    lang: str, checks: Iterable[Mapping[str, object]], *, electric: bool = False
) -> list[dict[str, str]]:
    """Each failing check as a localized warning: its label and the PDF's detail text."""
    return [
        {
            "code": f"suitability_{_check_name(check).lower()}",
            "severity": "warn",
            "applies_to": "run_suitability",
            "title": _tr(lang, str(check["check_key"])),
            "detail": suitability_check_detail(lang, check, electric=electric),
        }
        for check in _failing(checks)
    ]
