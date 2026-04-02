"""Guardrails that prevent regressions to legacy payload-first compatibility paths."""

from __future__ import annotations


def test_finding_has_no_from_payload_method() -> None:
    """Finding domain class should not own payload decode logic."""
    from vibesensor.domain import Finding

    assert not hasattr(Finding, "from_payload"), (
        "Finding.from_payload should live in boundaries/finding.py, not on the domain class"
    )


def test_build_run_suitability_checks_does_not_exist() -> None:
    """``build_run_suitability_checks`` must not exist in run_analysis.

    It was deleted in Workstream 2 (T3.21).  ``RunSuitability.evaluate()``
    is the canonical owner of suitability evaluation.
    """
    from vibesensor.use_cases.diagnostics import run_analysis

    assert not hasattr(run_analysis, "build_run_suitability_checks"), (
        "build_run_suitability_checks was deleted; use RunSuitability.evaluate()"
    )


def test_project_analysis_summary_has_no_legacy_summary_version_fast_path() -> None:
    """project_analysis_summary must always reconstruct through TestRun.

    The legacy `_summary_version == 2` bypass was removed. Historical
    summaries are reconstructed the same way as current ones so the
    boundary has a single canonical behavior.
    """
    from tests._paths import SERVER_ROOT

    source = (
        SERVER_ROOT / "vibesensor" / "shared" / "boundaries" / "analysis_summary_projection.py"
    ).read_text()
    assert 'analysis.get("_summary_version") == 2' not in source


def test_run_analysis_does_not_define_case_context_wrappers() -> None:
    """run_analysis must not own duplicate Car/Symptom metadata decoders."""
    from tests._paths import SERVER_ROOT

    source = (
        SERVER_ROOT / "vibesensor" / "use_cases" / "diagnostics" / "run_analysis.py"
    ).read_text()
    assert "def build_domain_car" not in source
    assert "def build_domain_symptoms" not in source
    assert "RunSuitabilityCheck" not in source


def test_f_order_finding_id_normalization() -> None:
    """``finalize_findings`` normalises arbitrary IDs to sequential ``F###``.

    ``F_ORDER`` is an internal working ID from order analysis.
    ``finalize_findings`` replaces all non-reference IDs with stable
    sequential ``F001``, ``F002``, … so that report and history
    consumers see deterministic identifiers.  The normalization to
    ``F001`` is correct behavior, not a test bug.
    """
    from vibesensor.domain import Finding
    from vibesensor.use_cases.diagnostics.findings import finalize_findings

    domain_findings = finalize_findings(
        [
            Finding(finding_id="F_ORDER", confidence=0.7, suspected_source="wheel/tire"),
            Finding(finding_id="F_PERSISTENT", confidence=0.4, suspected_source="engine"),
        ]
    )
    # Both get sequential F### IDs regardless of their input names
    assert domain_findings[0].finding_id == "F001"
    assert domain_findings[1].finding_id == "F002"
    assert all(isinstance(f, Finding) for f in domain_findings)

    # Reference findings keep their original IDs
    domain_ref = finalize_findings(
        [
            Finding(finding_id="REF_SPEED", confidence=None, suspected_source="unknown"),
            Finding(finding_id="F_ORDER", confidence=0.7, suspected_source="wheel/tire"),
        ]
    )
    assert domain_ref[0].finding_id == "REF_SPEED"
    assert domain_ref[1].finding_id == "F001"


def test_fallback_payload_functions_removed() -> None:
    """``top_strength_values`` and ``has_relevant_reference_gap`` have been
    removed — the domain aggregate is always available."""
    from vibesensor.adapters.pdf import mapping

    assert not hasattr(mapping, "top_strength_values")
    assert not hasattr(mapping, "has_relevant_reference_gap")


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
