"""Docker E2E tests for runtime settings validation and transitions."""

from __future__ import annotations

import pytest

from tests_e2e._docker_edge_helpers import (
    _cleanup_run,
    _simulate,
    _wait_complete,
)
from tests_e2e.e2e_helpers import (
    api_json,
    parse_export_zip,
    wait_export_ready,
)

pytestmark = pytest.mark.e2e


def test_speed_source_transitions_and_invalid_values(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    before = api_json(base, "/api/settings/speed-source")
    run_id = ""
    try:
        gps = api_json(
            base, "/api/settings/speed-source", method="PUT", body={"speed_source": "gps"}
        )
        assert gps["speed_source"] == "gps"

        manual = api_json(
            base,
            "/api/settings/speed-source",
            method="PUT",
            body={"speed_source": "manual", "manual_speed_kph": 77},
        )
        assert manual["speed_source"] == "manual"
        assert float(manual["manual_speed_kph"]) == pytest.approx(77.0)

        obd2 = api_json(
            base, "/api/settings/speed-source", method="PUT", body={"speed_source": "obd2"}
        )
        assert obd2["speed_source"] == "obd2"

        api_json(
            base,
            "/api/settings/speed-source",
            method="PUT",
            body={"speed_source": "manual", "manual_speed_kph": 77},
        )
        run_id = str(api_json(base, "/api/recording/start", method="POST")["run_id"])
        _simulate(e2e_env, duration=3.0)
        api_json(base, "/api/recording/stop", method="POST")
        complete = _wait_complete(base, run_id)
        assert complete["status"] == "complete"

        export_resp = wait_export_ready(base, run_id)
        _, rows, _ = parse_export_zip(export_resp.body)
        speed_values = [float(r["speed_kmh"]) for r in rows if r.get("speed_kmh") not in (None, "")]
        assert speed_values
        assert sum(1 for v in speed_values if abs(v - 77.0) <= 2.0) >= max(
            3, int(len(speed_values) * 0.75)
        )

        api_json(
            base,
            "/api/settings/speed-source",
            method="PUT",
            body={"speed_source": "invalid", "manual_speed_kph": 77},
            expected_status=422,
        )
        still_manual = api_json(base, "/api/settings/speed-source")
        assert still_manual["speed_source"] == "manual"
        assert float(still_manual["manual_speed_kph"]) == pytest.approx(77.0)
    finally:
        api_json(base, "/api/recording/stop", method="POST")
        if run_id:
            _cleanup_run(base, run_id)
        api_json(
            base,
            "/api/settings/speed-source",
            method="PUT",
            body={
                "speed_source": before["speed_source"],
                "manual_speed_kph": before["manual_speed_kph"],
            },
        )


def test_language_and_speed_unit_validation_e2e(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    language_before = api_json(base, "/api/settings/language")["language"]
    unit_before = api_json(base, "/api/settings/speed-unit")["speed_unit"]
    run_id = ""
    try:
        assert (
            api_json(base, "/api/settings/language", method="PUT", body={"language": "en"})[
                "language"
            ]
            == "en"
        )
        assert (
            api_json(base, "/api/settings/language", method="PUT", body={"language": "nl"})[
                "language"
            ]
            == "nl"
        )
        assert (
            api_json(base, "/api/settings/speed-unit", method="PUT", body={"speed_unit": "kmh"})[
                "speed_unit"
            ]
            == "kmh"
        )
        assert (
            api_json(base, "/api/settings/speed-unit", method="PUT", body={"speed_unit": "mps"})[
                "speed_unit"
            ]
            == "mps"
        )

        api_json(
            base,
            "/api/settings/language",
            method="PUT",
            body={"language": "de"},
            expected_status=422,
        )
        api_json(
            base,
            "/api/settings/speed-unit",
            method="PUT",
            body={"speed_unit": "mph"},
            expected_status=422,
        )

        run_id = str(api_json(base, "/api/recording/start", method="POST")["run_id"])
        _simulate(e2e_env, duration=3.0)
        api_json(base, "/api/recording/stop", method="POST")
        _wait_complete(base, run_id)

        insights_en = api_json(base, f"/api/history/{run_id}/insights?lang=en")
        insights_nl = api_json(base, f"/api/history/{run_id}/insights?lang=nl")
        checks_en = {str(item.get("check_key")) for item in insights_en.get("run_suitability", [])}
        checks_nl = {str(item.get("check_key")) for item in insights_nl.get("run_suitability", [])}
        # Analysis output is language-neutral: check_key contains the stable identifiers.
        assert "SUITABILITY_CHECK_SPEED_VARIATION" in checks_en
        assert "SUITABILITY_CHECK_SPEED_VARIATION" in checks_nl

        if insights_en.get("findings") and insights_nl.get("findings"):
            en_first = insights_en["findings"][0]
            nl_first = insights_nl["findings"][0]
            assert en_first.get("suspected_source") == nl_first.get("suspected_source")
            assert float(en_first.get("confidence") or 0.0) == pytest.approx(
                float(nl_first.get("confidence") or 0.0), abs=1e-6
            )
    finally:
        api_json(base, "/api/recording/stop", method="POST")
        if run_id:
            _cleanup_run(base, run_id)
        api_json(base, "/api/settings/language", method="PUT", body={"language": language_before})
        api_json(base, "/api/settings/speed-unit", method="PUT", body={"speed_unit": unit_before})
