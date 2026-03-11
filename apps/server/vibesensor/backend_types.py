"""Shared typed contracts for backend settings, history, and status boundaries."""

from __future__ import annotations

from typing import Literal, NotRequired, TypeAlias

from typing_extensions import TypedDict

from .json_types import JsonObject

AnalysisSettingsPayload: TypeAlias = dict[str, float]
LanguageCode: TypeAlias = Literal["en", "nl"]
SpeedUnitCode: TypeAlias = Literal["kmh", "mps"]
SpeedSourceKind: TypeAlias = Literal["gps", "obd2", "manual"]
FallbackMode: TypeAlias = Literal["manual"]
ResolvedSpeedSource: TypeAlias = Literal["gps", "manual", "fallback_manual", "none"]


class CarConfigUpdatePayload(TypedDict, total=False):
    id: str
    name: str
    type: str
    aspects: AnalysisSettingsPayload
    variant: str


class CarConfigPayload(TypedDict):
    id: str
    name: str
    type: str
    aspects: AnalysisSettingsPayload
    variant: NotRequired[str]


class CarsPayload(TypedDict):
    cars: list[CarConfigPayload]
    activeCarId: str | None


class SensorConfigPayload(TypedDict):
    name: str
    location: str


class SensorConfigUpdatePayload(TypedDict, total=False):
    name: str
    location: str


SensorsByMacPayload: TypeAlias = dict[str, SensorConfigPayload]


class SpeedSourceUpdatePayload(TypedDict, total=False):
    speedSource: SpeedSourceKind
    manualSpeedKph: float | None
    obd2Config: JsonObject
    staleTimeoutS: float
    fallbackMode: FallbackMode


class SpeedSourcePayload(TypedDict):
    speedSource: SpeedSourceKind
    manualSpeedKph: float | None
    obd2Config: JsonObject
    staleTimeoutS: float
    fallbackMode: FallbackMode


class SettingsSnapshotPayload(SpeedSourcePayload):
    cars: list[CarConfigPayload]
    activeCarId: str | None
    language: LanguageCode
    speedUnit: SpeedUnitCode
    sensorsByMac: SensorsByMacPayload


class HistoryRunListEntryPayload(TypedDict, total=False):
    run_id: str
    status: str
    start_time_utc: str
    end_time_utc: str | None
    created_at: str
    sample_count: int
    error_message: str
    analysis_version: int


class HistoryRunPayload(TypedDict, total=False):
    run_id: str
    status: str
    start_time_utc: str
    end_time_utc: str | None
    metadata: JsonObject
    analysis: JsonObject
    analysis_corrupt: bool
    error_message: str
    created_at: str
    sample_count: int
    analysis_version: int
    analysis_started_at: str
    analysis_completed_at: str
