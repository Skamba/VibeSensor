#!/usr/bin/env python3
"""Apply Cleo's 10 API hardening fixes and commit each one on wave1/cleo-api."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent


def run(cmd: str, cwd: Path = REPO) -> None:
    result = subprocess.run(cmd, shell=True, cwd=str(cwd))
    if result.returncode != 0:
        print(f"FAILED: {cmd}")
        sys.exit(result.returncode)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def patch(path: Path, old: str, new: str) -> None:
    content = read(path)
    if old not in content:
        print(f"ERROR: pattern not found in {path}")
        sys.exit(1)
    write(path, content.replace(old, new, 1))


def commit(files: list[str], message: str) -> None:
    run("git checkout wave1/cleo-api")
    files_str = " ".join(files)
    run(f"git add {files_str}")
    run(f'git commit -m {message!r}')


# ---------------------------------------------------------------------------
# Issue 1: AnalysisSettingsRequest missing upper bounds
# ---------------------------------------------------------------------------
api_models = REPO / "apps/server/vibesensor/api_models.py"

patch(
    api_models,
    """    tire_width_mm: float | None = Field(default=None, gt=0)
    tire_aspect_pct: float | None = Field(default=None, gt=0)
    rim_in: float | None = Field(default=None, gt=0)
    final_drive_ratio: float | None = Field(default=None, gt=0)
    current_gear_ratio: float | None = Field(default=None, gt=0)
    wheel_bandwidth_pct: float | None = Field(default=None, gt=0)
    driveshaft_bandwidth_pct: float | None = Field(default=None, gt=0)
    engine_bandwidth_pct: float | None = Field(default=None, gt=0)
    speed_uncertainty_pct: float | None = Field(default=None, ge=0)
    tire_diameter_uncertainty_pct: float | None = Field(default=None, ge=0)
    final_drive_uncertainty_pct: float | None = Field(default=None, ge=0)
    gear_uncertainty_pct: float | None = Field(default=None, ge=0)
    min_abs_band_hz: float | None = Field(default=None, ge=0)
    max_band_half_width_pct: float | None = Field(default=None, gt=0)""",
    """    tire_width_mm: float | None = Field(default=None, gt=0, le=500.0)
    tire_aspect_pct: float | None = Field(default=None, gt=0, le=90.0)
    rim_in: float | None = Field(default=None, gt=0, le=30.0)
    final_drive_ratio: float | None = Field(default=None, gt=0, le=20.0)
    current_gear_ratio: float | None = Field(default=None, gt=0, le=20.0)
    wheel_bandwidth_pct: float | None = Field(default=None, gt=0, le=100.0)
    driveshaft_bandwidth_pct: float | None = Field(default=None, gt=0, le=100.0)
    engine_bandwidth_pct: float | None = Field(default=None, gt=0, le=100.0)
    speed_uncertainty_pct: float | None = Field(default=None, ge=0, le=100.0)
    tire_diameter_uncertainty_pct: float | None = Field(default=None, ge=0, le=100.0)
    final_drive_uncertainty_pct: float | None = Field(default=None, ge=0, le=100.0)
    gear_uncertainty_pct: float | None = Field(default=None, ge=0, le=100.0)
    min_abs_band_hz: float | None = Field(default=None, ge=0, le=500.0)
    max_band_half_width_pct: float | None = Field(default=None, gt=0, le=100.0)""",
)
commit(
    ["apps/server/vibesensor/api_models.py"],
    (
        "fix(api): add upper-bound constraints to AnalysisSettingsRequest fields\n\n"
        "All analysis-settings fields only had lower bounds (gt=0 or ge=0).  The\n"
        "backend analysis_settings._BOUNDS dict already defines tight ceilings for\n"
        "every field, but these were never reflected in the Pydantic model, so\n"
        "out-of-range values (e.g. tire_width_mm=99999) passed API validation\n"
        "silently and were only caught deep in the settings layer.\n\n"
        "Mirror the backend ceilings in AnalysisSettingsRequest:\n"
        "  tire_width_mm le=500, tire_aspect_pct le=90, rim_in le=30,\n"
        "  final_drive_ratio/gear_ratio le=20, bandwidth_pcts le=100,\n"
        "  uncertainty_pcts le=100, min_abs_band_hz le=500,\n"
        "  max_band_half_width_pct le=100.\n\n"
        "Fixes issue 1."
    ),
)

# ---------------------------------------------------------------------------
# Issue 2: CarUpsertRequest.variant allows empty string
# ---------------------------------------------------------------------------
patch(
    api_models,
    "    variant: str | None = Field(default=None, max_length=64)",
    "    variant: str | None = Field(default=None, min_length=1, max_length=64)",
)
commit(
    ["apps/server/vibesensor/api_models.py"],
    (
        "fix(api): reject empty-string variant in CarUpsertRequest\n\n"
        "CarUpsertRequest.variant had max_length=64 but no min_length, allowing\n"
        'variant="" to pass Pydantic validation and store a blank variant string.\n'
        "A non-None variant must be a non-empty, meaningful label.\n\n"
        "Adds min_length=1.  Fixes issue 2."
    ),
)

# ---------------------------------------------------------------------------
# Issue 3: lang query param in history insights/PDF endpoints unbounded
# ---------------------------------------------------------------------------
history = REPO / "apps/server/vibesensor/routes/history.py"

patch(
    history,
    "        lang: str | None = Query(default=None),\n    ) -> HistoryInsightsResponse:",
    "        lang: str | None = Query(default=None, max_length=8),\n    ) -> HistoryInsightsResponse:",
)
patch(
    history,
    "        run_id: str, lang: str | None = Query(default=None)\n    ) -> Response:",
    "        run_id: str, lang: str | None = Query(default=None, max_length=8)\n    ) -> Response:",
)
commit(
    ["apps/server/vibesensor/routes/history.py"],
    (
        "fix(api): cap lang query param to 8 characters in history endpoints\n\n"
        "GET /api/history/{run_id}/insights and /report.pdf accepted an unbounded\n"
        "lang query string with no length constraint, allowing arbitrarily long\n"
        "strings to be accepted and passed into the language-resolution logic.\n\n"
        "Language codes are at most 5 chars (e.g. 'en', 'nl', 'en-US'); adding\n"
        "max_length=8 gives ample room while closing the unbounded input path.\n\n"
        "Fixes issue 3."
    ),
)

# ---------------------------------------------------------------------------
# Issue 4: GET /api/history/{run_id} leaks _-prefixed internal analysis keys
# ---------------------------------------------------------------------------
patch(
    history,
    (
        "    @router.get(\"/api/history/{run_id}\", response_model=HistoryRunResponse)\n"
        "    async def get_history_run(run_id: str) -> HistoryRunResponse:\n"
        "        return await async_require_run(state.history_db, run_id)"
    ),
    (
        "    @router.get(\"/api/history/{run_id}\", response_model=HistoryRunResponse)\n"
        "    async def get_history_run(run_id: str) -> HistoryRunResponse:\n"
        "        run = await async_require_run(state.history_db, run_id)\n"
        "        # Strip internal-only keys (prefixed with _) from the analysis block\n"
        "        # to prevent implementation details (e.g. _report_template_data)\n"
        "        # from leaking to API consumers.\n"
        "        analysis = run.get(\"analysis\")\n"
        "        if isinstance(analysis, dict):\n"
        "            run = {**run, \"analysis\": _strip_internal_fields(analysis)}\n"
        "        return run"
    ),
)
commit(
    ["apps/server/vibesensor/routes/history.py"],
    (
        "fix(api): strip internal analysis keys from GET /api/history/{run_id}\n\n"
        "GET /api/history/{run_id} returned the raw run dict from the database,\n"
        "including any _-prefixed internal keys in the analysis block (e.g.\n"
        "_report_template_data).  The /insights and /export endpoints already\n"
        "called _strip_internal_fields() but /get_history_run did not.\n\n"
        "Apply _strip_internal_fields() to the analysis block before returning,\n"
        "consistent with the other history endpoints.  Fixes issue 4."
    ),
)

# ---------------------------------------------------------------------------
# Issue 5: normalize_mac_or_400 helper + wire into sensor endpoints
# ---------------------------------------------------------------------------
helpers = REPO / "apps/server/vibesensor/routes/_helpers.py"
settings = REPO / "apps/server/vibesensor/routes/settings.py"

patch(
    helpers,
    (
        "def normalize_client_id_or_400(client_id: str) -> str:\n"
        '    """Normalize a client_id or raise HTTP 400."""\n'
        "    try:\n"
        "        return normalize_sensor_id(client_id)\n"
        "    except ValueError as exc:\n"
        '        raise HTTPException(status_code=400, detail="Invalid sensor identifier") from exc'
    ),
    (
        "def normalize_client_id_or_400(client_id: str) -> str:\n"
        '    """Normalize a client_id or raise HTTP 400."""\n'
        "    try:\n"
        "        return normalize_sensor_id(client_id)\n"
        "    except ValueError as exc:\n"
        '        raise HTTPException(status_code=400, detail="Invalid sensor identifier") from exc\n'
        "\n"
        "\n"
        "def normalize_mac_or_400(mac: str) -> str:\n"
        '    """Normalize a MAC address path parameter or raise HTTP 400 with a clear message.\n'
        "\n"
        "    Performs an early length guard before delegating to\n"
        "    :func:`normalize_sensor_id`, so that oversized or empty inputs are\n"
        "    rejected without touching the settings store.\n"
        '    """\n'
        "    if not mac or len(mac) > 64:\n"
        '        raise HTTPException(status_code=400, detail="Invalid MAC address: must be 1-64 characters")\n'
        "    try:\n"
        "        return normalize_sensor_id(mac)\n"
        "    except ValueError as exc:\n"
        '        raise HTTPException(status_code=400, detail="Invalid MAC address format") from exc'
    ),
)
patch(
    settings,
    (
        "from ..api_models import (\n"
        "    ActiveCarRequest,\n"
        "    AnalysisSettingsRequest,\n"
        "    AnalysisSettingsResponse,\n"
        "    CarsResponse,\n"
        "    CarUpsertRequest,\n"
        "    LanguageRequest,\n"
        "    LanguageResponse,\n"
        "    SensorRequest,\n"
        "    SensorsResponse,\n"
        "    SpeedSourceRequest,\n"
        "    SpeedSourceResponse,\n"
        "    SpeedSourceStatusResponse,\n"
        "    SpeedUnitRequest,\n"
        "    SpeedUnitResponse,\n"
        ")"
    ),
    (
        "from ..api_models import (\n"
        "    ActiveCarRequest,\n"
        "    AnalysisSettingsRequest,\n"
        "    AnalysisSettingsResponse,\n"
        "    CarsResponse,\n"
        "    CarUpsertRequest,\n"
        "    LanguageRequest,\n"
        "    LanguageResponse,\n"
        "    SensorRequest,\n"
        "    SensorsResponse,\n"
        "    SpeedSourceRequest,\n"
        "    SpeedSourceResponse,\n"
        "    SpeedSourceStatusResponse,\n"
        "    SpeedUnitRequest,\n"
        "    SpeedUnitResponse,\n"
        ")\n"
        "from ._helpers import normalize_mac_or_400"
    ),
)
patch(
    settings,
    (
        "    @router.post(\"/api/settings/sensors/{mac}\", response_model=SensorsResponse)\n"
        "    async def update_sensor(mac: str, req: SensorRequest) -> SensorsResponse:\n"
        "        payload = req.model_dump(exclude_none=True)\n"
        "        with _value_error_to_http():\n"
        "            await asyncio.to_thread(\n"
        "                state.settings_store.set_sensor,\n"
        "                mac,\n"
        "                payload,\n"
        "            )\n"
        "        return _sensors_response()\n"
        "\n"
        "    @router.delete(\"/api/settings/sensors/{mac}\", response_model=SensorsResponse)\n"
        "    async def delete_sensor(mac: str) -> SensorsResponse:\n"
        "        with _value_error_to_http():\n"
        "            removed = await asyncio.to_thread(state.settings_store.remove_sensor, mac)\n"
        "        if not removed:\n"
        '            raise HTTPException(status_code=404, detail="Unknown sensor MAC")\n'
        "        return _sensors_response()"
    ),
    (
        "    @router.post(\"/api/settings/sensors/{mac}\", response_model=SensorsResponse)\n"
        "    async def update_sensor(mac: str, req: SensorRequest) -> SensorsResponse:\n"
        "        normalized_mac = normalize_mac_or_400(mac)\n"
        "        payload = req.model_dump(exclude_none=True)\n"
        "        with _value_error_to_http():\n"
        "            await asyncio.to_thread(\n"
        "                state.settings_store.set_sensor,\n"
        "                normalized_mac,\n"
        "                payload,\n"
        "            )\n"
        "        return _sensors_response()\n"
        "\n"
        "    @router.delete(\"/api/settings/sensors/{mac}\", response_model=SensorsResponse)\n"
        "    async def delete_sensor(mac: str) -> SensorsResponse:\n"
        "        normalized_mac = normalize_mac_or_400(mac)\n"
        "        with _value_error_to_http():\n"
        "            removed = await asyncio.to_thread(state.settings_store.remove_sensor, normalized_mac)\n"
        "        if not removed:\n"
        '            raise HTTPException(status_code=404, detail="Unknown sensor MAC")\n'
        "        return _sensors_response()"
    ),
)
commit(
    [
        "apps/server/vibesensor/routes/_helpers.py",
        "apps/server/vibesensor/routes/settings.py",
    ],
    (
        "fix(api): validate MAC address format early in sensor settings endpoints\n\n"
        "POST /api/settings/sensors/{mac} and DELETE /api/settings/sensors/{mac}\n"
        "forwarded the raw path parameter directly to the settings store, which\n"
        "raised ValueError internally on invalid MACs.  That produced an opaque\n"
        "error message from the parser rather than a clear API error.\n\n"
        "Add normalize_mac_or_400() in routes/_helpers.py: performs a fast length\n"
        "guard (1-64 chars) then calls normalize_sensor_id(), returning a clear\n"
        "'Invalid MAC address format' 400 response on failure.  Wire it into both\n"
        "update_sensor and delete_sensor so the normalized value is used throughout.\n\n"
        "Fixes issue 5."
    ),
)

