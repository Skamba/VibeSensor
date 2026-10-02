"""Boundary translators between flat settings mappings and order-reference specs."""

from __future__ import annotations

from vibesensor.domain._order_reference_helpers import (
    ORDER_REFERENCE_KEYS,
    normalize_order_reference_mapping,
    order_reference_mapping_from_spec,
    order_reference_spec_from_mapping,
)
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.domain.order_reference import OrderReferenceSpec

__all__ = [
    "ORDER_REFERENCE_KEYS",
    "normalize_order_reference_mapping",
    "order_reference_mapping_from_spec",
    "order_reference_spec_from_mapping",
    "order_reference_spec_from_snapshot",
]


def order_reference_spec_from_snapshot(
    snapshot: AnalysisSettingsSnapshot,
) -> OrderReferenceSpec | None:
    """Build an order-reference spec from a typed analysis-settings snapshot."""

    return order_reference_spec_from_mapping(
        {key: getattr(snapshot, key) for key in ORDER_REFERENCE_KEYS},
    )
