"""Runtime regressions spanning API, history, and processing boundaries."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from test_support.history_db_async import execute_statements
from test_support.persisted_analysis import make_persisted_analysis

from vibesensor.adapters.http._helpers import safe_filename as _safe_filename
from vibesensor.adapters.persistence.history_db import (
    HistoryPersistenceAdapters,
    create_history_persistence_adapters,
)
from vibesensor.infra.processing import SignalProcessor
from vibesensor.shared.boundaries.runs.metadata import run_metadata_from_mapping
from vibesensor.shared.types.run_schema import RunMetadata

_SAFE_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


def _metadata(run_id: str = "run-1", **overrides: object) -> RunMetadata:
    payload: dict[str, object] = {
        "run_id": run_id,
        "start_time_utc": "2026-01-01T00:00:00Z",
        "sensor_model": "ADXL345",
        "raw_sample_rate_hz": 800,
        "feature_interval_s": 1.0,
        "source": "test",
    }
    payload.update(overrides)
    return run_metadata_from_mapping(payload)


# --- Bug 1 & 2: Content-Disposition / zip filename sanitisation -----------


class TestSafeFilename:
    """Ensure _safe_filename strips dangerous characters for HTTP headers."""

    def test_normal_run_id_unchanged(self) -> None:
        assert _safe_filename("run-2026-01-15_12-30") == "run-2026-01-15_12-30"

    @pytest.mark.parametrize(
        ("raw", "forbidden"),
        [
            ('run"injected', ['"']),
            ("run\r\nX-Injected: yes", ["\r", "\n"]),
            ("../../etc/passwd", ["/", "\\"]),
        ],
        ids=["double-quotes", "crlf", "path-separators"],
    )
    def test_dangerous_chars_stripped(self, raw: str, forbidden: list[str]) -> None:
        result = _safe_filename(raw)
        for ch in forbidden:
            assert ch not in result

    def test_empty_input_returns_download(self) -> None:
        assert _safe_filename("") == "download"

    def test_only_special_chars_returns_underscores(self) -> None:
        result = _safe_filename('""///')
        assert result  # non-empty
        assert '"' not in result
        assert "/" not in result

    def test_long_input_truncated(self) -> None:
        assert len(_safe_filename("a" * 300)) <= 200

    @pytest.mark.parametrize("raw", ["normal-run", "run 123", "run<script>", "run;echo hi"])
    def test_result_matches_safe_pattern(self, raw: str) -> None:
        result = _safe_filename(raw)
        assert _SAFE_RE.match(result), f"Unsafe chars in result: {result!r}"


# --- Bug 3: history_db analysis type validation ---------------------------


class TestHistoryDBAnalysisValidation:
    """Analysis stored in history must be type-checked as dict."""

    @staticmethod
    def _make_db(tmp_path: Path) -> HistoryPersistenceAdapters:
        db = create_history_persistence_adapters(tmp_path / "history.db")
        db.run_repository.create_run("run-1", "2026-01-01T00:00:00Z", _metadata())
        return db

    def test_rejects_non_dict_analysis(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        execute_statements(
            db.lifecycle,
            (
                "UPDATE runs SET status='complete', analysis_json=? WHERE run_id=?",
                ("[1,2,3]", "run-1"),
            ),
        )
        run = db.run_repository.get_run("run-1")
        assert run is not None
        assert run.analysis is None
        assert run.analysis_corrupt is True

    def test_accepts_dict_analysis(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        db.run_repository.store_analysis("run-1", make_persisted_analysis({"findings": []}))
        run = db.run_repository.get_run("run-1")
        assert run is not None
        assert run.analysis is not None


# --- Bug 9: Division by zero when sample_rate_hz == 0 --------------------


class TestProcessingZeroSampleRate:
    """Processing must not crash when sample_rate_hz is zero."""

    def _make_processor(self, sr: int) -> SignalProcessor:
        return SignalProcessor(
            sample_rate_hz=sr,
            waveform_seconds=4,
            waveform_display_hz=100,
            fft_n=256,
            spectrum_max_hz=200,
        )

    @pytest.mark.parametrize(
        ("sr", "expect_empty"),
        [(0, True), (800, False)],
        ids=["zero", "normal"],
    )
    def test_fft_params(self, sr: int, *, expect_empty: bool) -> None:
        proc = self._make_processor(800)
        freq_slice, valid_idx = proc._metrics.fft_params(sr)
        if expect_empty:
            assert len(freq_slice) == 0
            assert len(valid_idx) == 0
        else:
            assert len(freq_slice) > 0
            assert len(valid_idx) > 0
