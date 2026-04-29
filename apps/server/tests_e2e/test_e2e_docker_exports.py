"""Docker E2E tests for export consistency edge cases."""

from __future__ import annotations

from datetime import datetime

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


def test_export_history_consistency_e2e(e2e_env: dict[str, str]) -> None:
    base = e2e_env["base_url"]
    run_id = str(api_json(base, "/api/recording/start", method="POST")["run_id"])
    try:
        _simulate(e2e_env, duration=3.0)
        api_json(base, "/api/recording/stop", method="POST")
        detail = _wait_complete(base, run_id)
        summary_rows = api_json(base, "/api/history")["runs"]
        summary = next(item for item in summary_rows if str(item["run_id"]) == run_id)

        export_resp = wait_export_ready(base, run_id)
        assert str(export_resp.headers.get("content-type", "")).startswith("application/zip")
        assert f"{run_id}.zip" in str(export_resp.headers.get("content-disposition", ""))

        export_json, rows, names = parse_export_zip(export_resp.body)
        assert names == {f"{run_id}.json", f"{run_id}_raw.csv"}
        assert str(export_json.get("run_id")) == run_id
        assert int(export_json.get("sample_count", -1)) == len(rows)
        assert int(summary.get("sample_count", -1)) == len(rows)
        assert int(detail.get("sample_count", -1)) == len(rows)

        assert rows, "export contains no rows"
        expected_columns = {"timestamp_utc", "t_s", "client_id", "speed_kmh"}
        assert expected_columns.issubset(set(rows[0].keys())), (
            f"missing columns: {expected_columns - set(rows[0].keys())}"
        )

        parsed = []
        for row in rows:
            ts = str(row["timestamp_utc"]).replace("Z", "+00:00")
            parsed.append(datetime.fromisoformat(ts))
        assert all(parsed[i] <= parsed[i + 1] for i in range(len(parsed) - 1)), (
            "export timestamps are not sorted chronologically"
        )
    finally:
        api_json(base, "/api/recording/stop", method="POST")
        _cleanup_run(base, run_id)
