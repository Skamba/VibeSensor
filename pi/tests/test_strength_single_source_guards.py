from __future__ import annotations

import re
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
    public_dir = Path(__file__).resolve().parents[1] / "public"
    index_text = _read(public_dir / "index.html")
    scripts = [
        match.group(1).split("?", 1)[0].lstrip("/")
        for match in re.finditer(r'<script[^>]+src="([^"]+\.js)"', index_text)
    ]
    assert scripts
    forbidden_combined_spectrum = re.compile(
        r"Math\.sqrt\(\([^)]*\+[^)]*\+[^)]*\)\s*/\s*3\)"
    )
    forbidden_bucket_threshold_compare = re.compile(
        r"[A-Za-z_$][\w$]*\s*>=\s*[A-Za-z_$][\w$]*\.min_db\s*&&\s*"
        r"[A-Za-z_$][\w$]*\s*<\s*[A-Za-z_$][\w$]*\s*&&\s*"
        r"[A-Za-z_$][\w$]*\s*>=\s*[A-Za-z_$][\w$]*\.min_amp"
    )
    for script in scripts:
        text = _read(public_dir / script)
        assert "Math.log10(" not in text
        assert "severityFromPeak(" not in text
        assert "detectVibrationEvents(" not in text
        assert forbidden_combined_spectrum.search(text) is None
        assert forbidden_bucket_threshold_compare.search(text) is None
