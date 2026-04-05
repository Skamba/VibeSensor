"""Focused persisted speed-source settings service."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from threading import RLock

from vibesensor.infra.config.car_settings import _UpdateWithRollback
from vibesensor.infra.config.settings_transaction import log_settings_change
from vibesensor.shared.types.speed_source_config import (
    SpeedSourceConfig,
    SpeedSourcePayload,
    SpeedSourceUpdatePayload,
)

__all__ = ["PersistedSpeedSourceSettingsService", "SpeedSourceSettingsState"]

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class SpeedSourceSettingsState:
    """Mutable speed-source settings shared by the focused persisted services."""

    config: SpeedSourceConfig = field(default_factory=SpeedSourceConfig.default)


class PersistedSpeedSourceSettingsService:
    """Persist and expose the canonical speed-source configuration."""

    __slots__ = ("_lock", "_state", "_update_with_rollback")

    def __init__(
        self,
        *,
        lock: RLock,
        state: SpeedSourceSettingsState,
        update_with_rollback: _UpdateWithRollback,
    ) -> None:
        self._lock = lock
        self._state = state
        self._update_with_rollback = update_with_rollback

    def speed_source_config(self) -> SpeedSourceConfig:
        with self._lock:
            return self._state.config.copy()

    def get_speed_source(self) -> SpeedSourcePayload:
        return self.speed_source_config().to_dict()

    def preview_speed_source_update(self, data: SpeedSourceUpdatePayload) -> SpeedSourceConfig:
        return self.speed_source_config().updated(data)

    def persist_speed_source(self, config: SpeedSourceConfig) -> SpeedSourceConfig:
        next_config = config.copy()

        def _apply(_previous: SpeedSourcePayload) -> bool:
            self._state.config = next_config.copy()
            return True

        return self._update_with_rollback(
            snapshot=lambda: self._state.config.to_dict(),
            apply=_apply,
            restore=lambda previous: setattr(
                self._state,
                "config",
                SpeedSourceConfig.from_dict(previous),
            ),
            audit_log=lambda previous: log_settings_change(
                LOGGER,
                action="persist_speed_source",
                before=previous,
                after=next_config.to_dict(),
            ),
            result=self.speed_source_config,
        )

    def update_speed_source(self, data: SpeedSourceUpdatePayload) -> SpeedSourcePayload:
        return self.persist_speed_source(self.preview_speed_source_update(data)).to_dict()
