from __future__ import annotations

from _history_endpoint_helpers import make_app_and_state, make_metadata, sample
from fastapi.testclient import TestClient

from vibesensor.adapters.analysis_summary import summarize_run_data


def test_history_list_includes_recorded_car_name() -> None:
    metadata = make_metadata(active_car_snapshot={"name": "Track Car"})
    samples = [sample(i) for i in range(3)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    app, _ = make_app_and_state(
        language="en", metadata=metadata, samples=samples, analysis=analysis
    )

    with TestClient(app) as client:
        response = client.get("/api/history")

    assert response.json()["runs"][0]["car_name"] == "Track Car"


def test_history_list_includes_degraded_raw_capture_finalize_state() -> None:
    metadata = make_metadata(
        raw_capture_finalize={
            "status": "timeout",
            "queue_depth": 4,
            "error_summary": "raw capture finalize timed out",
        }
    )
    samples = [sample(i) for i in range(3)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    app, _ = make_app_and_state(
        language="en", metadata=metadata, samples=samples, analysis=analysis
    )

    with TestClient(app) as client:
        payload = client.get("/api/history").json()

    run = payload["runs"][0]
    assert run["lifecycle"] == {
        "stage": "post_analysis_ready",
        "raw_capture": "degraded",
        "whole_run_artifacts": "not_recorded",
        "post_analysis": "ready",
        "report": "ready",
    }
    assert run["artifact_availability"]["raw_capture"] == "degraded"
    assert run["raw_capture_finalize"] == {
        "status": "timeout",
        "queue_depth": 4,
        "error_summary": "raw capture finalize timed out",
    }


def test_history_list_uses_nested_active_car_snapshot_name() -> None:
    metadata = make_metadata(
        active_car_snapshot={
            "id": "car-1",
            "name": "Nested Track Car",
            "type": "coupe",
        }
    )
    samples = [sample(i) for i in range(3)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    app, _ = make_app_and_state(
        language="en", metadata=metadata, samples=samples, analysis=analysis
    )

    with TestClient(app) as client:
        payload = client.get("/api/history").json()

    assert payload["runs"][0]["car_name"] == "Nested Track Car"
