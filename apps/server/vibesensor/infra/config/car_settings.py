"""Car profile CRUD — extracted from ``SettingsStore``.

``CarSettingsMixin`` encapsulates all car-profile management methods.
``SettingsStore`` inherits from the mixin so that the public API is
unchanged for all consumers.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar

from vibesensor.domain import Car, CarSnapshot
from vibesensor.domain.analysis_settings import AnalysisSettingsSnapshot
from vibesensor.shared.types.car_config import (
    CarConfigUpdatePayload,
    CarsSnapshot,
    car_to_persistence_dict,
    new_car_id,
)
from vibesensor.shared.types.settings_types import AnalysisSettingsPayload

if TYPE_CHECKING:
    from threading import RLock

LOGGER = logging.getLogger(__name__)
_CarSettingsSnapshotT = TypeVar("_CarSettingsSnapshotT")
_CarSettingsResultT = TypeVar("_CarSettingsResultT")


def _clamp_str(value: object, maxlen: int) -> str:
    """Strip and truncate *value* to *maxlen* characters."""
    return str(value).strip()[:maxlen]


class CarSettingsMixin:
    """Car-profile CRUD methods mixed into :class:`SettingsStore`.

    Accesses ``self._lock``, ``self._cars``, ``self._active_car_id``,
    ``self._update_with_rollback()``, and ``self._sync_analysis_settings()``
    from the host class.
    """

    # Declared for type-checker visibility; actual attributes live on SettingsStore.
    if TYPE_CHECKING:
        _lock: RLock
        _cars: list[Car]
        _active_car_id: str | None
        _sanitize_analysis: staticmethod

        def _sync_analysis_settings(self) -> None: ...
        def _update_with_rollback(
            self,
            *,
            snapshot: Callable[[], _CarSettingsSnapshotT],
            apply: Callable[[_CarSettingsSnapshotT], bool],
            restore: Callable[[_CarSettingsSnapshotT], None],
            after_persist: Callable[[], None] | None = None,
            result: Callable[[], _CarSettingsResultT],
        ) -> _CarSettingsResultT: ...

    # -- domain-object accessors -----------------------------------------------

    def active_car(self) -> Car | None:
        """Return the active car as a domain ``Car`` value object."""
        with self._lock:
            return self._find_car(self._active_car_id)

    # -- car operations --------------------------------------------------------

    def _cars_snapshot_unlocked(self) -> CarsSnapshot:
        return CarsSnapshot(
            cars=[car_to_persistence_dict(car) for car in self._cars],
            active_car_id=self._active_car_id,
        )

    def get_cars(self) -> CarsSnapshot:
        with self._lock:
            return self._cars_snapshot_unlocked()

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

    def set_active_car(self, car_id: str) -> CarsSnapshot:
        def _apply(_previous: str | None) -> bool:
            car = self._find_car(car_id)
            if car is None:
                raise ValueError(f"Unknown car id: {car_id}")
            self._active_car_id = car_id
            return True

        return self._update_with_rollback(
            snapshot=lambda: self._active_car_id,
            apply=_apply,
            restore=lambda previous: setattr(self, "_active_car_id", previous),
            after_persist=self._sync_analysis_settings,
            result=self._cars_snapshot_unlocked,
        )

    def add_car(self, car_data: CarConfigUpdatePayload) -> CarsSnapshot:
        def _apply(_previous: list[Car]) -> bool:
            payload: dict[str, object] = dict(car_data)
            payload["id"] = new_car_id()
            self._cars.append(Car.from_persisted_dict(payload))
            return True

        return self._update_with_rollback(
            snapshot=lambda: list(self._cars),
            apply=_apply,
            restore=lambda previous: setattr(self, "_cars", previous),
            after_persist=self._sync_analysis_settings,
            result=self._cars_snapshot_unlocked,
        )

    def update_car(self, car_id: str, car_data: CarConfigUpdatePayload) -> CarsSnapshot:
        def _apply(_previous: list[Car]) -> bool:
            car = self._find_car(car_id)
            if car is None:
                raise ValueError(f"Unknown car id: {car_id}")
            idx = next(i for i, current in enumerate(self._cars) if current.id == car_id)
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
                raw_variant = car_data["variant"]
                if isinstance(raw_variant, str) and raw_variant:
                    new_variant = _clamp_str(raw_variant, 64) or None
                else:
                    new_variant = None
            self._cars[idx] = Car(
                id=car.id,
                name=new_name,
                car_type=new_car_type,
                aspects=new_aspects,
                variant=new_variant,
            )
            return True

        return self._update_with_rollback(
            snapshot=lambda: list(self._cars),
            apply=_apply,
            restore=lambda previous: setattr(self, "_cars", previous),
            after_persist=self._sync_analysis_settings,
            result=self._cars_snapshot_unlocked,
        )

    def update_active_car_aspects(
        self,
        aspects: AnalysisSettingsPayload,
    ) -> AnalysisSettingsPayload:
        def _apply(_previous: list[Car]) -> bool:
            car = self._find_car(self._active_car_id)
            if car is None:
                raise ValueError("No active car configured")
            idx = next(i for i, current in enumerate(self._cars) if current.id == car.id)
            self._cars[idx] = Car(
                id=car.id,
                name=car.name,
                car_type=car.car_type,
                aspects={**car.aspects, **AnalysisSettingsSnapshot.sanitize(aspects)},
                variant=car.variant,
            )
            return True

        return self._update_with_rollback(
            snapshot=lambda: list(self._cars),
            apply=_apply,
            restore=lambda previous: setattr(self, "_cars", previous),
            after_persist=self._sync_analysis_settings,
            result=lambda: self.active_car_aspects() or {},
        )

    def delete_car(self, car_id: str) -> CarsSnapshot:
        def _apply(_previous: tuple[list[Car], str | None]) -> bool:
            car = self._find_car(car_id)
            if car is None:
                raise ValueError(f"Unknown car id: {car_id}")
            if len(self._cars) <= 1:
                raise ValueError("Cannot delete the last car")
            self._cars = [current for current in self._cars if current.id != car_id]
            if self._active_car_id == car_id:
                self._active_car_id = self._cars[0].id if self._cars else None
            return True

        def _restore(previous: tuple[list[Car], str | None]) -> None:
            self._cars = previous[0]
            self._active_car_id = previous[1]

        return self._update_with_rollback(
            snapshot=lambda: (list(self._cars), self._active_car_id),
            apply=_apply,
            restore=_restore,
            after_persist=self._sync_analysis_settings,
            result=self._cars_snapshot_unlocked,
        )
