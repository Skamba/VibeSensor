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

## State and configuration scopes

Several issue reports have described the backend as one pool of global mutable
state. Current `main` is intentionally split more narrowly:

- `AppConfig` in `vibesensor.app.config_schema` owns YAML-backed deployment
  configuration loaded at startup, such as network bindings, retention windows,
  processing budgets, and update paths.
- `BootstrapEnvSettings`, `WebSocketEnvSettings`, and `UpdateEnvSettings` in
  `vibesensor.shared.process_settings` own process-level env overrides and
  feature flags such as config-path selection, static-asset mounting, WS debug
  logging, and updater/release path/repo defaults. `vibesensor.app.settings`
  re-exports that surface for app/CLI entrypoints.
- Focused persisted settings services own user-facing runtime settings: car
  profiles (`CarSettingsService`), active-car analysis settings
  (`ActiveCarAnalysisSettingsService`), speed-source preferences
  (`PersistedSpeedSourceSettingsService`), language/units
  (`UiPreferencesService`), and canonical sensor metadata
  (`SensorSettingsService`). A shared settings snapshot coordinator owns only
  the single stored snapshot's load/save/rollback mechanics.
  `build_settings_service_bundle()` in `vibesensor.app.container` groups those
  focused services into explicit runtime and HTTP dependency bundles.
  `SettingsDerivationService` projects the persisted car settings into the
  current analysis/run context, while `SpeedSourceRuntimeApplier` pushes the
  current speed-source selection into live runtime collaborators. Client-facing
  sensor location assignment also delegates through `SensorSettingsService`.
  HTTP adapters and runtime collaborators should consume the focused settings
  ports they need rather than importing persistence internals directly.
  Route-facing HTTP modules should stay on shared ports or adapter-local
  protocol seams, while `clients.py` remains the only HTTP surface allowed to
  delegate location writes through `assign_sensor_location()`.
- `vibesensor.app.container.build_runtime()` is a thin app-layer orchestrator.
  It delegates speed/OBD setup, history/reporting services, live runtime
  services, update deps, lifecycle state, and router wiring to focused builder
  functions with explicit bundles rather than extending one monolithic
  composition function.
- Run lifecycle helpers (`RunLifecycleState`, `RunRecorder`,
  `PostAnalysisWorker`) own live per-process coordination and per-run state.
- History persistence now uses a shared SQLite lifecycle engine plus narrow
  run, settings-snapshot, and client-name repositories. The live recording path
  and post-analysis/report path still remain separate phases with different
  owners even though they share one SQLite file.

That separation is deliberate: deployment config, mutable user settings, and
run-attached snapshots are related, but they are not interchangeable sources of
truth.

## Startup sequencing

Backend startup is explicit rather than ambient:

1. `vibesensor.app.bootstrap` resolves config and builds the runtime/container.
2. `LifecycleManager.start()` runs lightweight startup validation, opens the UDP
   receiver, starts the control plane, and then launches the supervised
   processing, WebSocket, metrics, GPS, and update-recovery tasks in a declared
   order.
3. The runtime is only marked ready after those startup phases succeed.

See `apps/server/vibesensor/infra/runtime/lifecycle.py` and
`apps/server/tests/infra/runtime/test_runtime.py` for the executable phase
contract.

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

## Payload boundary pattern

Updater status persistence and `/api/update/status` now share one msgspec-owned
boundary in `vibesensor/use_cases/updates/status/payload_codec.py`.

- Keep the domain models (`UpdateJobStatus`, `UpdateRuntimeDetails`,
  `UpdateIssue`) as the internal source of truth.
- Use `Update*Payload` `msgspec.Struct` types only at the persistence/HTTP
  boundary, then route both JSON file I/O and FastAPI response shaping through
  `update_status_to_payload()`, `update_status_to_builtins()`,
  `update_status_to_json()`, `update_status_from_builtins()`, and
  `update_status_from_json()`.
- Keep compatibility code narrow: legacy persisted status oddities normalize in
  one decode fallback path instead of leaking loose coercion into domain models
  or route handlers.
- Keep Pydantic response models at the HTTP edge when OpenAPI generation still
  depends on them; msgspec feeds those models with already-validated builtins.

For Pi or Pi-like timing checks before widening this pattern, run:

```bash
python tools/tests/benchmark_update_status_codec.py --iterations 5000 --rounds 20
```

The benchmark uses a representative updater-status payload and reports payload
bytes plus median/p95 encode/decode latency in microseconds per operation.

## Configuration

