"""Car profile CRUD — extracted from ``SettingsStore``.

``CarSettingsMixin`` encapsulates all car-profile management methods.
``SettingsStore`` inherits from the mixin so that the public API is
unchanged for all consumers.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from vibesensor.domain import Car, CarSnapshot
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.shared.exceptions import PersistenceError
from vibesensor.shared.types.backend_types import (
    AnalysisSettingsPayload,
    CarConfigUpdatePayload,
    car_to_persistence_dict,
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
        _cars: list[Car]
        _active_car_id: str | None
        _sanitize_analysis: staticmethod

        def _persist(self) -> None: ...
        def _sync_analysis_settings(self) -> None: ...

    # -- domain-object accessors -----------------------------------------------

    def active_car(self) -> Car | None:
        """Return the active car as a domain ``Car`` value object."""
        with self._lock:
            return self._find_car(self._active_car_id)

    # -- car operations --------------------------------------------------------

    def get_cars(self) -> dict[str, object]:
        with self._lock:
            return {
                "cars": [car_to_persistence_dict(c) for c in self._cars],
                "activeCarId": self._active_car_id,
            }

    def active_car_aspects(self) -> dict[str, float] | None:
        """Return the active car's aspects as a flat analysis-settings dict.

        Routes through the domain ``Car`` object so dimension validation
        (rejecting zero and negative values) fires on the hot path.
        """
        with self._lock:
            car = self._find_car(self._active_car_id)
            if car is None:
                return None
            return dict(car.aspects)

    def active_car_snapshot(self) -> CarSnapshot | None:
        """Return the active car profile as a typed domain snapshot."""
        with self._lock:
            car = self._find_car(self._active_car_id)
            if car is None:
                return None
            return CarSnapshot(
                car_id=car.id,
                name=car.name,
                car_type=car.car_type,
                variant=car.variant,
                aspects=dict(car.aspects),
            )

    def _find_car(self, car_id: str | None) -> Car | None:
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
            car = Car.from_persisted_dict(payload)
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
            idx = next(i for i, c in enumerate(self._cars) if c.id == car_id)
            # Build updated fields via reconstruction
            new_name = car.name
            if "name" in car_data:
                raw_name = car_data["name"]
                if isinstance(raw_name, str):
                    clamped = _clamp_str(raw_name, 64)
                    if clamped:
                        new_name = clamped
            new_car_type = car.car_type
            if "type" in car_data:
                raw_type = car_data["type"]
                if isinstance(raw_type, str):
                    clamped = _clamp_str(raw_type, 32)
                    if clamped:
                        new_car_type = clamped
            new_aspects = dict(car.aspects)
            if "aspects" in car_data and isinstance(car_data["aspects"], dict):
                new_aspects.update(AnalysisSettingsSnapshot.sanitize(car_data["aspects"]))
            new_variant = car.variant
            if "variant" in car_data:
                raw = car_data["variant"]
                new_variant = _clamp_str(raw, 64) or None if isinstance(raw, str) and raw else None
            updated = Car(
                id=car.id,
                name=new_name,
                car_type=new_car_type,
                aspects=new_aspects,
                variant=new_variant,
            )
            self._cars[idx] = updated
            try:
                self._persist()
            except PersistenceError:
                self._cars[idx] = car  # rollback
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
            idx = next(i for i, c in enumerate(self._cars) if c.id == car.id)
            new_aspects = {**car.aspects, **AnalysisSettingsSnapshot.sanitize(aspects)}
            updated = Car(
                id=car.id,
                name=car.name,
                car_type=car.car_type,
                aspects=new_aspects,
                variant=car.variant,
            )
            self._cars[idx] = updated
            try:
                self._persist()
            except PersistenceError:
                self._cars[idx] = car  # rollback
                raise
            self._sync_analysis_settings()
            return dict(updated.aspects)

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
