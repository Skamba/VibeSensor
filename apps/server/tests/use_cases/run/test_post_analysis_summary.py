from __future__ import annotations

from types import SimpleNamespace

import pytest

from vibesensor.shared.types.run_schema import RunMetadata
from vibesensor.use_cases.run.post_analysis_summary import build_post_analysis_summary


def _run_metadata(
    run_id: str,
    *,
    language: str = "en",
    raw_sample_rate_hz: int = 800,
) -> RunMetadata:
    return RunMetadata.from_dict(
        {
            "run_id": run_id,
            "start_time_utc": "2025-01-01T00:00:00Z",
            "sensor_model": "fixture-sensor",
            "raw_sample_rate_hz": raw_sample_rate_hz,
            "sample_rate_hz": raw_sample_rate_hz,
            "feature_interval_s": 1.0,
            "language": language,
        }
    )


def test_build_post_analysis_summary_adds_analysis_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeRunAnalysis:
        def __init__(self, metadata, samples, *, lang, file_name, include_samples):
            captured["metadata"] = metadata
            captured["samples"] = samples
            captured["lang"] = lang
            captured["file_name"] = file_name
            captured["include_samples"] = include_samples

        def summarize(self):
            return SimpleNamespace(
                diagnostic_case=SimpleNamespace(case_id="case-1"),
            )

    monkeypatch.setattr(
        "vibesensor.use_cases.diagnostics.RunAnalysis",
        FakeRunAnalysis,
    )
    monkeypatch.setattr(
        "vibesensor.use_cases.run.post_analysis_summary.analysis_result_to_summary",
        lambda _result: {"run_suitability": []},
    )

    summary = build_post_analysis_summary(
        run_id="run-ok",
        metadata=_run_metadata("run-ok", language="nl", raw_sample_rate_hz=1),
        samples=[{"t_s": 1.0, "vibration_strength_db": 10.0}],
        language="nl",
        total_sample_count=3,
        stride=1,
    )

    assert captured["lang"] == "nl"
    assert captured["file_name"] == "run-ok"
    assert captured["include_samples"] is False
    assert summary["case_id"] == "case-1"
    assert summary["analysis_metadata"] == {
        "analyzed_sample_count": 1,
        "total_sample_count": 3,
        "sampling_method": "full",
    }


def test_build_post_analysis_summary_adds_stride_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRunAnalysis:
        def __init__(self, *_args, **_kwargs):
            pass

        def summarize(self):
            return SimpleNamespace(
                diagnostic_case=SimpleNamespace(case_id="case-2"),
            )

    monkeypatch.setattr(
        "vibesensor.use_cases.diagnostics.RunAnalysis",
        FakeRunAnalysis,
    )
    monkeypatch.setattr(
        "vibesensor.use_cases.run.post_analysis_summary.analysis_result_to_summary",
        lambda _result: {},
    )
    monkeypatch.setattr(
        "vibesensor.report_i18n.tr",
        lambda _language, _key, *, stride: f"stride={stride}",
    )

    summary = build_post_analysis_summary(
        run_id="run-stride",
        metadata=_run_metadata("run-stride", raw_sample_rate_hz=1),
        samples=[{"t_s": 1.0, "vibration_strength_db": 10.0}],
        language="en",
        total_sample_count=5,
        stride=3,
    )

    run_suitability = summary["run_suitability"]
    assert isinstance(run_suitability, list)
    assert run_suitability == [
        {
            "check_key": "SUITABILITY_CHECK_ANALYSIS_SAMPLING",
            "check": "SUITABILITY_CHECK_ANALYSIS_SAMPLING",
            "state": "warn",
            "explanation": "stride=3",
        }
    ]


def test_build_post_analysis_summary_adds_short_run_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRunAnalysis:
        def __init__(self, *_args, **_kwargs):
            pass

        def summarize(self):
            return SimpleNamespace(
                diagnostic_case=SimpleNamespace(case_id="case-3"),
            )

    monkeypatch.setattr(
        "vibesensor.use_cases.diagnostics.RunAnalysis",
        FakeRunAnalysis,
    )
    monkeypatch.setattr(
        "vibesensor.use_cases.run.post_analysis_summary.analysis_result_to_summary",
        lambda _result: {},
    )
    monkeypatch.setattr(
        "vibesensor.report_i18n.tr",
        lambda _language, key, **_kwargs: key,
    )

    summary = build_post_analysis_summary(
        run_id="run-short",
        metadata=_run_metadata("run-short", raw_sample_rate_hz=800),
        samples=[{"t_s": 1.0, "vibration_strength_db": 10.0}],
        language="en",
        total_sample_count=100,
        stride=1,
    )

    assert summary["run_suitability"] == [
        {
            "check_key": "SUITABILITY_CHECK_RUN_DURATION",
            "check": "SUITABILITY_CHECK_RUN_DURATION",
            "state": "warn",
            "explanation": "SUITABILITY_RUN_DURATION_WARNING",
        }
    ]
