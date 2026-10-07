from __future__ import annotations

import pytest
from _history_endpoint_helpers import (
    make_app_and_state,
    make_app_from_state,
    make_metadata,
    make_status_app,
    sample,
)
from fastapi.testclient import TestClient
from test_support.analysis import summarize_mappings

from vibesensor.domain.car import CarSnapshot
from vibesensor.history.runs import HistoryRunService
from vibesensor.web.history_services import ProjectedHistoryRunService


@pytest.mark.parametrize(
    ("status", "analysis", "expected_status", "expected_detail"),
    [
        ("analyzing", {"status": "analyzing"}, 202, None),
        ("error", {"status": "error"}, 422, "Analysis failed"),
        ("complete", None, 422, "No analysis available for this run"),
    ],
)
def test_history_insights_status_and_analysis_errors(
    status: str,
    analysis: dict[str, object] | None,
    expected_status: int,
    expected_detail: str | None,
) -> None:
    app = make_status_app(status=status, analysis=analysis, include_error_message=False)

    with TestClient(app) as client:
        response = client.get("/api/history/run-1/insights")

    assert response.status_code == expected_status
    if expected_status == 202:
        body = response.json()
        assert body["status"] == "analyzing"
        assert body["run_id"] == "run-1"
        return
    assert response.json()["detail"] == expected_detail


def test_history_insights_does_not_mutate_db_analysis() -> None:
    app, state = make_app_and_state(language="en")
    original_analysis = state.history_db.analysis
    original_keys = set(original_analysis.keys())

    with TestClient(app) as client:
        response = client.get("/api/history/run-1/insights")

    assert response.status_code == 200
    assert set(state.history_db.analysis.keys()) == original_keys


def test_history_insights_complete_response_includes_status_and_run_id() -> None:
    metadata = make_metadata()
    samples = [sample(i) for i in range(5)]
    analysis = summarize_mappings(metadata, samples, lang="en", include_samples=False)
    analysis.pop("status", None)
    analysis.pop("run_id", None)
    app, _ = make_app_and_state(
        language="en", metadata=metadata, samples=samples, analysis=analysis
    )

    with TestClient(app) as client:
        response = client.get("/api/history/run-1/insights")

    payload = response.json()
    assert payload["status"] == "complete"
    assert payload["run_id"] == "run-1"


def test_history_insights_preserves_analysis_case_id() -> None:
    metadata = make_metadata()
    samples = [sample(i) for i in range(5)]
    analysis = summarize_mappings(metadata, samples, lang="en", include_samples=False)
    analysis["case_id"] = "case-123"
    app, _ = make_app_and_state(
        language="en", metadata=metadata, samples=samples, analysis=analysis
    )

    with TestClient(app) as client:
        payload = client.get("/api/history/run-1/insights").json()

    assert payload["case_id"] == "case-123"


def test_history_insights_localizes_and_adds_run_context_warnings() -> None:
    metadata = make_metadata(
        analysis_settings_snapshot={
            "tire_width_mm": 245.0,
            "tire_aspect_pct": 35.0,
            "rim_in": 19.0,
            "final_drive_ratio": 3.23,
            "current_gear_ratio": 0.82,
        },
        active_car_snapshot={
            "id": "car-a",
            "name": "Track Car",
            "type": "coupe",
        },
        car_name="Track Car",
        tire_width_mm=245.0,
        tire_aspect_pct=35.0,
        rim_in=19.0,
        final_drive_ratio=3.23,
        current_gear_ratio=0.82,
        incomplete_for_order_analysis=True,
    )
    samples = [sample(i) for i in range(5)]
    analysis = summarize_mappings(metadata, samples, lang="en", include_samples=False)

    app, state = make_app_and_state(
        language="en",
        metadata=metadata,
        analysis=analysis,
        samples=samples,
    )
    state.settings_store.active_car_snapshot = lambda: CarSnapshot(
        car_id="car-b",
        name="Daily Car",
        car_type="wagon",
        aspects={
            "tire_width_mm": 225.0,
            "tire_aspect_pct": 45.0,
            "rim_in": 18.0,
            "final_drive_ratio": 2.91,
            "current_gear_ratio": 0.72,
        },
    )

    with TestClient(app) as client:
        payload = client.get("/api/history/run-1/insights", params={"lang": "nl"}).json()

    warnings = [item for item in payload["warnings"] if item["applies_to"] != "run_suitability"]
    assert len(warnings) == 2
    titles = {str(item.get("title")) for item in warnings}
    assert "De referentiecontext voor ordeanalyse was onvolledig voor deze meting" in titles
    assert "Voertuigprofielinstellingen zijn na deze meting gewijzigd" in titles


