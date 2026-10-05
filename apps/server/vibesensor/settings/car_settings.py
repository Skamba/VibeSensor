"""Car profile CRUD extracted into an explicit collaborator."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from threading import RLock
from typing import Protocol, TypeVar

from vibesensor.domain.car import Car, CarOrderReferenceStatus, CarSnapshot
from vibesensor.settings.analysis_settings_schema import sanitize_analysis_settings
from vibesensor.settings.car_config import (
    CarConfigUpdatePayload,
    CarsSnapshot,
    car_from_persistence_dict,
    car_order_reference_status_from_mapping,
    car_to_persistence_dict,
    drive_layout_or_none,
    final_drive_axle_or_none,
    fuel_type_or_none,
    new_car_id,
)
from vibesensor.settings.settings_transaction import log_settings_change
from vibesensor.settings.settings_types import (
    AnalysisSettingsPayload,
    analysis_settings_payload_from_mapping,
)

LOGGER = logging.getLogger(__name__)
_CarSettingsSnapshotT = TypeVar("_CarSettingsSnapshotT")
_CarSettingsResultT = TypeVar("_CarSettingsResultT")
_ORDER_REFERENCE_ASPECT_KEYS = frozenset({"current_gear_ratio", "final_drive_ratio"})
_FLAT_TIRE_ASPECT_KEYS = frozenset({"tire_width_mm", "tire_aspect_pct", "rim_in"})
_AXLE_TIRE_ASPECT_KEYS = frozenset(
    {
        "front_tire_width_mm",
        "front_tire_aspect_pct",
        "front_rim_in",
        "rear_tire_width_mm",
        "rear_tire_aspect_pct",
        "rear_rim_in",
        "default_axle_for_speed",
    }
)
_TIRE_REFERENCE_ASPECT_KEYS = _FLAT_TIRE_ASPECT_KEYS | _AXLE_TIRE_ASPECT_KEYS


class _UpdateWithRollback(Protocol):
    def __call__(
        self,
        *,
        snapshot: Callable[[], _CarSettingsSnapshotT],
        apply: Callable[[_CarSettingsSnapshotT], bool],
        restore: Callable[[_CarSettingsSnapshotT], None],
        audit_log: Callable[[_CarSettingsSnapshotT], None] | None = None,
        after_persist: Callable[[], None] | None = None,
        result: Callable[[], _CarSettingsResultT],
    ) -> _CarSettingsResultT: ...


@dataclass(slots=True)
class CarSettingsState:
    """Mutable car-selection state shared by focused persisted settings services."""

    cars: list[Car] = field(default_factory=list)
    active_car_id: str | None = None


def _clamp_str(value: object, maxlen: int) -> str:
    """Strip and truncate *value* to *maxlen* characters."""
    return str(value).strip()[:maxlen]


def _car_payload(car: Car | None) -> dict[str, object] | None:
    if car is None:
        return None
    return dict(car_to_persistence_dict(car))


class CarSettingsService:
    """Persisted car-profile CRUD collaborator backed by the shared snapshot coordinator."""

    __slots__ = ("_lock", "_state", "_update_with_rollback")

    def __init__(
        self,
        *,
        lock: RLock,
        state: CarSettingsState,
        update_with_rollback: _UpdateWithRollback,
    ) -> None:
        self._lock = lock
        self._state = state
        self._update_with_rollback = update_with_rollback

    def cars_snapshot_unlocked(self) -> CarsSnapshot:
        return CarsSnapshot(
            cars=[car_to_persistence_dict(car) for car in self._state.cars],
            active_car_id=self._state.active_car_id,
        )

    def get_cars(self) -> CarsSnapshot:
        with self._lock:
            return self.cars_snapshot_unlocked()

    def active_car_aspects(self) -> AnalysisSettingsPayload | None:
        """Return the active car's aspects as a typed analysis-settings payload."""
        with self._lock:
            car = self._find_car(self._state.active_car_id)
            if car is None:
                return None
            return analysis_settings_payload_from_mapping(car.aspects)

    def active_car_snapshot(self) -> CarSnapshot | None:
        """Return the active car profile as a typed domain snapshot."""
        with self._lock:
            car = self._find_car(self._state.active_car_id)
            if car is None:
                return None
            return CarSnapshot(
                car_id=car.id,
                name=car.name,
                car_type=car.car_type,
                variant=car.variant,
                aspects=dict(car.aspects),
                order_reference_status=car.order_reference_status,
                fuel_type=car.fuel_type,
                drive_layout=car.drive_layout,
                final_drive_axle=car.final_drive_axle,
            )

    def _find_car(self, car_id: str | None) -> Car | None:
        if not car_id:
            return None
        return next((c for c in self._state.cars if c.id == car_id), None)

    def set_active_car(self, car_id: str) -> CarsSnapshot:
        def _apply(_previous: str | None) -> bool:
            car = self._find_car(car_id)
            if car is None:
                raise ValueError(f"Unknown car id: {car_id}")
            self._state.active_car_id = car_id
            return True

        return self._update_with_rollback(
            snapshot=lambda: self._state.active_car_id,
            apply=_apply,
            restore=lambda previous: setattr(self._state, "active_car_id", previous),
            audit_log=lambda previous: log_settings_change(
                LOGGER,
                action="set_active_car",
                before=previous,
                after=self._state.active_car_id,
                car_id=car_id,
            ),
            result=self.cars_snapshot_unlocked,
        )

    def add_car(self, car_data: CarConfigUpdatePayload) -> CarsSnapshot:
        created_car_id: str | None = None

        def _apply(_previous: list[Car]) -> bool:
            nonlocal created_car_id
            payload: dict[str, object] = dict(car_data)
            created_car_id = new_car_id()
            payload["id"] = created_car_id
            self._state.cars.append(car_from_persistence_dict(payload))
            return True

        return self._update_with_rollback(
            snapshot=lambda: list(self._state.cars),
            apply=_apply,
            restore=lambda previous: setattr(self._state, "cars", previous),
            audit_log=lambda _previous: log_settings_change(
                LOGGER,
                action="add_car",
                before=None,
                after=_car_payload(self._find_car(created_car_id)),
                car_id=created_car_id,
            ),
            result=self.cars_snapshot_unlocked,
        )

    def update_car(self, car_id: str, car_data: CarConfigUpdatePayload) -> CarsSnapshot:
        def _apply(_previous: list[Car]) -> bool:
            car = self._find_car(car_id)
            if car is None:
                raise ValueError(f"Unknown car id: {car_id}")
            idx = next(i for i, current in enumerate(self._state.cars) if current.id == car_id)
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
            new_aspects: AnalysisSettingsPayload = analysis_settings_payload_from_mapping(
                car.aspects
            )
            clear_final_drive = clear_gear = False
            aspect_updates: AnalysisSettingsPayload = {}
            if "aspects" in car_data and isinstance(car_data["aspects"], dict):
                raw_aspects: Mapping[str, object] = car_data["aspects"]
                aspect_updates = sanitize_analysis_settings(raw_aspects)
                new_aspects = _merge_aspects_with_tire_setup(
                    current=new_aspects,
                    updates=aspect_updates,
                )
                # An explicit null ratio means "unknown": drop the stored value.
                clear_final_drive = _is_explicit_null(raw_aspects, "final_drive_ratio")
                clear_gear = _is_explicit_null(raw_aspects, "current_gear_ratio")
                if clear_final_drive:
                    new_aspects.pop("final_drive_ratio", None)
                if clear_gear:
                    new_aspects.pop("current_gear_ratio", None)
            new_variant = car.variant
            if "variant" in car_data:
                raw_variant = car_data["variant"]
                if isinstance(raw_variant, str) and raw_variant:
                    new_variant = _clamp_str(raw_variant, 64) or None
                else:
                    new_variant = None
            # Without an explicit status, every reference the user edited becomes
            # user-confirmed; the untouched ones keep their provenance.
            new_order_reference_status = _updated_order_reference_status(
                car.order_reference_status, aspect_updates
            )
            if "order_reference_status" in car_data:
                raw_order_reference_status = car_data["order_reference_status"]
                if isinstance(raw_order_reference_status, Mapping):
                    new_order_reference_status = car_order_reference_status_from_mapping(
                        raw_order_reference_status
                    )
            new_fuel_type = fuel_type_or_none(car_data.get("fuel_type")) or car.fuel_type
            new_drive_layout = (
                drive_layout_or_none(car_data.get("drive_layout")) or car.drive_layout
            )
            # An AWD car's final-drive axle comes from its library row: it holds
            # only while the layout and the final drive it describes are kept.
            new_final_drive_axle = final_drive_axle_or_none(car_data.get("final_drive_axle"))
            if (
                new_final_drive_axle is None
                and new_drive_layout == car.drive_layout
                and "final_drive_ratio" not in aspect_updates
                and not clear_final_drive
            ):
                new_final_drive_axle = car.final_drive_axle
            if new_order_reference_status is not None and (clear_final_drive or clear_gear):
                status = new_order_reference_status
                new_order_reference_status = replace(
                    status,
                    final_drive_ratio_confidence=(
                        None if clear_final_drive else status.final_drive_ratio_confidence
                    ),
                    current_gear_ratio_confidence=(
                        None if clear_gear else status.current_gear_ratio_confidence
                    ),
                )
            self._state.cars[idx] = Car(
                id=car.id,
                name=new_name,
                car_type=new_car_type,
                aspects=new_aspects,
                variant=new_variant,
                order_reference_status=new_order_reference_status,
                fuel_type=new_fuel_type,
                drive_layout=new_drive_layout,
                final_drive_axle=new_final_drive_axle,
            )
            return True

        return self._update_with_rollback(
            snapshot=lambda: list(self._state.cars),
            apply=_apply,
            restore=lambda previous: setattr(self._state, "cars", previous),
            audit_log=lambda previous: log_settings_change(
                LOGGER,
                action="update_car",
                before=_car_payload(next((car for car in previous if car.id == car_id), None)),
                after=_car_payload(self._find_car(car_id)),
                car_id=car_id,
            ),
            result=self.cars_snapshot_unlocked,
        )

    def update_active_car_aspects(
        self,
        aspects: AnalysisSettingsPayload,
    ) -> AnalysisSettingsPayload:
        def _apply(_previous: list[Car]) -> bool:
            car = self._find_car(self._state.active_car_id)
            if car is None:
                raise ValueError("No active car configured")
            idx = next(i for i, current in enumerate(self._state.cars) if current.id == car.id)
            self._state.cars[idx] = Car(
                id=car.id,
                name=car.name,
                car_type=car.car_type,
                aspects=_merge_aspects_with_tire_setup(
                    current=car.aspects,
                    updates=sanitize_analysis_settings(aspects),
                ),
                variant=car.variant,
                order_reference_status=_updated_order_reference_status(
                    car.order_reference_status,
                    aspects,
                ),
                fuel_type=car.fuel_type,
                drive_layout=car.drive_layout,
                final_drive_axle=car.final_drive_axle,
            )
            return True

        def _result() -> AnalysisSettingsPayload:
            active_aspects = self.active_car_aspects()
            if active_aspects is not None:
                return active_aspects
            return {}

        return self._update_with_rollback(
            snapshot=lambda: list(self._state.cars),
            apply=_apply,
            restore=lambda previous: setattr(self._state, "cars", previous),
            audit_log=lambda previous: log_settings_change(
                LOGGER,
                action="update_active_car_aspects",
                before=next(
                    (dict(car.aspects) for car in previous if car.id == self._state.active_car_id),
                    None,
                ),
                after=self.active_car_aspects(),
                car_id=self._state.active_car_id,
            ),
            result=_result,
        )

    def delete_car(self, car_id: str) -> CarsSnapshot:
        def _apply(_previous: tuple[list[Car], str | None]) -> bool:
            car = self._find_car(car_id)
            if car is None:
                raise ValueError(f"Unknown car id: {car_id}")
            if len(self._state.cars) <= 1:
                raise ValueError("Cannot delete the last car")
            self._state.cars = [current for current in self._state.cars if current.id != car_id]
            if self._state.active_car_id == car_id:
                self._state.active_car_id = self._state.cars[0].id if self._state.cars else None
            return True

        def _restore(previous: tuple[list[Car], str | None]) -> None:
            self._state.cars = previous[0]
            self._state.active_car_id = previous[1]

        return self._update_with_rollback(
            snapshot=lambda: (list(self._state.cars), self._state.active_car_id),
            apply=_apply,
            restore=_restore,
            audit_log=lambda previous: log_settings_change(
                LOGGER,
                action="delete_car",
                before=_car_payload(next((car for car in previous[0] if car.id == car_id), None)),
                after=None,
                car_id=car_id,
                active_car_id=self._state.active_car_id,
            ),
            result=self.cars_snapshot_unlocked,
        )


