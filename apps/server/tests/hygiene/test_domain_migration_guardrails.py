"""Guardrails that prevent regressions to legacy payload-first compatibility paths."""

from __future__ import annotations

import pytest

from vibesensor.domain import Finding
from vibesensor.use_cases.diagnostics.findings import finalize_findings


def test_f_order_finding_id_normalization_preserves_order_and_reference_ids() -> None:
    """``finalize_findings`` normalises arbitrary IDs to sequential ``F###``.

    ``F_ORDER`` is an internal working ID from order analysis.
    ``finalize_findings`` replaces all non-reference IDs with stable
    sequential ``F001``, ``F002``, … so that report and history
    consumers see deterministic identifiers.  The normalization to
    ``F001`` is correct behavior, not a test bug.
    """

    domain_findings = finalize_findings(
        [
            Finding(
                finding_id="F_ORDER",
                confidence=0.7,
                ranking_score=0.3,
                suspected_source="wheel/tire",
            ),
            Finding(
                finding_id="F_PERSISTENT",
                confidence=0.4,
                ranking_score=0.9,
                suspected_source="engine",
            ),
        ]
    )
    assert [finding.finding_id for finding in domain_findings] == ["F001", "F002"]
    assert [finding.suspected_source for finding in domain_findings] == ["wheel/tire", "engine"]

    # Reference findings keep their original IDs
    domain_ref = finalize_findings(
        [
            Finding(finding_id="REF_SPEED", confidence=None, ranking_score=0.1),
            Finding(finding_id="F_ORDER", confidence=0.7, ranking_score=0.2),
        ]
    )
    assert [finding.finding_id for finding in domain_ref] == ["REF_SPEED", "F001"]


def test_no_compat_dual_base_exceptions() -> None:
    """All VibeSensorError subclasses must not also inherit from stdlib
    exception types (ValueError, RuntimeError, LookupError, etc.).

    This prevents accidental dual-base compatibility shims that let callers
    catch stdlib types and bypass the domain exception hierarchy.
    """
    from vibesensor.shared.exceptions import VibeSensorError

    # stdlib exception types that should never appear as co-parents
    stdlib_bases = (
        ValueError,
        TypeError,
        RuntimeError,
        LookupError,
        KeyError,
        IndexError,
        AttributeError,
        OSError,
        IOError,
        NotImplementedError,
        ArithmeticError,
        StopIteration,
    )

    violations: list[str] = []

    def _check_recursive(cls: type) -> None:
        # MRO between cls and VibeSensorError should contain no stdlib types
        mro = cls.__mro__
        vs_idx = mro.index(VibeSensorError)
        between = mro[1:vs_idx]  # skip cls itself, stop before VibeSensorError
        for entry in between:
            if entry in stdlib_bases or (
                issubclass(entry, BaseException)
                and entry not in (VibeSensorError, Exception, BaseException)
                and entry.__module__ == "builtins"
            ):
                violations.append(
                    f"{cls.__name__} inherits from stdlib {entry.__name__} "
                    f"(MRO: {[c.__name__ for c in mro]})"
                )
        for sub in cls.__subclasses__():
            _check_recursive(sub)

    _check_recursive(VibeSensorError)

    assert not violations, (
        "Custom exceptions must inherit exclusively from VibeSensorError, "
        f"not from stdlib exception types: {violations}"
    )


@pytest.mark.parametrize(
    "legacy_id",
    [
        pytest.param("F_ORDER", id="order"),
        pytest.param("F_PERSISTENT", id="persistent"),
        pytest.param("CUSTOM_FINDING", id="custom"),
    ],
)
def test_non_reference_finding_ids_get_stable_sequential_ids(legacy_id: str) -> None:
    domain_findings = finalize_findings([Finding(finding_id=legacy_id, confidence=0.7)])

    assert [finding.finding_id for finding in domain_findings] == ["F001"]
