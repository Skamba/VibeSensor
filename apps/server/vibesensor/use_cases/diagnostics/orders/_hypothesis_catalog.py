"""Shared catalog helpers for whole-run order-hypothesis consumers."""

from __future__ import annotations

from collections.abc import Iterable

from vibesensor.use_cases.diagnostics.orders.physics import OrderHypothesis, _order_hypotheses


def order_hypotheses_by_key() -> dict[str, OrderHypothesis]:
    return {hypothesis.key: hypothesis for hypothesis in _order_hypotheses()}


def order_hypothesis_path_compliance_by_key() -> dict[str, float]:
    return {hypothesis.key: hypothesis.path_compliance for hypothesis in _order_hypotheses()}


def ordered_order_hypothesis_keys(keys: Iterable[str]) -> tuple[str, ...]:
    catalog = _order_hypotheses()
    pending_keys = set(keys)
    ordered_keys = [hypothesis.key for hypothesis in catalog if hypothesis.key in pending_keys]
    known_keys = {hypothesis.key for hypothesis in catalog}
    ordered_keys.extend(sorted(key for key in pending_keys if key not in known_keys))
    return tuple(ordered_keys)
