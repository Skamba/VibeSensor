"""Tests for converting run-suitability checks to and from boundary payloads."""

from __future__ import annotations

from vibesensor.domain.run_suitability import RunSuitability, SuitabilityCheck
from vibesensor.recording.run_suitability_codec import (
    run_suitability_from_payload,
    run_suitability_payload,
)
from vibesensor.report.i18n import tr
from vibesensor.report.run_quality import suitability_check_detail


def test_run_suitability_from_payload_uses_canonical_check_key() -> None:
    suitability = run_suitability_from_payload(
        [
            {"check_key": "speed_profile", "state": "warn"},
            "ignore-me",
        ]
    )

    assert suitability.checks == (SuitabilityCheck(check_key="speed_profile", state="warn"),)


def test_run_suitability_from_payload_recovers_numeric_details_from_i18n_explanation() -> None:
    suitability = run_suitability_from_payload(
        [
            {
                "check_key": "SUITABILITY_CHECK_FRAME_INTEGRITY",
                "state": "warn",
                "explanation": {
                    "_i18n_key": "SUITABILITY_FRAME_INTEGRITY_WARN",
                    "total_dropped": "4",
                    "total_overflow": 7,
                },
            }
        ]
    )

    assert suitability.checks == (
        SuitabilityCheck(
            check_key="SUITABILITY_CHECK_FRAME_INTEGRITY",
            state="warn",
            details=(("total_dropped", 4), ("total_overflow", 7)),
        ),
    )


def test_run_suitability_payload_projects_domain_checks() -> None:
    suitability = RunSuitability(
        checks=(
            SuitabilityCheck(check_key="speed_profile", state="warn"),
            SuitabilityCheck(check_key="SUITABILITY_CHECK_RUN_DURATION", state="warn"),
            SuitabilityCheck(check_key="steady_cruise", state="pass"),
        )
    )

    payload = run_suitability_payload(suitability)

    assert payload[0]["check_key"] == "speed_profile"
    assert payload[0]["state"] == "warn"
    assert "explanation" in payload[0]
    assert payload[1]["check_key"] == "SUITABILITY_CHECK_RUN_DURATION"
    assert payload[1]["explanation"] == {"_i18n_key": "SUITABILITY_RUN_DURATION_WARNING"}
    assert payload[2]["check_key"] == "steady_cruise"


def test_run_suitability_payload_uses_summary_row_duration_details() -> None:
    suitability = RunSuitability(
        checks=(
            SuitabilityCheck(
                check_key="SUITABILITY_CHECK_RUN_DURATION",
                state="warn",
                details=(("summary_rows", 1), ("required_summary_rows", 2)),
            ),
        )
    )

    payload = run_suitability_payload(suitability)

    assert payload == [
        {
            "check_key": "SUITABILITY_CHECK_RUN_DURATION",
            "state": "warn",
            "explanation": {
                "_i18n_key": "SUITABILITY_SUMMARY_ROW_COUNT_WARNING",
                "summary_rows": 1,
                "required_summary_rows": 2,
            },
        }
    ]


def test_run_suitability_payload_uses_raw_sample_duration_details() -> None:
    suitability = RunSuitability(
        checks=(
            SuitabilityCheck(
                check_key="SUITABILITY_CHECK_RUN_DURATION",
                state="warn",
                details=(("raw_samples", 160), ("required_raw_samples", 800)),
            ),
        )
    )

    payload = run_suitability_payload(suitability)

    assert payload == [
        {
            "check_key": "SUITABILITY_CHECK_RUN_DURATION",
            "state": "warn",
            "explanation": {
                "_i18n_key": "SUITABILITY_RAW_SAMPLE_DURATION_WARNING",
                "raw_samples": 160,
                "required_raw_samples": 800,
            },
        }
    ]


def test_run_suitability_payload_handles_none() -> None:
    assert run_suitability_payload(None) == []


def test_a_loose_mount_adds_a_warning_row_that_survives_storage() -> None:
    """Only a found loose mount adds the row: a run without one may not have been checked."""
    base = RunSuitability(checks=(SuitabilityCheck(check_key="speed_profile", state="pass"),))

    assert base.with_loose_mounts(0) is base
    stored = run_suitability_from_payload(run_suitability_payload(base.with_loose_mounts(2)))
    assert stored.checks[-1] == SuitabilityCheck(
        check_key="SUITABILITY_CHECK_SENSOR_MOUNTS", state="warn", details=(("loose_sensors", 2),)
    )
    row = run_suitability_payload(stored)[-1]
    assert [tr("en", row["check_key"]), tr("nl", row["check_key"])] == [
        "Sensor mounting",
        "Sensorbevestiging",
    ]
    assert suitability_check_detail("en", row, speed_unit="kmh") == (
        "One or more sensors moved on their mount during the drive, so the vibration measured"
        " there is less reliable."
    )