Configuration is YAML-based. Runtime defaults live in `vibesensor/app/config_defaults.py`, and `load_config()` applies precedence `DEFAULT_CONFIG -> selected YAML override file -> typed validation/clamping`. Run `vibesensor-config-preflight --dump-defaults` to see all available keys with defaults, or run `vibesensor-config-preflight apps/server/config.dev.yaml` / `apps/server/config.docker.yaml` to inspect a resolved override file.

Use [docs/configuration_reference.md](../../docs/configuration_reference.md) for
the key-by-key operator reference across the `ap`, `server`, `udp`,
`processing`, `logging`, `gps`, and `update` sections.

Those YAML files cover deployment/process settings. User-facing runtime
preferences are stored separately through the focused persisted settings
services over one settings snapshot in `history.db`; runtime consumers read the
derived current-context view rather than mutating persisted settings directly,
and completed runs persist immutable per-run snapshots for later
analysis/reporting. Persisted sensor display metadata also lives in that shared
settings snapshot, while `ClientRegistry` remains the owner of live
transport/connection state only.

For live sensor presence, `processing.client_live_ttl_seconds` controls how long
`/api/clients` and `/ws` keep reporting `connected: true` after the last
packet. `processing.client_ttl_seconds` is the longer retention/eviction window
for keeping stale clients and their metadata available after they stop sending
traffic.

For persisted run history on Pi-class devices, `logging.run_retention_days`
controls how many days of terminal (`complete` / `error`) runs are kept before
startup maintenance prunes them automatically. The default is `7`.

## Environment variables

Prefer YAML config for normal runtime settings. The backend resolves the
environment-driven startup/static layer through
`vibesensor.shared.process_settings` so env names, defaults, and validation
stay in one typed owner instead of being spread across bootstrap and updater
modules.

Those process settings stay separate from the persisted user settings services:
car, analysis, speed-source, UI-preference, and sensor-metadata state still
live in the settings snapshot/history DB flow because they need transactional
mutation and per-run snapshot behavior that env/process settings do not.

The backend supports this focused set of env overrides for packaging, service,
and debug workflows:

- `VIBESENSOR_CONFIG_PATH`: alternate config path used by the app factory and
  the hotspot/systemd launch path.
- `VIBESENSOR_SERVE_STATIC=0`: disable mounting bundled UI static files for
  API-only runs, backend tests, or release validation helpers.
- `VIBESENSOR_WS_DEBUG=1`: enable dev-only WebSocket payload-size debug logs.

Importing `vibesensor.app` or `vibesensor.app.bootstrap` is now side-effect
free. Config loading, runtime construction, SQLite opening, and static-asset
validation happen only when callers explicitly invoke `create_app(...)` or the
CLI startup path.

Updater and release tooling also expose focused overrides:

- `VIBESENSOR_FIRMWARE_CACHE_DIR`
- `VIBESENSOR_FIRMWARE_REPO`
- `VIBESENSOR_FIRMWARE_CHANNEL`
- `VIBESENSOR_FIRMWARE_PINNED_TAG`
- `VIBESENSOR_SERVER_REPO`
- `VIBESENSOR_UPDATE_STATE_PATH`
- `VIBESENSOR_UPDATE_SUDO_WRAPPER`

Those update-related variables are intended for controlled packaging, staging,
or recovery scenarios rather than day-to-day dashboard use.

Common runtime files under `apps/server/data/` include:

- `history.db`: persisted run history and settings.
- `metrics.jsonl`: optional metrics log output.
- `clients.json`: persisted client metadata.
- `report_i18n.json`: report translation data.

## Pi deployment & service operations