# ---------------------------------------------------------------------------
# Issue 6: debug endpoints return HTTP 200 + error body for unknown client
# ---------------------------------------------------------------------------
debug = REPO / "apps/server/vibesensor/routes/debug.py"

patch(
    debug,
    "from fastapi import APIRouter, Query",
    "from fastapi import APIRouter, HTTPException, Query",
)
patch(
    debug,
    (
        "    @router.get(\"/api/debug/spectrum/{client_id}\")\n"
        "    async def debug_spectrum(client_id: str) -> dict[str, Any]:\n"
        '        """Detailed spectrum debug info for independent verification."""\n'
        "        normalized = normalize_client_id_or_400(client_id)\n"
        "        return state.processor.debug_spectrum(normalized)\n"
        "\n"
        "    @router.get(\"/api/debug/raw-samples/{client_id}\")\n"
        "    async def debug_raw_samples(\n"
        "        client_id: str,\n"
        "        n: int = Query(default=2048, ge=1, le=6400),\n"
        "    ) -> dict[str, Any]:\n"
        '        """Raw time-domain samples in g for offline analysis."""\n'
        "        normalized = normalize_client_id_or_400(client_id)\n"
        "        return state.processor.raw_samples(normalized, n_samples=n)"
    ),
    (
        "    @router.get(\"/api/debug/spectrum/{client_id}\")\n"
        "    async def debug_spectrum(client_id: str) -> dict[str, Any]:\n"
        '        """Detailed spectrum debug info for independent verification."""\n'
        "        normalized = normalize_client_id_or_400(client_id)\n"
        "        result = state.processor.debug_spectrum(normalized)\n"
        "        if \"error\" in result:\n"
        "            raise HTTPException(status_code=404, detail=result[\"error\"])\n"
        "        return result\n"
        "\n"
        "    @router.get(\"/api/debug/raw-samples/{client_id}\")\n"
        "    async def debug_raw_samples(\n"
        "        client_id: str,\n"
        "        n: int = Query(default=2048, ge=1, le=6400),\n"
        "    ) -> dict[str, Any]:\n"
        '        """Raw time-domain samples in g for offline analysis."""\n'
        "        normalized = normalize_client_id_or_400(client_id)\n"
        "        result = state.processor.raw_samples(normalized, n_samples=n)\n"
        "        if \"error\" in result:\n"
        "            raise HTTPException(status_code=404, detail=result[\"error\"])\n"
        "        return result"
    ),
)
commit(
    ["apps/server/vibesensor/routes/debug.py"],
    (
        "fix(api): return 404 instead of 200+error body from debug spectrum endpoints\n\n"
        "GET /api/debug/spectrum/{client_id} and /debug/raw-samples/{client_id}\n"
        "returned HTTP 200 with {\"error\": \"insufficient samples\"} when the sensor\n"
        "was not connected or had insufficient data.  Callers received a success\n"
        "status code with an error payload, which is misleading and tricky to handle.\n\n"
        "Inspect the result dict and raise HTTP 404 when an 'error' key is present,\n"
        "converting the internal sentinel into a proper API error response.\n\n"
        "Fixes issue 6."
    ),
)

