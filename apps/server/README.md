# Server backend

FastAPI backend for VibeSensor. It ingests UDP telemetry from ESP32 sensor nodes, runs vibration analysis, serves the browser UI over HTTP and WebSocket, stores run history in SQLite, and generates PDF diagnostic reports.

## Source of truth

- Backend package: `apps/server/vibesensor/`
- Protocol and wire-level details: `docs/protocol.md`
- Test layout: `docs/testing.md`
- AI repo maps and runbooks: `docs/ai/`

## Current architecture

```text
ESP32 nodes -> adapters/udp + adapters/gps -> infra/processing -> infra/runtime -> adapters/http + adapters/websocket -> apps/ui
                                                            \-> infra/metrics + adapters/persistence -> use_cases/history -> use_cases/reporting + adapters/pdf
```

Backend ownership boundaries:

- `app/`: FastAPI bootstrap (`bootstrap.py`), runtime assembly (`container.py`), and config loading (`settings.py`).
- `domain/`: domain-first aggregates and value objects grouped by `run/`, `diagnostics/`, `vehicle/`, `sensing/`, `reporting/`, and `updates/`.
- `use_cases/`: post-stop diagnostics, history orchestration, reporting assembly, and update workflows.
- `adapters/`: HTTP routes/models/schema export, WebSocket hub/schema export, persistence boundaries + SQLite/history I/O, PDF rendering, UDP transport, GPS ingestion, and simulator tooling.
- `infra/`: runtime coordination, live processing, worker pool, config stores, hotspot management, and metrics/recording infrastructure.
- `cli/`: server/report/config entry points.

## Important directories

```text
apps/server/
├── pyproject.toml
├── config.yaml
├── config.dev.yaml
├── config.docker.yaml
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

Configuration is YAML-based. Run `vibesensor-config-preflight --dump-defaults` to see all available keys with defaults. Use `apps/server/config.dev.yaml` or `apps/server/config.docker.yaml` for local overrides.

Common runtime files under `apps/server/data/` include:

- `history.db`: persisted run history and settings.
- `metrics.jsonl`: optional metrics log output.
- `clients.json`: persisted client metadata.
- `report_i18n.json`: report translation data.

## HTTP and WebSocket surface

The API surface is implemented in `apps/server/vibesensor/adapters/http/routes/` and assembled by `adapters/http/routes/__init__.py`.

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

The public PDF entrypoint is `apps/server/vibesensor/adapters/pdf/pdf_engine.py`. Report assembly lives in `use_cases/reporting/`, and page composition/rendering stays in `adapters/pdf/`.

## Updates

Production devices use the wheel-based updater flow under `apps/server/vibesensor/use_cases/updates/`, with update state/value objects in `domain/updates/`.

- Normal delivery should go through release wheels.
- Do not rely on manual edits inside deployed `site-packages` as a normal workflow.
- Emergency in-place patching is allowed only to restore a broken live updater and must be followed by the matching in-repo fix, validation, and a successful updater run.

## Testing

```bash
make lint
make typecheck-backend
pytest -q apps/server/tests
python3 tools/tests/pytest_progress.py --show-test-names apps/server/tests
make test-all
```

`make typecheck-backend` is the enforced backend static-typing gate for `app/`, `adapters/`, `infra/`, `use_cases/`, and the high-risk persistence/update packages. Use `docs/testing.md` for the full test map. Start with the matching feature directory under `apps/server/tests/unit/`, then add `integration/` coverage when the behavior crosses package boundaries.

When tightening Python types, treat `Any` as a smell rather than a shortcut: prefer shared `JsonValue`/`JsonObject` aliases for persisted JSON, `TypedDict`/dataclass contracts for nested payloads, and `ParamSpec` for generic callable wrappers so mypy reflects the real runtime contract instead of a permissive fallback.
