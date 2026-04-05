"""Canonical boundary package for persisted run payload adapters."""

from .capture import configuration_snapshot_from_metadata, configuration_snapshot_from_run_metadata
from .car import run_car_metadata_from_mapping, run_car_metadata_to_json_object
from .log import RunData, normalize_sample_record, read_jsonl_run
from .metadata import run_metadata_from_mapping, run_metadata_to_json_object
from .projection import car_from_run_metadata, symptom_from_run_metadata
from .suitability import run_suitability_from_payload, run_suitability_payload

__all__ = [
    "RunData",
    "car_from_run_metadata",
    "configuration_snapshot_from_metadata",
    "configuration_snapshot_from_run_metadata",
    "normalize_sample_record",
    "read_jsonl_run",
    "run_car_metadata_from_mapping",
    "run_car_metadata_to_json_object",
    "run_metadata_from_mapping",
    "run_metadata_to_json_object",
    "run_suitability_from_payload",
    "run_suitability_payload",
    "symptom_from_run_metadata",
]