# ---------------------------------------------------------------------------
# Issue 7: clients.py conflict message leaks other sensor name
# ---------------------------------------------------------------------------
clients = REPO / "apps/server/vibesensor/routes/clients.py"

patch(
    clients,
    (
        "            if conflict is not None:\n"
        "                other_name = conflict.get(\"name\") or \"another sensor\"\n"
        "                raise HTTPException(\n"
        "                    status_code=409,\n"
        "                    detail=f\"Location already assigned to {other_name}\",\n"
        "                )"
    ),
    (
        "            if conflict is not None:\n"
        "                raise HTTPException(\n"
        "                    status_code=409,\n"
        "                    detail=\"Location is already assigned to another sensor\",\n"
        "                )"
    ),
)
commit(
    ["apps/server/vibesensor/routes/clients.py"],
    (
        "fix(api): remove sensor name from 409 conflict response in set_client_location\n\n"
        "When two sensors competed for the same location code, the 409 response\n"
        "included the conflicting sensor's display name:\n"
        "  'Location already assigned to <other_name>'\n"
        "This leaks the name of an unrelated sensor to any caller, which is an\n"
        "unnecessary information disclosure.\n\n"
        "Replace with a generic message that does not expose any sensor identifier.\n\n"
        "Fixes issue 7."
    ),
)

