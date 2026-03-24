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
See [docs/ai/repo-map.md#backend-package-layout](../../docs/ai/repo-map.md#backend-package-layout)
for the detailed backend ownership map. This README stays focused on
backend-specific setup, configuration, routes, updates, and testing.

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

Use the top-level [README quickstart](../../README.md#quick-start) for the
supported Docker and native bootstrap commands, then come back here for
backend-specific configuration and CLI details.

The local development configs default the HTTP listener to port `8000`.

For native backend iteration, run `vibesensor-server --reload --config
apps/server/config.dev.yaml` from the repo root so Python changes hot-reload
while the Vite dev server proxies browser traffic to `http://127.0.0.1:8000`.

## Dependency management

Backend Python dependencies are declared in `apps/server/pyproject.toml` with
bounded version ranges and installed through the editable package flow (`python
-m pip install -e "./apps/server[dev]"`). The repo currently validates that
model with CI `pip check` plus automated Dependabot update PRs rather than
maintaining a second checked-in Python lockfile workflow alongside the editable
install path.

## Configuration

Configuration is YAML-based. Run `vibesensor-config-preflight --dump-defaults` to see all available keys with defaults. Use `apps/server/config.dev.yaml` or `apps/server/config.docker.yaml` for local overrides.

For live sensor presence, `processing.client_live_ttl_seconds` controls how long
`/api/clients` and `/ws` keep reporting `connected: true` after the last
packet. `processing.client_ttl_seconds` is the longer retention/eviction window
for keeping stale clients and their metadata available after they stop sending
traffic.

Common runtime files under `apps/server/data/` include:

- `history.db`: persisted run history and settings.
- `metrics.jsonl`: optional metrics log output.
- `clients.json`: persisted client metadata.
- `report_i18n.json`: report translation data.

## Observability

When `logging.app_log_path` is configured, the backend writes structured JSON
application logs instead of plain text. Each HTTP response now echoes an
`X-Request-ID` header, and matching request-scoped log entries carry the same
`request_id` field so operators can correlate a client-visible failure with the
server log line that handled it.

Successful settings writes also emit `settings_change` audit entries with
before/after values for the changed setting or car profile. That gives a stable
operator trail for configuration changes without adding a second persistence
path.

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

### HTTP API schema export and versioning stance

- Export the committed HTTP OpenAPI schema with `python -m vibesensor.cli.http_api_schema_export`.
- The checked-in schema artifact lives at
  `apps/ui/src/contracts/http_api_schema.json` and is kept in sync by CI
  drift checks.
- The current HTTP API intentionally remains a single unversioned `/api/*`
  surface because the backend and bundled UI ship atomically.
- If independent or third-party clients become a real compatibility concern,
  introduce explicit path versioning starting at `/api/v1/` rather than adding
  ad hoc compatibility shims to the current routes.

## Reports

Generate a PDF from a saved run:

```bash
vibesensor-report path/to/run.jsonl --output report.pdf --summary-json summary.json
```

The public PDF entrypoint is `apps/server/vibesensor/adapters/pdf/pdf_engine.py`. Page composition lives in focused modules under `adapters/pdf/`.

## Updates

Production devices use the wheel-based updater in `apps/server/vibesensor/use_cases/updates/`, with `manager.py` as the public facade over the focused updater modules.

`firmware_cache.py` is now the thin public cache/CLI surface, while `firmware_release_fetcher.py` owns GitHub firmware HTTP access, `firmware_bundle.py` owns bundle extraction/validation/metadata helpers, and `firmware_types.py` owns the updater-local cache/release contracts.

- Normal delivery should go through release wheels.
- Do not rely on manual edits inside deployed `site-packages` as a normal workflow.
- Emergency in-place patching is allowed only to restore a broken live updater and must be followed by the matching in-repo fix, validation, and a successful updater run.

## Testing

Use [.github/copilot-instructions.md](../../.github/copilot-instructions.md)
§ "Commands" for backend validation commands, and
[docs/testing.md](../../docs/testing.md) for the full test map and command
selection guidance.

`make typecheck-backend` is the enforced backend static-typing gate for the `vibesensor` package. It checks backend files by default without an internal module denylist. Use `docs/testing.md` for the full test map. Start with the matching mirrored feature directory under `apps/server/tests/`, then add `integration/` coverage when the behavior crosses package boundaries.

When tightening Python types, treat `Any` as a smell rather than a shortcut: prefer shared `JsonValue`/`JsonObject` aliases for persisted JSON, `TypedDict`/dataclass contracts for nested payloads, and `ParamSpec` for generic callable wrappers so mypy reflects the real runtime contract instead of a permissive fallback.
