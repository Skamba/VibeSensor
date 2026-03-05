"""Runtime fallback and error-guard regressions.

Covers strength_floor_amp_g fallback, wheel_focus_from_location,
store_analysis_error guard, and i18n formatting.
"""

from __future__ import annotations

import json

from _paths import SERVER_ROOT


class TestEvidencePeakPresentFormat:
    """Regression: EVIDENCE_PEAK_PRESENT i18n template must use .1f for dB values."""

    def test_dB_format_is_one_decimal(self) -> None:
        i18n_path = SERVER_ROOT / "data" / "report_i18n.json"
        data = json.loads(i18n_path.read_text())

        en_template = data["EVIDENCE_PEAK_PRESENT"]["en"]
        nl_template = data["EVIDENCE_PEAK_PRESENT"]["nl"]

        # Must use .1f, not .4f
        assert ".1f}" in en_template, f"Expected .1f in EN template, got: {en_template}"
        assert ".1f}" in nl_template, f"Expected .1f in NL template, got: {nl_template}"
        assert ".4f" not in en_template, "Stale .4f found in EN template"
        assert ".4f" not in nl_template, "Stale .4f found in NL template"
