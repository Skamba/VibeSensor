# ruff: noqa: E402
from __future__ import annotations

"""Runtime regressions spanning API, history, and processing boundaries."""


import re
from pathlib import Path

import pytest
from _paths import SERVER_ROOT

from vibesensor.adapters.http.routes._helpers import safe_filename as _safe_filename
from vibesensor.adapters.persistence.history_db import HistoryDB
from vibesensor.infra.processing import SignalProcessor

_SAFE_RE = re.compile(r"^[a-zA-Z0-9._-]+$")

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
    def _make_db(tmp_path: Path) -> HistoryDB:
        db = HistoryDB(tmp_path / "history.db")
        db.create_run("run-1", "2026-01-01T00:00:00Z", {"source": "test"})
        return db

    def test_rejects_non_dict_analysis(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        with db._cursor() as cur:
            cur.execute(
                "UPDATE runs SET status='complete', analysis_json=? WHERE run_id=?",
                ("[1,2,3]", "run-1"),
            )
        run = db.get_run("run-1")
        assert run is not None
        assert "analysis" not in run

    def test_accepts_dict_analysis(self, tmp_path: Path) -> None:
        db = self._make_db(tmp_path)
        db.store_analysis("run-1", {"findings": []})
        run = db.get_run("run-1")
        assert run is not None
        assert isinstance(run.get("analysis"), dict)


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


# --- Bug 10: location_code stripped before registry -----------------------


def test_set_location_uses_stripped_code() -> None:
    """Verify the stripped code is passed to registry.set_location."""
    source = (SERVER_ROOT / "vibesensor" / "routes" / "clients.py").read_text()
    assert "set_location(normalized_client_id, code)" in source
    assert "set_location(normalized_client_id, req.location_code)" not in source
