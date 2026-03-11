# Server backend

FastAPI backend for VibeSensor. It ingests UDP telemetry from ESP32 sensor nodes, runs vibration analysis, serves the browser UI over HTTP and WebSocket, stores run history in SQLite, and generates PDF diagnostic reports.

## Source of truth

- Backend package: `apps/server/vibesensor/`
- Protocol and wire-level details: `docs/protocol.md`
- Test layout: `docs/testing.md`
- AI repo maps and runbooks: `docs/ai/`

## Current architecture

```text
ESP32 nodes -> udp_data_rx.py -> processing/ + analysis/ -> runtime/ -> routes/ + ws_hub.py -> apps/ui
                                           \-> metrics_log/ + history_db/ -> history_services/ -> report/
```

Backend ownership boundaries:

- `app.py`: FastAPI app factory and startup entry.
- `routes/`: HTTP and WebSocket route groups.
- `runtime/`: service builders, flat `RuntimeState`, processing loop, WebSocket broadcast, and lifecycle management.
- `processing/`, `analysis/`: signal processing and findings logic.
- `metrics_log/`, `history_db/`, `history_services/`, `runlog.py`: recording, persistence, and exports. Inside `metrics_log/`, `session_state.py` owns recording-session lifecycle, `persistence.py` owns history-run create/append/finalize bookkeeping, and `post_analysis.py` owns the background analysis queue; `logger.py` is the façade that coordinates those focused collaborators. The `history_services/` package owns the domain-logic layer above `HistoryDB` — run query/delete, PDF report generation, CSV/ZIP exports.
- `report/`: PDF rendering pipeline.
- `update/`: wheel-based update flow.
- `hotspot/`: Wi-Fi AP monitoring, parsing, and self-heal infrastructure.

## Important directories

```text
apps/server/
├── pyproject.toml
├── config.yaml
├── config.dev.yaml
├── config.docker.yaml
├── config.example.yaml
├── data/
├── scripts/
├── systemd/
├── tests/
└── vibesensor/
```

- `data/`: runtime state, history database, and report i18n JSON.
- `vibesensor/static/`: built UI assets served by FastAPI.
- `scripts/` and `systemd/`: Pi deployment and hotspot support.
- `tests/`: pytest suite, organized by backend ownership boundary.

## Local development

From the repository root:

```bash
python3 -m pip install -e "./apps/server[dev]"
vibesensor-server --config apps/server/config.dev.yaml
```

Or run the local stack through Docker:

```bash
docker compose up --build
```

The local development configs default the HTTP listener to port `8000`.

## Configuration

Configuration is YAML-based. Use `apps/server/config.example.yaml` as the canonical config reference and `apps/server/config.dev.yaml` or `apps/server/config.docker.yaml` for local overrides.

Common runtime files under `apps/server/data/` include:

- `history.db`: persisted run history and settings.
- `metrics.jsonl`: optional metrics log output.
- `clients.json`: persisted client metadata.
- `report_i18n.json`: report translation data.

## HTTP and WebSocket surface

The API surface is implemented in `apps/server/vibesensor/routes/` and assembled by `routes/__init__.py`.

Current route groups:

- `health.py`
- `clients.py`
- `settings.py`
- `recording.py`
- `history.py`
- `websocket.py`
- `updates.py`
- `car_library.py`
- `debug.py`

When route ownership changes, update this README and the AI repo maps in the same change set.

## Reports

Generate a PDF from a saved run:

```bash
vibesensor-report path/to/run.jsonl --output report.pdf --summary-json summary.json
```

The public PDF entrypoint is `apps/server/vibesensor/report/pdf_engine.py`. Page composition lives in focused modules under `report/`.

## Updates

Production devices use the wheel-based updater in `apps/server/vibesensor/update/`, with `manager.py` as the public facade over the focused updater modules.

- Normal delivery should go through release wheels.
- Do not rely on manual edits inside deployed `site-packages` as a normal workflow.
- Emergency in-place patching is allowed only to restore a broken live updater and must be followed by the matching in-repo fix, validation, and a successful updater run.

## Testing

```bash
make lint
make typecheck-backend
pytest -q -m "not selenium" apps/server/tests
python3 tools/tests/pytest_progress.py --show-test-names -- -m "not selenium" apps/server/tests
make test-all
```

`make typecheck-backend` is the enforced backend static-typing gate for app, runtime/routes, and the high-risk `analysis/`, `processing/`, `history_db/`, and `update/` packages. Use `docs/testing.md` for the full test map. Start with the matching feature directory under `apps/server/tests/`, then add `integration/` or `regression/` coverage when the behavior crosses package boundaries.

When tightening Python types, treat `Any` as a smell rather than a shortcut: prefer shared `JsonValue`/`JsonObject` aliases for persisted JSON, `TypedDict`/dataclass contracts for nested payloads, and `ParamSpec` for generic callable wrappers so mypy reflects the real runtime contract instead of a permissive fallback.
