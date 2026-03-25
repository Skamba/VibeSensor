"""Shared gate for deciding whether a report payload is projectable."""

from __future__ import annotations

from collections.abc import Mapping

__all__ = ["has_projectable_report_payload"]


def has_projectable_report_payload(payload: Mapping[str, object]) -> bool:
    return isinstance(payload.get("findings"), list) or isinstance(
        payload.get("top_causes"), list
    )
