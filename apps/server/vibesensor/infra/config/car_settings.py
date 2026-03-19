"""Car profile CRUD — extracted from ``SettingsStore``.

``CarSettingsMixin`` encapsulates all car-profile management methods.
``SettingsStore`` inherits from the mixin so that the public API is
unchanged for all consumers.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from vibesensor.domain import Car, CarSnapshot
from vibesensor.domain.snapshots import AnalysisSettingsSnapshot
from vibesensor.shared.exceptions import PersistenceError
from vibesensor.shared.types.backend_types import (
    AnalysisSettingsPayload,
    CarConfig,
    CarConfigUpdatePayload,
    new_car_id,
)

if TYPE_CHECKING:
    from threading import RLock

LOGGER = logging.getLogger(__name__)


def _clamp_str(value: object, maxlen: int) -> str:
    """Strip and truncate *value* to *maxlen* characters."""
    return str(value).strip()[:maxlen]


class CarSettingsMixin:
    """Car-profile CRUD methods mixed into :class:`SettingsStore`.

    Accesses ``self._lock``, ``self._cars``, ``self._active_car_id``,
    ``self._persist()``, and ``self._sync_analysis_settings()`` from
    the host class.
    """

    # Declared for type-checker visibility; actual attributes live on SettingsStore.
    if TYPE_CHECKING:
        _lock: RLock
        _cars: list[CarConfig]
        _active_car_id: str | None
        _sanitize_analysis: staticmethod

        def _persist(self) -> None: ...
        def _sync_analysis_settings(self) -> None: ...

    # -- domain-object accessors -----------------------------------------------

    def active_car(self) -> Car | None:
        """Return the active car as a domain ``Car`` value object."""
        with self._lock:
            car_cfg = self._find_car(self._active_car_id)
            if car_cfg is None:
                return None
            return Car(
                id=car_cfg.id,
                name=car_cfg.name,
                car_type=car_cfg.car_type,
                aspects=dict(car_cfg.aspects),
                variant=car_cfg.variant,
            )

    # -- car operations --------------------------------------------------------

    def get_cars(self) -> dict[str, object]:
        with self._lock:
            return {
                "cars": [c.to_dict() for c in self._cars],
                "activeCarId": self._active_car_id,
            }

    def active_car_aspects(self) -> dict[str, float] | None:
        """Return the active car's aspects as a flat analysis-settings dict.

        Routes through the domain ``Car`` object so dimension validation
        (rejecting zero and negative values) fires on the hot path.
        """
        with self._lock:
            car_cfg = self._find_car(self._active_car_id)
            if car_cfg is None:
                return None
            car = Car(
                id=car_cfg.id,
                name=car_cfg.name,
                car_type=car_cfg.car_type,
                aspects=dict(car_cfg.aspects),
                variant=car_cfg.variant,
            )
            return dict(car.aspects)

    def active_car_snapshot(self) -> CarSnapshot | None:
        """Return the active car profile as a typed domain snapshot."""
        with self._lock:
            car_cfg = self._find_car(self._active_car_id)
            if car_cfg is None:
                return None
            return CarSnapshot(
                car_id=car_cfg.id,
                name=car_cfg.name,
                car_type=car_cfg.car_type,
                variant=car_cfg.variant,
                aspects=dict(car_cfg.aspects),
            )

    def _find_car(self, car_id: str | None) -> CarConfig | None:
        if not car_id:
            return None
        return next((c for c in self._cars if c.id == car_id), None)

    def set_active_car(self, car_id: str) -> dict[str, object]:
        with self._lock:
            car = self._find_car(car_id)
            if car is None:
                raise ValueError(f"Unknown car id: {car_id}")
            old_active = self._active_car_id
            self._active_car_id = car_id
            try:
                self._persist()
            except PersistenceError:
                self._active_car_id = old_active
                raise
            self._sync_analysis_settings()
            return self.get_cars()

    def add_car(self, car_data: CarConfigUpdatePayload) -> dict[str, object]:
        with self._lock:
            payload: dict[str, object] = dict(car_data)
            payload["id"] = new_car_id()
            car = CarConfig.from_dict(payload)
            self._cars.append(car)
            try:
                self._persist()
            except PersistenceError:
                self._cars.pop()  # rollback in-memory append
                raise
            self._sync_analysis_settings()
            return self.get_cars()

    def update_car(self, car_id: str, car_data: CarConfigUpdatePayload) -> dict[str, object]:
        with self._lock:
            car = self._find_car(car_id)
            if car is None:
                raise ValueError(f"Unknown car id: {car_id}")
            # Snapshot for rollback
            old_name, old_type = car.name, car.car_type
            old_aspects = dict(car.aspects)
            old_variant = car.variant
            if "name" in car_data:
                raw_name = car_data["name"]
                if isinstance(raw_name, str):
                    name = _clamp_str(raw_name, 64)
                    if name:
                        car.name = name
            if "type" in car_data:
                raw_type = car_data["type"]
                if isinstance(raw_type, str):
                    car_type = _clamp_str(raw_type, 32)
                    if car_type:
                        car.car_type = car_type
            if "aspects" in car_data and isinstance(car_data["aspects"], dict):
                car.aspects.update(AnalysisSettingsSnapshot.sanitize(car_data["aspects"]))
            if "variant" in car_data:
                raw = car_data["variant"]
                car.variant = _clamp_str(raw, 64) or None if isinstance(raw, str) and raw else None
            try:
                self._persist()
            except PersistenceError:
                car.name, car.car_type = old_name, old_type
                car.aspects.clear()
                car.aspects.update(old_aspects)
                car.variant = old_variant
                raise
            self._sync_analysis_settings()
            return self.get_cars()

    def update_active_car_aspects(
        self,
        aspects: AnalysisSettingsPayload,
    ) -> AnalysisSettingsPayload:
        with self._lock:
            car = self._find_car(self._active_car_id)
            if car is None:
                raise ValueError("No active car configured")
            old_aspects = dict(car.aspects)
            car.aspects.update(AnalysisSettingsSnapshot.sanitize(aspects))
            try:
                self._persist()
            except PersistenceError:
                car.aspects.clear()
                car.aspects.update(old_aspects)
                raise
            self._sync_analysis_settings()
            return dict(car.aspects)

    def delete_car(self, car_id: str) -> dict[str, object]:
        with self._lock:
            car = self._find_car(car_id)
            if car is None:
                raise ValueError(f"Unknown car id: {car_id}")
            if len(self._cars) <= 1:
                raise ValueError("Cannot delete the last car")
            old_cars = list(self._cars)
            old_active = self._active_car_id
            self._cars = [c for c in self._cars if c.id != car_id]
            if self._active_car_id == car_id:
                self._active_car_id = self._cars[0].id if self._cars else None
            try:
                self._persist()
            except PersistenceError:
                self._cars = old_cars
                self._active_car_id = old_active
                raise
            self._sync_analysis_settings()
            return self.get_cars()