# ---------------------------------------------------------------------------
# Issue 8: ws_hub error payload lacks schema_version field
# ---------------------------------------------------------------------------
ws_hub = REPO / "apps/server/vibesensor/ws_hub.py"

patch(
    ws_hub,
    "from .json_utils import sanitize_for_json",
    "from .json_utils import sanitize_for_json\nfrom .payload_types import SCHEMA_VERSION",
)
patch(
    ws_hub,
    (
        '_ERROR_PAYLOAD: str = json.dumps(\n'
        '    {"error": "payload_build_failed"},\n'
        '    separators=(",", ":"),\n'
        ")\n"
        '"""Pre-serialised error payload sent to clients when their payload build fails."""'
    ),
    (
        "def _make_error_payload() -> str:\n"
        '    """Build the pre-serialised error payload including the current schema version."""\n'
        "    return json.dumps(\n"
        '        {"schema_version": SCHEMA_VERSION, "error": "payload_build_failed"},\n'
        '        separators=(",", ":"),\n'
        "    )\n"
        "\n"
        "\n"
        "_ERROR_PAYLOAD: str = _make_error_payload()\n"
        '"""Pre-serialised error payload sent when a per-client payload build fails.\n'
        "\n"
        "Includes ``schema_version`` so clients can parse it like any other live-\n"
        "payload frame and route on the ``error`` field rather than failing on an\n"
        '"""'
    ),
)
commit(
    ["apps/server/vibesensor/ws_hub.py"],
    (
        "fix(ws): include schema_version in WebSocket error payload\n\n"
        "_ERROR_PAYLOAD was {\"error\": \"payload_build_failed\"} with no schema_version\n"
        "field.  Frontend clients that unpack every live-payload frame by schema_version\n"
        "would fail to route this message correctly.\n\n"
        "Add schema_version to the error payload so it is structurally consistent\n"
        "with normal LiveWsPayload frames and clients can distinguish it via the\n"
        "'error' key.  Fixes issue 8."
    ),
)

