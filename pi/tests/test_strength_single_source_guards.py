from __future__ import annotations

from pathlib import Path


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# Lightweight smoke tests: string guards intentionally enforce "no local reimplementation" patterns.
def test_live_diagnostics_avoids_strength_formula_reimplementation() -> None:
    text = _read(Path(__file__).resolve().parents[1] / "vibesensor" / "live_diagnostics.py")
    assert "strength_db_above_floor(" not in text
    assert "compute_floor_rms(" not in text
    assert "compute_band_rms(" not in text


def test_report_analysis_uses_shared_strength_math() -> None:
    text = _read(Path(__file__).resolve().parents[1] / "vibesensor" / "report_analysis.py")
    assert "Math.log10" not in text
    assert "20.0 * log10(" not in text
    assert "bucket_for_strength(" not in text


def test_client_assets_do_not_compute_strength_metrics() -> None:
    text = _read(Path(__file__).resolve().parents[1] / "public" / "app.js")
    assert "Math.log10(" not in text
    assert "severityFromPeak(" not in text
    assert "detectVibrationEvents(" not in text
    assert "s.x[j] * s.x[j]" not in text
