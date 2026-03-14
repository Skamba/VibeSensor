"""Case reconciliation service."""

from __future__ import annotations

from ..diagnostic_case import DiagnosticCase


def reconcile_case(case: DiagnosticCase) -> DiagnosticCase:
    """Reconcile run-level state into case-level conclusions."""
    return case.reconcile()
