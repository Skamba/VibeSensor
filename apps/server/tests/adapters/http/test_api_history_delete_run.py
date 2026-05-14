from __future__ import annotations

from dataclasses import dataclass

from _history_endpoint_helpers import (
    FakeHistoryDB,
    FakeState,
    FakeWsHub,
    make_app_and_state,
    make_app_from_state,
    make_metadata,
    sample,
)
from fastapi.testclient import TestClient

from vibesensor.adapters.analysis_summary import summarize_run_data


def test_delete_active_run_returns_409() -> None:
    @dataclass
    class ActiveDB(FakeHistoryDB):
        async def aget_active_run_id(self) -> str | None:
            return "run-1"

        async def adelete_run_if_safe(self, run_id: str) -> tuple[bool, str | None]:
            if run_id == "run-1":
                return False, "active"
            return False, "not_found"

    metadata = make_metadata()
    samples = [sample(i) for i in range(5)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    app = make_app_from_state(FakeState(ActiveDB(metadata, samples, analysis), FakeWsHub()))

    with TestClient(app) as client:
        response = client.delete("/api/history/run-1")

    assert response.status_code == 409


def test_delete_analyzing_run_returns_409() -> None:
    @dataclass
    class AnalyzingDB(FakeHistoryDB):
        async def adelete_run_if_safe(self, run_id: str) -> tuple[bool, str | None]:
            if run_id == "run-1":
                return False, "analyzing"
            return False, "not_found"

        async def adelete_run(self, run_id: str) -> bool:
            raise AssertionError("delete_run should not be called for analyzing run")

    metadata = make_metadata()
    samples = [sample(i) for i in range(5)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    app = make_app_from_state(FakeState(AnalyzingDB(metadata, samples, analysis), FakeWsHub()))

    with TestClient(app) as client:
        response = client.delete("/api/history/run-1")

    assert response.status_code == 409


def test_delete_run_returns_404_for_not_found_reason() -> None:
    app, _ = make_app_and_state(language="en")

    with TestClient(app) as client:
        response = client.delete("/api/history/missing-run")

    assert response.status_code == 404


def test_delete_run_returns_generic_409_for_unknown_reason() -> None:
    @dataclass
    class LockedDB(FakeHistoryDB):
        async def adelete_run_if_safe(self, run_id: str) -> tuple[bool, str | None]:
            if run_id == "run-1":
                return False, "locked"
            return False, "not_found"

    metadata = make_metadata()
    samples = [sample(i) for i in range(5)]
    analysis = summarize_run_data(metadata, samples, lang="en", include_samples=False)
    app = make_app_from_state(FakeState(LockedDB(metadata, samples, analysis), FakeWsHub()))

    with TestClient(app) as client:
        response = client.delete("/api/history/run-1")

    assert response.status_code == 409
    assert response.json()["detail"] == "Cannot delete run at this time"