def _is_explicit_null(values: Mapping[str, object], key: str) -> bool:
    return key in values and values[key] is None


def _updated_order_reference_status(
    existing: CarOrderReferenceStatus | None,
    aspects: AnalysisSettingsPayload,
) -> CarOrderReferenceStatus | None:
    touched_keys = _ORDER_REFERENCE_ASPECT_KEYS.intersection(aspects)
    touched_tire_keys = _TIRE_REFERENCE_ASPECT_KEYS.intersection(aspects)
    if not touched_keys and not touched_tire_keys:
        return existing
    if existing is None:
        return CarOrderReferenceStatus(
            selection_source_status="manual_entry",
            tire_dimensions_confidence="user_confirmed" if touched_tire_keys else None,
            current_gear_ratio_confidence=(
                "user_confirmed" if "current_gear_ratio" in touched_keys else None
            ),
            final_drive_ratio_confidence=(
                "user_confirmed" if "final_drive_ratio" in touched_keys else None
            ),
        )
    return existing.with_user_confirmed_fields(
        tire_dimensions=bool(touched_tire_keys),
        current_gear_ratio="current_gear_ratio" in touched_keys,
        final_drive_ratio="final_drive_ratio" in touched_keys,
    )


def _merge_aspects_with_tire_setup(
    *,
    current: Mapping[str, object],
    updates: Mapping[str, object],
) -> AnalysisSettingsPayload:
    merged = analysis_settings_payload_from_mapping(current)
    if _FLAT_TIRE_ASPECT_KEYS.intersection(updates) and not _AXLE_TIRE_ASPECT_KEYS.intersection(
        updates
    ):
        merged.pop("front_tire_width_mm", None)
        merged.pop("front_tire_aspect_pct", None)
        merged.pop("front_rim_in", None)
        merged.pop("rear_tire_width_mm", None)
        merged.pop("rear_tire_aspect_pct", None)
        merged.pop("rear_rim_in", None)
        merged.pop("default_axle_for_speed", None)
    merged.update(analysis_settings_payload_from_mapping(updates))
    return merged
