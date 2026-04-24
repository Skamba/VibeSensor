"""Docker E2E tests for long-sim PDF report accuracy."""

from __future__ import annotations

import pytest

from tests_e2e._docker_edge_helpers import (
    _assert_no_placeholders,
    _cleanup_clients,
    _cleanup_run,
    _pdf_mentions_frequency,
    _prepare_simulator_locations,
    _simulate,
    _wait_complete,
)
from tests_e2e.e2e_helpers import (
    api_bytes,
    api_json,
    parse_export_zip,
    pdf_text,
)

pytestmark = pytest.mark.e2e


@pytest.mark.long_sim
def test_full_pdf_report_20s_accuracy_e2e(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    duration_long = float(e2e_env["sim_duration_long"])
    _cleanup_clients(base)
    _prepare_simulator_locations(e2e_env)
    run_id = str(api_json(base, "/api/recording/start", method="POST")["run_id"])
    try:
        _simulate(e2e_env, duration=duration_long, count=4)
        api_json(base, "/api/recording/stop", method="POST")
        run = _wait_complete(base, run_id)
        assert run["status"] == "complete"

        detail = api_json(base, f"/api/history/{run_id}")
        insights = api_json(base, f"/api/history/{run_id}/insights?lang=en")
        export_resp = api_bytes(base, f"/api/history/{run_id}/export")
        export_json, rows, _ = parse_export_zip(export_resp.body)
        pdf_resp = api_bytes(base, f"/api/history/{run_id}/report.pdf?lang=en")
        text = " ".join(pdf_text(pdf_resp.body).split())

        for required in (
            "vibesensor diagnostic report",
            "likely source",
            "what to do next",
            "sensor model",
            "firmware version",
            "analysis rows",
            "raw sample rate",
        ):
            assert required in text, f"missing PDF section: {required}"

        metadata = detail["metadata"]
        active_car_snapshot = metadata.get("active_car_snapshot") or {}
        car_name = str(active_car_snapshot.get("name") or "").strip().lower()
        if car_name:
            assert car_name in text
        assert run_id.lower() in text

        findings = [
            f
            for f in insights.get("findings", [])
            if not str(f.get("finding_id", "")).startswith("REF_")
        ]
        assert findings, "20s run produced no non-reference findings"
        primary = findings[0]
        primary_source = str(primary.get("suspected_source") or "").replace("/", " / ").lower()
        source_label = {
            "wheel/tire": "wheel / tire",
            "driveline": "driveline",
            "engine": "engine",
            "unknown_resonance": "unknown",
        }.get(str(primary.get("suspected_source") or "").lower(), primary_source)
        assert source_label in text or source_label.replace(" ", "") in text.replace(" ", "")

        strongest = str(primary.get("strongest_location") or "").lower().replace("-", " ")
        if strongest:
            normalized_text = text.replace(" ", "")
            strongest_token = strongest.replace(" ", "")
            assert (
                strongest in text
                or strongest_token in normalized_text
                or "unknown" in text
                or "not available" in text
            )

        top_causes = [c for c in insights.get("top_causes", []) if isinstance(c, dict)]
        assert top_causes, "20s run produced no top_causes"
        top_source = str(top_causes[0].get("suspected_source") or "").lower()
        top_source_label = {
            "wheel/tire": "wheel / tire",
            "driveline": "driveline",
            "engine": "engine",
            "unknown_resonance": "unknown",
        }.get(top_source, top_source.replace("/", " / "))
        assert top_source_label in text

        analysis = detail.get("analysis") or {}
        sensor_rows = [
            r for r in analysis.get("sensor_intensity_by_location", []) if isinstance(r, dict)
        ]
        assert sensor_rows, "sensor_intensity_by_location is empty"
        assert len(rows) == int(export_json.get("sample_count", -1)), (
            f"export row count {len(rows)} != sample_count {export_json.get('sample_count')}"
        )

        # The PDF renders frequencies from the persistence-ranked peaks_table, not
        # from the raw fft_spectrum top amplitude (which may be a transient spike).
        peaks_table = analysis.get("plots", {}).get("peaks_table", [])
        if (
            peaks_table
            and isinstance(peaks_table[0], dict)
            and "recapture before acting" not in text
        ):
            peak_hz = float(peaks_table[0].get("frequency_hz") or 0)
            assert _pdf_mentions_frequency(text, peak_hz), (
                f"PDF missing expected peaks-table top frequency {peak_hz:.2f} Hz"
            )

        _assert_no_placeholders(text)
    finally:
        api_json(base, "/api/recording/stop", method="POST")
        _cleanup_run(base, run_id)
        _cleanup_clients(base)
