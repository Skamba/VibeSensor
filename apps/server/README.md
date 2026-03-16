# Server backend

FastAPI backend for VibeSensor. It ingests UDP telemetry from ESP32 sensor nodes, runs vibration analysis, serves the browser UI over HTTP and WebSocket, stores run history in SQLite, and generates PDF diagnostic reports.

## Source of truth

- Backend package: `apps/server/vibesensor/`
- Protocol and wire-level details: `docs/protocol.md`
- Test layout: `docs/testing.md`
- AI repo maps and runbooks: `docs/ai/`

## Current architecture

```text
ESP32 nodes -> adapters/udp/ -> infra/processing/ + use_cases/diagnostics/
                             -> infra/runtime/ -> adapters/http/ + adapters/websocket/ -> apps/ui
                             -> use_cases/run/ + adapters/persistence/history_db/ -> use_cases/history/ -> adapters/pdf/
```

Backend ownership boundaries:

- `app/`: FastAPI app factory (`bootstrap.py`), runtime container wiring (`container.py`), and YAML settings/config loading (`settings.py`).
- `adapters/http/` and `adapters/websocket/`: HTTP route groups and live WebSocket delivery.
- `infra/runtime/`: flat `RuntimeState`, lifecycle management, processing loop, health snapshots, and WebSocket broadcast coordination.
- `infra/processing/`: signal processing pipeline.
- `infra/config/`: runtime settings stores used by recording and runtime services.
- `use_cases/diagnostics/`: post-stop analysis/findings logic.
- `use_cases/run/`: recording orchestration and post-analysis queue.
- `adapters/persistence/` and `use_cases/history/`: SQLite persistence, runlog I/O, car library loading, and history/report/export services.
- `adapters/pdf/`: PDF/report rendering pipeline.
- `use_cases/updates/`: wheel-based update flow.
- `adapters/hotspot/`: Wi-Fi AP monitoring, parsing, and self-heal infrastructure.

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

The API surface is implemented in `apps/server/vibesensor/adapters/http/` and assembled by `adapters/http/__init__.py`.

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

The public PDF entrypoint is `apps/server/vibesensor/adapters/pdf/pdf_engine.py`. Page composition lives in focused modules under `adapters/pdf/`.

## Updates

Production devices use the wheel-based updater in `apps/server/vibesensor/use_cases/updates/`, with `manager.py` as the public facade over the focused updater modules.

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

`make typecheck-backend` is the enforced backend static-typing gate for the reorganized `app/`, `shared/`, `infra/`, `use_cases/`, `adapters/`, and `domain/` packages. Use `docs/testing.md` for the full test map. Start with the matching mirrored feature directory under `apps/server/tests/`, then add `integration/` coverage when the behavior crosses package boundaries.

When tightening Python types, treat `Any` as a smell rather than a shortcut: prefer shared `JsonValue`/`JsonObject` aliases for persisted JSON, `TypedDict`/dataclass contracts for nested payloads, and `ParamSpec` for generic callable wrappers so mypy reflects the real runtime contract instead of a permissive fallback.