# ---------------------------------------------------------------------------
# Issue 9: WebSocket endpoint silently falls back on invalid client_id
# ---------------------------------------------------------------------------
ws_route = REPO / "apps/server/vibesensor/routes/websocket.py"

patch(
    ws_route,
    (
        "    @router.websocket(\"/ws\")\n"
        "    async def ws_endpoint(ws: WebSocket) -> None:\n"
        "        selected = ws.query_params.get(\"client_id\")\n"
        "        if selected is not None:\n"
        "            try:\n"
        "                selected = normalize_sensor_id(selected)\n"
        "            except ValueError:\n"
        "                selected = None\n"
        "        await ws.accept()\n"
        "        await state.ws_hub.add(ws, selected)"
    ),
    (
        "    @router.websocket(\"/ws\")\n"
        "    async def ws_endpoint(ws: WebSocket) -> None:\n"
        "        selected = ws.query_params.get(\"client_id\")\n"
        "        client_id_invalid = False\n"
        "        if selected is not None:\n"
        "            try:\n"
        "                selected = normalize_sensor_id(selected)\n"
        "            except ValueError:\n"
        "                LOGGER.warning(\n"
        "                    \"WebSocket connection received invalid client_id query param %r; \"\n"
        "                    \"defaulting to all-sensor broadcast.\",\n"
        "                    selected,\n"
        "                )\n"
        "                client_id_invalid = True\n"
        "                selected = None\n"
        "        await ws.accept()\n"
        "        if client_id_invalid:\n"
        "            await ws.send_text(\n"
        "                '{\"error\":\"invalid_client_id\",'\n"
        "                '\"detail\":\"Requested client_id was not a valid sensor identifier; '\n"
        "                'all sensors will be broadcast.\"}'\n"
        "            )\n"
        "        await state.ws_hub.add(ws, selected)"
    ),
)
commit(
    ["apps/server/vibesensor/routes/websocket.py"],
    (
        "fix(ws): notify client when client_id query param is invalid at WS connect\n\n"
        "When a WebSocket connection was opened with an invalid ?client_id=... query\n"
        "parameter, the server silently fell back to broad-casting all sensors without\n"
        "informing the client.  The client had no way to know their sensor filter\n"
        "was ignored.\n\n"
        "After accepting the connection, send a one-time JSON error frame when the\n"
        "client_id could not be normalised, and log a WARNING so operators can\n"
        "identify misconfigured clients.  Fixes issue 9."
    ),
)

