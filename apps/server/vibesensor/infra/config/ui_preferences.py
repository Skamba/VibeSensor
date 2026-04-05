"""Focused persisted UI language and units preferences."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import RLock
from typing import get_args

from vibesensor.infra.config.car_settings import _UpdateWithRollback
from vibesensor.infra.config.settings_transaction import log_settings_change
from vibesensor.shared.boundaries.settings.snapshot import (
    validated_language_code as _validated_language,
)
from vibesensor.shared.boundaries.settings.snapshot import (
    validated_speed_unit_code as _validated_speed_unit,
)
from vibesensor.shared.types.settings_types import LanguageCode, SpeedUnitCode

__all__ = ["UiPreferencesService", "UiPreferencesState"]

LOGGER = logging.getLogger(__name__)

VALID_LANGUAGES: frozenset[str] = frozenset(get_args(LanguageCode))
VALID_SPEED_UNITS: frozenset[str] = frozenset(get_args(SpeedUnitCode))


@dataclass(slots=True)
class UiPreferencesState:
    """Mutable UI preferences shared by the focused persisted settings services."""

    language: LanguageCode = "en"
    speed_unit: SpeedUnitCode = "kmh"


class UiPreferencesService:
    """Persisted language and speed-unit preferences."""

    __slots__ = ("_lock", "_state", "_update_with_rollback")

    def __init__(
        self,
        *,
        lock: RLock,
        state: UiPreferencesState,
        update_with_rollback: _UpdateWithRollback,
    ) -> None:
        self._lock = lock
        self._state = state
        self._update_with_rollback = update_with_rollback

    @property
    def language(self) -> LanguageCode:
        with self._lock:
            return self._state.language

    def set_language(self, value: str) -> LanguageCode:
        language = _validated_language(value)
        if language is None:
            raise ValueError(f"language must be one of {sorted(VALID_LANGUAGES)}")

        def _apply(_previous: LanguageCode) -> bool:
            self._state.language = language
            return True

        return self._update_with_rollback(
            snapshot=lambda: self._state.language,
            apply=_apply,
            restore=lambda previous: setattr(self._state, "language", previous),
            audit_log=lambda previous: log_settings_change(
                LOGGER,
                action="set_language",
                before=previous,
                after=self._state.language,
            ),
            result=lambda: self._state.language,
        )

    @property
    def speed_unit(self) -> SpeedUnitCode:
        with self._lock:
            return self._state.speed_unit

    def set_speed_unit(self, value: str) -> SpeedUnitCode:
        unit = _validated_speed_unit(value)
        if unit is None:
            raise ValueError(f"speed_unit must be one of {sorted(VALID_SPEED_UNITS)}")

        def _apply(_previous: SpeedUnitCode) -> bool:
            self._state.speed_unit = unit
            return True

        return self._update_with_rollback(
            snapshot=lambda: self._state.speed_unit,
            apply=_apply,
            restore=lambda previous: setattr(self._state, "speed_unit", previous),
            audit_log=lambda previous: log_settings_change(
                LOGGER,
                action="set_speed_unit",
                before=previous,
                after=self._state.speed_unit,
            ),
            result=lambda: self._state.speed_unit,
        )
