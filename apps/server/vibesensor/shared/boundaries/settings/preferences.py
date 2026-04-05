"""Shared boundary helpers for UI-preference HTTP payloads."""

from __future__ import annotations

from vibesensor.shared.types.settings_types import LanguageCode, SpeedUnitCode


def language_response_payload(language: LanguageCode) -> dict[str, object]:
    """Project the active language code into the HTTP response shape."""

    return {"language": language}


def speed_unit_response_payload(speed_unit: SpeedUnitCode) -> dict[str, object]:
    """Project the active speed-unit code into the HTTP response shape."""

    return {"speed_unit": speed_unit}


__all__ = ["language_response_payload", "speed_unit_response_payload"]