# ---------------------------------------------------------------------------
# Issue 10: run_id path param not validated for length before DB lookup
# ---------------------------------------------------------------------------
patch(
    helpers,
    "def safe_filename(name: str) -> str:",
    (
        "_RUN_ID_MAX_LEN = 128\n"
        '"""Maximum accepted length for a run_id path parameter before any DB lookup."""\n'
        "\n"
        "\n"
        "def validate_run_id_or_400(run_id: str) -> str:\n"
        '    """Validate a run_id path parameter for length before any DB lookup.\n'
        "\n"
        "    Rejects oversized or empty run IDs early — before they reach the\n"
        "    database — to prevent unnecessarily long strings from hitting storage\n"
        "    queries.  A valid run_id is at most :data:`_RUN_ID_MAX_LEN` chars.\n"
        '    """\n'
        "    if not run_id or len(run_id) > _RUN_ID_MAX_LEN:\n"
        "        raise HTTPException(\n"
        "            status_code=400,\n"
        "            detail=f\"run_id must be 1-{_RUN_ID_MAX_LEN} characters\",\n"
        "        )\n"
        "    return run_id\n"
        "\n"
        "\n"
        "def safe_filename(name: str) -> str:"
    ),
)
patch(
    helpers,
    (
        'async def async_require_run(history_db: HistoryDB, run_id: str) -> dict[str, Any]:\n'
        '    """Fetch a history run in a thread or raise 404."""\n'
        "    run = await asyncio.to_thread(history_db.get_run, run_id)\n"
        "    if run is None:\n"
        '        raise HTTPException(status_code=404, detail="Run not found")\n'
        "    return run"
    ),
    (
        'async def async_require_run(history_db: HistoryDB, run_id: str) -> dict[str, Any]:\n'
        '    """Validate *run_id* and fetch the history run or raise HTTP 4xx.\n'
        "\n"
        "    Returns HTTP 400 when *run_id* exceeds the maximum allowed length,\n"
        "    and HTTP 404 when no run with that ID exists.\n"
        '    """\n'
        "    validate_run_id_or_400(run_id)\n"
        "    run = await asyncio.to_thread(history_db.get_run, run_id)\n"
        "    if run is None:\n"
        '        raise HTTPException(status_code=404, detail="Run not found")\n'
        "    return run"
    ),
)
# Also add validate_run_id_or_400 to the DELETE endpoint in history.py
patch(
    history,
    (
        "    @router.delete(\"/api/history/{run_id}\", response_model=DeleteHistoryRunResponse)\n"
        "    async def delete_history_run(run_id: str) -> DeleteHistoryRunResponse:\n"
        "        deleted, reason = await asyncio.to_thread(state.history_db.delete_run_if_safe, run_id)"
    ),
    (
        "    @router.delete(\"/api/history/{run_id}\", response_model=DeleteHistoryRunResponse)\n"
        "    async def delete_history_run(run_id: str) -> DeleteHistoryRunResponse:\n"
        "        validate_run_id_or_400(run_id)\n"
        "        deleted, reason = await asyncio.to_thread(state.history_db.delete_run_if_safe, run_id)"
    ),
)
patch(
    history,
    "from ._helpers import async_require_run, safe_filename",
    "from ._helpers import async_require_run, safe_filename, validate_run_id_or_400",
)
commit(
    [
        "apps/server/vibesensor/routes/_helpers.py",
        "apps/server/vibesensor/routes/history.py",
    ],
    (
        "fix(api): validate run_id length before DB lookup in history endpoints\n\n"
        "All history route handlers accepted arbitrarily long run_id path parameters\n"
        "and forwarded them directly to database queries.  Submitting a multi-KB\n"
        "string would hit the DB before being rejected.\n\n"
        "Add validate_run_id_or_400() in routes/_helpers.py which returns 400 when\n"
        "run_id is empty or exceeds 128 characters.  Wire it into:\n"
        "  - async_require_run() so GET /history/{id}, /insights, /report.pdf, and\n"
        "    /export all benefit automatically.\n"
        "  - delete_history_run() which bypasses async_require_run.\n\n"
        "Fixes issue 10."
    ),
)

print("\n=== All 10 fixes applied and committed successfully ===")