Use the top-level [README deployment section](../../README.md#deploying-to-raspberry-pi)
to choose between manual install and the prebuilt image flow. After the software
is on the device, this README owns the backend-side service and config path.

- Runtime config lives at `/etc/vibesensor/config.yaml`. Manual install copies
  `apps/server/config.pi.yaml` there on first install, and the prebuilt image
  bakes the same overlay into the image build.
- Validate the on-device config before restarting services:

  ```bash
  /path/to/venv/bin/vibesensor-config-preflight /etc/vibesensor/config.yaml
  ```

- The main service units are:
  - `vibesensor.service`
  - `vibesensor-hotspot.service`
  - `vibesensor-hotspot-self-heal.timer`

- Common service operations:

  ```bash
  sudo systemctl status vibesensor.service vibesensor-hotspot.service --no-pager
  sudo systemctl restart vibesensor.service
  sudo systemctl restart vibesensor-hotspot.service
  sudo systemctl status vibesensor-hotspot-self-heal.timer --no-pager
  sudo journalctl -u vibesensor.service -u vibesensor-hotspot.service -n 200 --no-pager
  ```

- Hotspot diagnostics are written under `/var/log/wifi/`, including
  `hotspot.log` plus the latest `summary.txt`/dump files emitted by
  `apps/server/scripts/hotspot_nmcli.sh`.
- Backend runtime data lives under `/var/lib/vibesensor/` and `/var/log/vibesensor/`
  on Pi installs.
- First verification after install/flash:

  ```bash
  curl -sf http://10.4.0.1/api/health || curl -sf http://10.4.0.1:8000/api/health
  curl -sf http://10.4.0.1/api/clients || curl -sf http://10.4.0.1:8000/api/clients
  ```

Use [docs/configuration_reference.md](../../docs/configuration_reference.md) for
config tuning, [docs/operational-runbooks.md](../../docs/operational-runbooks.md)
for incident response, and
[infra/pi-image/pi-gen/README.md](../../infra/pi-image/pi-gen/README.md) for the
image-build path and artifact validation.

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

Run transitions now also emit structured `run_lifecycle` records with a
`run_action` (`started` or `stopped`), the `run_id`, timestamps, and, for stop
events, the stop reason plus written/dropped sample counters. That gives
operators a queryable trail for manual stops, restart rollovers, inactivity
auto-stops, and shutdown cleanup without stitching together multiple log
messages.

## HTTP and WebSocket surface

The API surface is implemented in `apps/server/vibesensor/adapters/http/`, with the top-level composition root in `adapters/http/router.py` and domain bundle registration in `adapters/http/route_bundles.py`.

Start here for the human-facing API overview, then use the generated schema artifacts for endpoint-level contracts:

- `make sync-contracts` is the authoritative end-to-end contract sync entrypoint. It refreshes the committed HTTP OpenAPI schema at `apps/ui/src/contracts/http_api_schema.json`, the committed WebSocket schema at `apps/ui/src/contracts/ws_payload_schema.json`, `docs/protocol.md`, and the locally materialized derivative UI TypeScript/constants generated from those checked-in inputs.
- The committed HTTP schema remains the endpoint-by-endpoint reference for request/response shapes, route descriptions, and documented HTTP error responses.
- Pair the committed WebSocket schema with `apps/ui/README.md` § "WebSocket contract boundary" for the human-readable field guide.
- `docs/operational-runbooks.md` covers `/api/health` interpretation and stale-live-update debugging steps.

Current route groups:

- `health.py` — `/api/health` runtime, startup, and degradation snapshots.
- `clients.py` — sensor inventory, location assignment, and identify/blink actions.
- `settings/` — aggregated settings routes split across cars, speed source, OBD admin, UI preferences, and analysis micro-routers.
- `recording.py` — recording lifecycle control and status.
- `history.py` — saved runs, insights, reports, and exports.
- `websocket.py` — `/ws` live update stream and selected-client updates.
- `updates.py` — software updater and ESP flash workflows.
- `car_library.py` — bundled car library brands/types/variants.

### HTTP API schema export and versioning stance

- Refresh all committed contract artifacts with `make sync-contracts`.
- The checked-in schema artifact lives at
  `apps/ui/src/contracts/http_api_schema.json`, while the committed WebSocket
  payload schema lives at `apps/ui/src/contracts/ws_payload_schema.json`; both,
  along with `docs/protocol.md`, are kept in sync by the authoritative
  contract-drift checks.
- The current HTTP API intentionally remains a single unversioned `/api/*`
  surface because the backend and bundled UI ship atomically.
- If independent or third-party clients become a real compatibility concern,
  introduce explicit path versioning starting at `/api/v1/` rather than adding
  ad hoc compatibility shims to the current routes.

### Common error semantics

The exported OpenAPI schema documents per-route error responses. The main status
families currently used across the HTTP adapters are:

- `400` — invalid identifiers, malformed request values, or invalid config-style inputs.
- `404` — unknown sensors, runs, or car-library entities.
- `409` — state conflicts such as already-running workflows or location collisions.
- `422` — history/analysis requests that are structurally valid but not currently available for the run state.
- `503` — live sensor actions that cannot be served because the device is not currently reachable.
- `500` — unexpected internal failures that escape the route-specific error mapping.

WebSocket error frames are separate from `LiveWsPayload` and currently use
`{"error": "payload_build_failed"}` when the server cannot assemble a live
update tick.

## Reports

Generate a PDF from a saved run:

```bash
vibesensor-report path/to/run.jsonl --output report.pdf --summary-json summary.json
```

The public PDF entrypoint is `apps/server/vibesensor/adapters/pdf/pdf_engine.py`. Page composition lives in focused modules under `adapters/pdf/`, with panel renderers grouped under `adapters/pdf/panels/`.

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
