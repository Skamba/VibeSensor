"""Regression tests for the top-10 bug fixes (PR #390)."""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from vibesensor.api import _safe_filename
from vibesensor.history_db import HistoryDB
from vibesensor.processing import SignalProcessor

# --- Bug 1 & 2: Content-Disposition / zip filename sanitisation -----------


class TestSafeFilename:
    """Ensure _safe_filename strips dangerous characters for HTTP headers."""

    def test_normal_run_id_unchanged(self) -> None:
        assert _safe_filename("run-2026-01-15_12-30") == "run-2026-01-15_12-30"

    def test_double_quotes_stripped(self) -> None:
        result = _safe_filename('run"injected')
        assert '"' not in result

    def test_crlf_stripped(self) -> None:
        result = _safe_filename("run\r\nX-Injected: yes")
        assert "\r" not in result
        assert "\n" not in result

    def test_path_separators_stripped(self) -> None:
        result = _safe_filename("../../etc/passwd")
        assert "/" not in result
        assert "\\" not in result

    def test_empty_input_returns_download(self) -> None:
        assert _safe_filename("") == "download"

    def test_only_special_chars_returns_underscores(self) -> None:
        result = _safe_filename('""///')
        assert result  # non-empty
        assert '"' not in result
        assert "/" not in result

    def test_long_input_truncated(self) -> None:
        long_name = "a" * 300
        result = _safe_filename(long_name)
        assert len(result) <= 200

    def test_result_matches_safe_pattern(self) -> None:
        safe_re = re.compile(r"^[a-zA-Z0-9._-]+$")
        for raw in ["normal-run", "run 123", "run<script>", "run;echo hi"]:
            result = _safe_filename(raw)
            assert safe_re.match(result), f"Unsafe chars in result: {result!r}"


# --- Bug 3: history_db analysis type validation ---------------------------


def test_history_db_rejects_non_dict_analysis(tmp_path: Path) -> None:
    """Analysis stored as non-dict JSON should not appear in get_run()."""
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-1", "2026-01-01T00:00:00Z", {"source": "test"})
    # Manually store a JSON list instead of a dict
    with db._cursor() as cur:
        cur.execute(
            "UPDATE runs SET status='complete', analysis_json=? WHERE run_id=?",
            ("[1,2,3]", "run-1"),
        )
    run = db.get_run("run-1")
    assert run is not None
    # The non-dict value must not appear as 'analysis'
    assert "analysis" not in run


def test_history_db_accepts_dict_analysis(tmp_path: Path) -> None:
    """A proper dict analysis should be returned."""
    db = HistoryDB(tmp_path / "history.db")
    db.create_run("run-1", "2026-01-01T00:00:00Z", {"source": "test"})
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

    def test_selected_payload_returns_empty_on_zero_sr(self) -> None:
        # Processor with sr=0 but data ingested at a valid rate
        proc = self._make_processor(0)
        raw = np.zeros((10, 3), dtype=np.int16)
        proc.ingest("c1", raw, sample_rate_hz=800)
        # Force buf.sample_rate_hz back to 0 to simulate the bug path
        buf = proc._buffers["c1"]
        buf.sample_rate_hz = 0
        result = proc.selected_payload("c1")
        # Must return without crash; waveform/spectrum/metrics empty
        assert result.get("waveform") == {} or result.get("metrics") == {}

    def test_fft_params_returns_empty_on_zero_sr(self) -> None:
        proc = self._make_processor(800)
        freq_slice, valid_idx = proc._fft_params(0)
        assert len(freq_slice) == 0
        assert len(valid_idx) == 0

    def test_fft_params_normal_sr_still_works(self) -> None:
        proc = self._make_processor(800)
        freq_slice, valid_idx = proc._fft_params(800)
        assert len(freq_slice) > 0
        assert len(valid_idx) > 0


# --- Bug 5: live_diagnostics type annotation (compile-time) ---------------


def test_live_diagnostics_entries_type_annotation() -> None:
    """The entries type should be a 4-tuple matching the actual append."""
    src_path = Path(__file__).resolve().parent.parent / "vibesensor" / "live_diagnostics.py"
    source = src_path.read_text()
    # Find the type annotation line for entries
    assert "tuple[str, str, str, list[dict[str, Any]]]" in source, (
        "entries type annotation should be a 4-tuple (client_id, label, location, peaks_raw)"
    )


# --- Bug 10: location_code stripped before registry -----------------------


def test_set_location_uses_stripped_code() -> None:
    """Verify the stripped code is passed to registry.set_location."""
    src_path = Path(__file__).resolve().parent.parent / "vibesensor" / "routes" / "clients.py"
    source = src_path.read_text()
    # The registry.set_location call should use 'code' (stripped), not
    # 'req.location_code' (raw).
    assert "set_location(normalized_client_id, code)" in source
    assert "set_location(normalized_client_id, req.location_code)" not in source