_REPLAY_INCOMPLETE = {
    "code": "raw_replay_coverage_incomplete",
    "severity": "warn",
    "applies_to": "raw_replay",
    "title": {"_i18n_key": "RUN_CONTEXT_WARNING_RAW_REPLAY_INCOMPLETE_TITLE"},
}
# What the Pi's manual-speed runs with a short raw capture stored.
_PI_RUN_SUITABILITY = [
    {
        "check_key": "SUITABILITY_CHECK_SPEED_VARIATION",
        "state": "warn",
        "explanation": {"_i18n_key": "SUITABILITY_SPEED_VARIATION_MANUAL", "manual_speed": 1},
    },
    {
        "check_key": "SUITABILITY_CHECK_SENSOR_COVERAGE",
        "state": "warn",
        "explanation": {"_i18n_key": "SUITABILITY_SENSOR_COVERAGE_WARN"},
    },
    {
        "check_key": "SUITABILITY_CHECK_SATURATION_AND_OUTLIERS",
        "state": "pass",
        "explanation": {"_i18n_key": "SUITABILITY_SATURATION_PASS"},
    },
    {
        "check_key": "SUITABILITY_CHECK_FRAME_INTEGRITY",
        "state": "warn",
        "explanation": {
            "_i18n_key": "SUITABILITY_FRAME_INTEGRITY_REPLAY_WARN",
            "total_dropped": 0,
            "total_overflow": 0,
            "replay_incomplete": 1,
            "replay_partial": 152,
            "replay_missing": 0,
            "replay_gaps": 8,
            "replay_overlaps": 11,
        },
    },
]


@pytest.mark.parametrize(
    ("lang", "frame_integrity", "summaries_clause"),
    [
        (
            "en",
            "Frame integrity",
            "those moments were analyzed from the stored summaries",
        ),
        (
            "nl",
            "Frame-integriteit",
            "die momenten zijn uit de opgeslagen samenvattingen geanalyseerd",
        ),
    ],
)
def test_history_insights_lead_with_the_pdfs_run_suitability_warnings(
    lang: str, frame_integrity: str, summaries_clause: str
) -> None:
    metadata = make_metadata()
    samples = [sample(i) for i in range(5)]
    analysis = summarize_mappings(metadata, samples, lang="en", include_samples=False)
    analysis["run_suitability"] = _PI_RUN_SUITABILITY
    analysis["warnings"] = [_REPLAY_INCOMPLETE]
    app, _ = make_app_and_state(
        language="en", metadata=metadata, samples=samples, analysis=analysis
    )

    with TestClient(app) as client:
        warnings = client.get("/api/history/run-1/insights", params={"lang": lang}).json()[
            "warnings"
        ]

    assert [warning["code"] for warning in warnings] == [
        "suitability_speed_variation",
        "suitability_sensor_coverage",
        "suitability_frame_integrity",
    ]
    assert {warning["applies_to"] for warning in warnings} == {"run_suitability"}
    frame = warnings[2]
    assert frame["title"] == frame_integrity
    assert "152" in frame["detail"]
    # The replay warning says the same as the check, so it is stated once.
    text = " ".join(f"{warning['title']} {warning['detail']}" for warning in warnings)
    assert text.count(summaries_clause) == 1


def test_history_insights_word_an_evs_speed_check_for_its_motor() -> None:
    metadata = make_metadata()
    samples = [sample(i) for i in range(5)]
    analysis = summarize_mappings(metadata, samples, lang="en", include_samples=False)
    analysis["run_suitability"] = _PI_RUN_SUITABILITY
    analysis["diagnosis"]["conditions"]["fuel_type"] = "EV"
    app, _ = make_app_and_state(
        language="en", metadata=metadata, samples=samples, analysis=analysis
    )

    with TestClient(app) as client:
        warnings = client.get("/api/history/run-1/insights").json()["warnings"]

    speed = next(w for w in warnings if w["code"] == "suitability_speed_variation")
    assert speed["detail"].startswith(
        "The speed could not tell the wheel and electric-motor orders apart."
    )


@pytest.mark.parametrize(
    ("lang", "speed_unit", "ending"),
    [
        ("en", "kmh", "speed above 20\u00a0km/h."),
        ("en", "mps", "speed above 6\u00a0m/s."),
        ("nl", "kmh", "boven 20\u00a0km/u."),
        ("nl", "mps", "boven 6\u00a0m/s."),
    ],
)
def test_history_insights_name_the_speed_to_record_above_in_the_users_unit(
    lang: str, speed_unit: str, ending: str
) -> None:
    metadata = make_metadata()
    samples = [sample(i) for i in range(5)]
    analysis = summarize_mappings(metadata, samples, lang="en", include_samples=False)
    analysis["run_suitability"] = [
        {
            "check_key": "SUITABILITY_CHECK_SPEED_VARIATION",
            "state": "warn",
            "explanation": {"_i18n_key": "SUITABILITY_SPEED_VARIATION_WARN"},
        }
    ]
    _, state = make_app_and_state(metadata=metadata, samples=samples, analysis=analysis)
    state.run_service = ProjectedHistoryRunService(
        HistoryRunService(state.history_db), speed_unit=lambda: speed_unit
    )

    with TestClient(make_app_from_state(state)) as client:
        insights = client.get("/api/history/run-1/insights", params={"lang": lang}).json()

    speed = next(w for w in insights["warnings"] if w["code"] == "suitability_speed_variation")
    assert speed["detail"].endswith(ending)
    if speed_unit == "mps":
        assert "km/" not in str(insights["warnings"])
