# Web UI

Single-page TypeScript application that provides real-time vibration monitoring,
sensor management, run history, and car configuration. Communicates with the Pi
server over HTTP (REST) and WebSocket (live data).

## Tech Stack

- **TypeScript** — application logic
- **Preact + @preact/signals** — UI rendering plus shared reactive state
- **Vite** — build tool and dev server
- **uPlot** — high-performance spectrum charts
- **Playwright** — visual regression testing
- **CSS custom properties** — Material Design 3 inspired theming

## Setup

Use the supported Node line from
[docs/runtime_support_matrix.md](../../docs/runtime_support_matrix.md) before
running the UI commands below. Native frontend work follows [`.nvmrc`](../../.nvmrc).

```bash
cd apps/ui
npm ci
npm run lint         # Biome lint over the hand-written UI/config/test files
npm run lint:deps    # dependency-cruiser boundary checks over src/
npm run lint:unused  # knip dead-file/dependency checks
npm run dev          # Dev server on http://localhost:5173
npm run dev:open     # Same dev server, but opens the browser on local desktops
npm run dev:docker   # Docker-oriented wrapper: contract check + guarded npm ci + Vite
npm run build        # Production build to dist/
npm run analyze      # Production build + bundle analysis report at dist/bundle-analysis.html
npm run typecheck    # Type check without emitting
```

Use `npm ci` for normal repo bootstrap and dependency refresh from the checked-in
lockfile. Only use `npm install` when you are intentionally adding or updating
UI dependencies so the resulting `package-lock.json` change is deliberate.

The source-mounted Docker dev stack calls `npm run dev:docker` inside the UI
container. It re-runs `npm ci` only when `node_modules` is missing or the
checked-in `package-lock.json` changes, and it fails fast if the generated UI
contract files are stale.

The Vite dev server proxies `/api`, `/ws`, and `/static` to
`http://127.0.0.1:8000` by default so you can use HMR without manually swapping
backend URLs. Override that backend target with `VITE_BACKEND_ORIGIN` when your
server is listening elsewhere.

The built output in `dist/` is copied to `apps/server/vibesensor/static/` for serving by FastAPI.
Use `python tools/build_ui_static.py` from the repo root to build and sync
in one step.

## Contract sync

Use `make sync-contracts` from the repo root as the authoritative contract sync entrypoint. If your backend dev environment is already bootstrapped, `npm run sync:contracts` in `apps/ui/` is a thin alias to the same full pipeline.

That authoritative sync updates the checked-in contract inputs first:

- `src/contracts/http_api_schema.json`
- `src/contracts/ws_payload_schema.json`
- `../../docs/protocol.md`

It then regenerates the UI-only derivative artifacts:

- `src/generated/http_api_contracts.ts`
- `src/contracts/ws_payload_types.ts`
- `src/contracts/ws_payload_schema.generated.ts`
- `src/constants.ts`

Those derivative outputs are materialized locally from the tracked inputs and are no longer a committed source-of-truth surface. Explicit owner flows such as `test:smoke`, `dev:docker`, `make ui-typecheck`, and release/UI-build helpers call `npm run sync:generated-contracts` when they need the files on disk.

`npm run build` and `npm run typecheck` no longer regenerate those files automatically. They run `npm run check:contracts` first and fail fast with guidance to `make sync-contracts` if the local derivative copy is missing or stale. CI contract drift and human-facing regeneration should still use `make sync-contracts`.

The release-smoke artifact helper is the intentional narrow exception: after the same commit already passed `backend-contract-drift` and `frontend-typecheck`, `tools/build_ui_static.py --skip-typecheck --assume-prevalidated-contracts` still regenerates the UI-only derivatives for that fresh checkout but switches to `npm run build:prevalidated-contracts` so the late packaged smoke path does not repeat `check:contracts`.

## Code Quality

- `npm run lint` checks the hand-written TypeScript, config, and support scripts
  with Biome.
- `npm run lint:deps` runs dependency-cruiser against the current `src/`
  boundary rules so feature/runtime/view and transport/app seams stay explicit.
- `npm run lint:unused` runs knip's first-pass dead-file/dependency checks. It
  intentionally focuses on high-confidence files and dependency drift before the
  noisier export sweep lands in a follow-up.
- `npm run format` rewrites the supported files when you want to apply the repo
  UI formatting locally.

Generated contract artifacts stay out of the lint/format path on purpose so the
source-of-truth export commands remain the only writers for those files.

## HTTP boundary tests with MSW

Use `msw` as the shared HTTP mocking layer for UI tests that exercise the real
browser-side fetch boundary.

- Node-side Playwright specs should install the shared lifecycle from
  `tests/msw/node.ts`; it normalizes relative `/api/...` requests onto the
  test origin and fails unhandled HTTP requests loudly by default.
- Feature-specific reusable handlers belong under `tests/msw/handlers/` as they
  appear. Keep cross-feature primitives in `tests/msw/http.ts`, and name
  scenario factories `build<Feature><Scenario>Handlers(...)`.

## Optional browser MSW mock mode

Use the explicit mock-mode dev server when you want to exercise the UI without a
live backend HTTP stack:

```bash
cd apps/ui
npm run dev:mock
```

- `npm run dev` remains the normal backend-backed path. `npm run dev:mock` is
  the opt-in browser-worker mode and is easy to disable by switching back to the
  normal dev command.
- Browser mock mode starts the app with `msw/browser` before `startUiApp()`,
  serves a checked-in `mockServiceWorker.js`, and bypasses any HTTP requests
  that do not have an explicit mock handler.
- The mode currently reuses the shared history and settings MSW handler owners
  plus lightweight startup/update defaults so local settings and history flows
  can load without the backend.
- WebSocket mocking is still out of scope for this mode. Local smoke tests that
  need stable live-session behavior can still stub WebSocket separately.

## Bundle analysis

Run `npm run analyze` to build the production bundle and emit
`dist/bundle-analysis.html`. The report auto-opens when the build is running in
a desktop session; on headless or CI hosts, open the generated HTML file
manually after the build finishes.

Treat these gzip budgets as review thresholds for the named build artifacts:

| Asset | Budget |
|------|--------|
| `vendor.js` | `< 40 KB` |
| `chart.js` | `< 20 KB` |
| `index.js` | `< 60 KB` |
| Total CSS | `< 15 KB` |

These budgets are guidance, not hard CI gates. If a change pushes a chunk over
budget, attach the analyzer output to the PR review and explain the growth.

## Source Modules

| File | Purpose |
|------|---------|
| `main.ts` | Thin Vite entry that boots the UI runtime |
| `app/start_ui_app.ts` | CSS-aware public startup entry that mounts one `UiAppRoot` and returns a disposable app handle |
| `app/ui_app_mount.ts` | Pure mount helper that creates the runtime, renders the root tree, and composes teardown for tests and startup callers |
| `app/ui_app_root.tsx` | Single rendered app tree that owns the shell frame plus the dashboard/history/settings sections |
| `app/ui_panel_host_registry.ts` | Ref-backed settings-shell host registry for the per-tab settings panels mounted inside the settings subtree |
| `app/ui_lazy_panels.ts` | Typed panel binding factory that gives the runtime full dashboard/history/settings contracts up front, then attaches the real settings shell handles when that subtree mounts |
| `app/dom/` | Focused DOM-only utilities for download and RAF lifecycles after removing the shared global query helper |
| `app/ui_app_runtime.ts` | Thin UI composition root that creates the shell, spectrum, transport, feature bundle, and startup coordinator, then exposes one composed runtime `dispose()` |
| `app/ui_app_state.ts` | Canonical AppState shape plus reactive slice helpers that keep object-style reads/writes working while shared shell/transport/realtime/history/settings/spectrum state becomes signal-observable, preserve light-tick spectrum frames, and dedupe unchanged heavy frames before redraws |
| `app/ui_signals.ts` | Canonical re-export surface for shared `signal`, `computed`, and `effect` usage across runtime, features, and views |
| `app/runtime/ui_shell_chrome.tsx` | Preact owner for the primary nav, header preferences, pills, app-level error banner, and the top-level dashboard/history/settings view containers plus the typed shell bridge |
| `app/runtime/ui_shell_controller.ts` | Menu/view shell, language and preference hydration, and the reactive shell-chrome model that feeds header pills, feedback, and app-level banners |
| `app/runtime/ui_live_transport_controller.ts` | Demo/WebSocket transport coordinator that queues payloads through AppState, throttles live-session adaptation, and lets realtime, shell, and spectrum surfaces react from signal-backed state |
| `app/runtime/ui_spectrum_controller.ts` | Thin spectrum coordinator that splits heavy data refreshes from lighter settings-driven decoration refreshes while wiring overlay, canvas, interaction, and panel modules |
| `app/runtime/ui_startup_coordinator.ts` | Declarative startup-task runner that lets the shell own its initial bind/language/view boot while startup loads and transport start from a named sync/async plan |
| `app/runtime/ui_startup_feature_ports.ts` | Narrow startup-only feature contract for initial refresh/load work |
| `app/runtime/spectrum_canvas_renderer.ts` | Spectrum frame preparation, cached per-client display-series reuse, plot lifecycle, cadence-aware tween scheduling, stable uPlot buffer reuse for same-shape frames, and canvas draw plugin orchestration |
| `app/runtime/spectrum_interaction_controller.ts` | Spectrum focus, band-toggle, cursor, and legend/isolation interaction state with explicit ports plus throttled hover-inspector updates and announcement routing |
| `app/runtime/spectrum_panel_view.ts` | Typed spectrum panel contract for the signal-backed legend, band legend, split visual inspector vs live announcer, band-toggle, and chart-host refs |
| `app/app_feature_bundle.ts` | Creates concrete feature instances, then exposes explicit shell, transport, and startup port bundles back to the runtime |
| `app/features/` | Feature owners for state changes, API calls, shared polling control, and typed actions emitted from local view surfaces |
| `app/features/esp_flash_feature.ts` | Thin ESP flash facade that wires the workflow, presenter, typed island action bridge, and settings-view polling context together |
| `app/features/esp_flash_feature_workflow.ts` | DOM-free ESP flash workflow/controller for port refreshes, flash status polling, log/history hydration, and start/cancel orchestration |
| `app/features/cars_feature.ts` | Thin car-wizard facade that wires the DOM-free workflow plus island-owned wizard DOM adapter into typed wizard actions |
| `app/features/cars_feature_transport.ts` | Car-library transport wrapper for loading wizard brands, types, and models through the UI API facade |
| `app/features/cars_feature_workflow.ts` | DOM-free car-wizard workflow/controller for step transitions, library loading, branch selection, and finish validation |
| `app/features/realtime_feature.ts` | Thin realtime facade that wires the workflow, derived realtime view-state, and typed logging/sensor action bridges together |
| `app/features/realtime_feature_workflow.ts` | DOM-free realtime workflow/controller for polling, logging actions, location updates, and client mutations |
| `app/features/settings_cars_module.ts` | Settings-side car controller that owns list loading, activation/deletion flows, highlight feedback, and typed tab/view-driven feedback dismissal plus the explicit open-wizard port |
| `app/features/settings_cars_transport.ts` | Settings-car transport wrapper over load/activate/delete API calls |
| `app/features/settings_analysis_module.ts` | Analysis-settings behavior owner for validation, save/reset orchestration, field guidance, and spectrum refreshes behind the typed analysis-panel bridge |
| `app/features/settings_speed_source_module.ts` | Thin speed-source settings facade that wires the transport seam, DOM-free workflow, pure presenter, typed panel actions, and typed navigation subscriptions into the shared panel bridge |
| `app/features/settings_speed_source_transport.ts` | Speed-source settings transport wrapper over the UI-local settings and OBD APIs |
| `app/features/settings_speed_source_workflow.ts` | DOM-free speed-source workflow/controller for draft state, validation, save/load orchestration, and background OBD rescans |
| `app/views/analysis_panel.tsx` | Signal-backed Preact owner for the analysis-settings shell; local refs/effects handle guidance and field focus while analysis and car-selection modules feed typed model and availability updates |
| `app/views/settings_shell.tsx` | Preact owner for the shared settings tab chrome and tab-panel wrappers that mount the per-tab panel hosts, keep tab selection in signal-backed shell state, and expose typed settings navigation APIs |
| `app/views/esp_flash_panel.tsx` | Signal-backed Preact owner for the ESP flash settings shell, typed flash actions, and log-autoscroll lifecycle while feature/presenter code updates a semantic panel bridge |
| `app/views/internet_panel.tsx` | Signal-backed Preact owner for the full internet settings surface that renders USB status, transport choices, Wi-Fi credentials, and readiness guidance through a semantic panel bridge |
| `app/views/update_panel.tsx` | Signal-backed Preact owner for the full update settings surface that renders the action row plus current status, health, journey, issues, latest attempt, and log cards through a semantic panel bridge |
| `app/views/sensors_panel.tsx` | Signal-backed Preact owner for the sensors settings shell that keeps the sensor table reactive while exposing typed identify/remove/location callbacks to the realtime feature |
| `app/views/speed_source_panel.tsx` | Signal-backed Preact owner for the speed-source shell that renders the full tab plus live diagnostics in JSX, owns typed save/scan/select/input callbacks, and exposes semantic `setModel()` / `setDiagnostics()` bridge updates to the speed-source and GPS-status modules |
| `app/views/cars_panel.tsx` | Signal-backed Preact owner for the full car-management surface; it renders saved-car guidance/list rows, delegates wizard focus/return-focus/scroll lifecycle to the extracted wizard focus hook, and exposes typed list and wizard bridges |
| `app/views/cars_wizard_focus.ts` | Focus/ref owner for the add-car wizard that centralizes return-focus, scroll reset, requested-focus handling, and target resolution now that the wizard lifecycle lives beside the cars panel surface |
| `app/views/cars_wizard_panel.tsx` | Modal shell for the add-car wizard; it keeps dialog chrome and typed action wiring small while delegating step content to focused wizard sections |
| `app/views/cars_wizard_sections.tsx` | Extracted add-car wizard step sections, option grids, manual-spec inputs, and summary helpers that keep the main wizard panel readable while preserving the existing selectors and flow |
| `app/views/car_wizard_view.ts` | Typed add-car wizard render-model builders for progress, option sections, selected specs, and summary rows reused by the Preact car-management island |
| `app/features/update_feature.ts` | Thin update facade that binds typed island actions, delegates island render-model updates to the presenter, and derives update/internet polling context from the shell and settings tab state |
| `app/features/update_feature_workflow.ts` | DOM-free update workflow/controller for update polling, internet-status normalization, and start/cancel command orchestration |
| `app/features/history_feature.ts` | Single owner for history refresh, expanded-run/detail state, download/delete actions, collapsed-preview prefetch, and the typed panel render model |
| `app/features/history_download.ts` | Focused blob-download helper for the history PDF/report flow |
| `app/views/esp_flash_readiness_presenter.ts` | ESP flash readiness presenter that derives start-readiness, status-banner, selected-target, and recent-attempt summary models |
| `app/views/esp_flash_journey_presenter.ts` | ESP flash journey presenter that derives staged lifecycle progress and terminal stage state for the maintenance journey card |
| `app/views/esp_flash_feature_presenter.ts` | Top-level ESP flash presenter that composes journey, readiness, log, and history panel models for the island-owned ESP flash bridge |
| `app/views/history_table_models.ts` | Typed row/detail/finding/heatmap view models that describe history table rendering without HTML fragments |
| `app/views/history_heatmap_presenter.ts` | Heatmap presenter helpers that normalize location labels and turn preview intensity stats into typed history heatmap zones |
| `app/views/history_detail_presenter.ts` | Expanded history detail presenter that builds typed findings, warnings, and heatmap-backed diagnosis sections |
| `app/views/history_table_presenters.ts` | Top-level history row presenter that composes summary/collapsed row state and delegates expanded detail sections to focused history presenter modules |
| `app/views/history_panel.tsx` | Signal-backed Preact owner for the history panel shell that renders summary/toolbar chrome and binds typed row actions through a semantic bridge |
| `app/views/history_table_content.tsx` | History island JSX renderer that turns typed row/detail models into empty state, table rows, expanded evidence cards, and action affordances |
| `app/views/history_table_view.ts` | Thin history-panel bridge that defines the typed empty/table render contract consumed by the Preact history island |
| `app/views/realtime_capture_readiness_models.ts` | Typed capture-readiness helpers and checklist builders reused by realtime logging and sensor-health derivation |
| `app/views/realtime_logging_summary_models.ts` | Typed realtime logging summary-panel builders for blocked/setup/post-run states and CTA mapping |
| `app/views/realtime_logging_view_models.ts` | Thin realtime logging panel compositor and stable re-export surface over the focused readiness and summary builders |
| `app/views/realtime_live_overview.tsx` | Signal-backed Preact owner for the live overview card that consumes typed status/sensor models without manual island rerender loops |
| `app/views/realtime_logging_panel.tsx` | Signal-backed Preact owner for the run-recording card that renders typed logging/readiness models, owns the setup-layout marker locally, and binds start/stop plus summary CTA actions through the shared bridge |
| `app/views/settings_car_list_view.ts` | Typed saved-car list and guidance view-model builders reused by the car-management island for row, empty-state, and highlight rendering |
| `app/views/settings_speed_source_presenter.ts` | Pure speed-source presenter that turns typed workflow state and live status payloads into panel and diagnostics render models |
| `app/views/update_feature_presenter.ts` | Update presenter that derives typed update/internet panel models from workflow state plus draft form inputs and toggles |
| `app/views/internet_status_view.ts` | Pure USB-internet status model builder reused by the Preact internet panel |
| `app/views/update_status_models.ts` | Shared update-status badge, row, and section interfaces consumed by the update and internet panels |
| `app/views/update_journey_builder.ts` | Update journey and recovery-summary builders for phase formatting, staged progress, and retry guidance |
| `app/views/update_current_status_builders.ts` | Typed update-status builders for current status, issue list, and latest-attempt sections plus shared runtime/lifecycle rows |
| `app/views/update_health_status_builders.ts` | Typed update-health builders for degradation reasons, data-loss summaries, and persistence-analysis status |
| `app/views/update_log_status_builder.ts` | Typed update log-section builder for running, failed, and empty log states |
| `app/views/update_status_builders.ts` | Slim update-status panel assembler and re-export surface for the focused section builders |
| `app/views/maintenance_readiness_view.ts` | Shared maintenance-readiness model and Preact component contract reused by update and ESP flash readiness flows |
| `app/views/` | Focused render-model builders, event-target decoding, and signal-backed Preact surfaces for settings, cars wizard, realtime, history, and updater flows |
| `app/features/realtime_feature_view_state.ts` | Signal-backed realtime view-state owner that derives live overview, logging, and sensors models plus idle readiness signatures without presenter render fan-out |
| `transport/` | UI-local HTTP / WS DTOs plus adapter helpers that isolate generated contract files from app state and feature code |
| `api.ts` | REST API facade that returns local transport DTOs while `api/types.ts` stays the generated HTTP boundary |
| `ws.ts` | WebSocket client with auto-reconnect, stale detection, and direct writes into the signal-backed transport slice |
| `config.ts` | Centralized UI tuning constants for polling intervals, spectrum ranges, and history heatmap positions |
| `i18n.ts` | Internationalization dictionary (English, Dutch) |
| `spectrum.ts` | Shared spectrum math helpers such as amplitude-to-dB conversion that stay safe to import on the startup path |
| `spectrum_chart.ts` | Lazy-loaded uPlot chart wrapper, explicit `setData`/`redraw` bridge, and stylesheet entry for interactive spectrum visualization |
| `spectrum_css_vars.ts` | Shared cached spectrum CSS-variable snapshot for chart and canvas renderer colors |
| `server_payload.ts` | Transport-boundary WebSocket payload adaptation and schema-version guardrails around the generated WS types |
| `diagnostics.ts` | Strength band normalization and vibration matrix helpers |
| `vehicle_math.ts` | Tire diameter, order tolerance, and uncertainty calculations |
| `format.ts` | Number, byte, and timestamp formatting utilities |
| `constants.ts` | Generated sensor location codes and shared strength field names from backend sources |
| `theme.ts` | Chart color palette and order band fill colors |
| `styles/app.css` | Thin stylesheet aggregator that imports the UI style modules in cascade order |
| `styles/{tokens,shell,components,maintenance-*,realtime-*,history-*,settings-*,adaptive,theme}.css` | Shared tokens/primitives plus feature-scoped and cross-cutting style ownership for shell, updater, realtime, history, settings, responsive, and theme overrides |

- AppState top-level slices returned by `createAppState()` are reactive proxy stores. Existing feature/runtime code can keep object-style reads and writes, but any `computed()`/`effect()` that depends on a slice should call `trackAppStateSlice(slice)` (or read `getAppStateSliceSignal(slice).value`) and bulk multi-field writes should use `batchAppStateUpdates()`.

## Features

- **Live view** — multi-sensor spectrum chart and recording controls
- **History view** — recorded runs with insights, PDF download, ZIP export (CSV raw samples + JSON run details)
- **Settings view** — car profiles (tire/drivetrain wizard with car library), analysis parameters, speed source, sensor naming and location mapping
- **Auto theme** — follows system light/dark preference
- **Drive sizing** — larger touch targets on tablet viewports
- **Demo mode** — deterministic UI state via `?demo=1` for testing

The runtime layer is intentionally split so `ui_app_runtime.ts` stays a
composition root instead of becoming a single-file owner for transport, shell,
chart behavior, or page-wide DOM state. Startup now renders one `UiAppRoot`
tree up front, so the shared shell frame and the dashboard/history/settings
sections all live inside a single Preact render path instead of a multi-root
bootstrap layer. `ui_lazy_panels.ts` still gives the runtime typed panel
contracts immediately, but history/settings lazy loading is now just component
loading inside that one tree; only the settings subtree keeps its internal
tab-panel mount path so the per-tab settings panels can keep their existing
typed view bindings. The spectrum island owns its chart host refs internally
and passes that typed bridge to the runtime. `app_feature_bundle.ts` creates
the concrete features, wires explicit cross-feature ports, and returns only the
shell, transport, and startup contracts the runtime needs, while
`ui_startup_coordinator.ts` runs the startup-only load/refresh ports from a
small declarative sync/async plan instead of a handwritten boot call chain.
`startUiApp()` now returns a public dispose handle, and that top-level teardown
flows through `ui_app_runtime.ts` to stop long-lived effects, polling loops,
WebSocket reconnect/stale timers, spectrum RAF work, and deferred settings
panel bindings from one place.

The live UI architecture is now fully Preact for the top-level shell and
primary page composition. `app/runtime/ui_shell_chrome.tsx` owns the primary
navigation, header preferences, pills, and app banner; `app/ui_app_root.tsx`
owns the top-level view sections; `app/views/settings_shell.tsx`
owns the shared settings tab strip and per-tab host wrappers; and the
individual page/settings panel islands own their local chrome plus typed
bridges. The remaining
imperative paths are deliberate runtime integrations rather than alternate UI
renderers: the shell controller still owns app-level status/preference state,
the spectrum controller still owns the uPlot/canvas lifecycle through
island-owned chart refs, and a few focused bridges still move typed wizard or
status models into island-owned hosts. Those seams should use semantic methods
like `setModel()` / `setDiagnostics()` rather than generic `render(model)`
loops.

Realtime follows that same split explicitly: `realtime_feature.ts` is the thin
facade, `realtime_feature_workflow.ts` owns the controller-style polling,
mutation flow, and signal-backed workflow state, `realtime_feature_view_state.ts`
derives the live overview/logging/sensors models plus idle readiness signatures
from shared AppState slices, `app/views/realtime_live_overview.tsx` and
`app/views/realtime_logging_panel.tsx` consume bound model signals inside their
signal-backed islands, `realtime_capture_readiness_models.ts` owns the
readiness/checklist helpers, `realtime_logging_summary_models.ts` owns the
logging summary-panel builders, and `realtime_logging_view_models.ts` stays the
top-level logging panel compositor and stable re-export surface reused by that
derived state. `app/views/` now owns typed view-model builders, event-target
decoding, and signal-backed Preact surfaces for reusable multi-action panels.

`src/transport/` owns transport-specific helpers such as clone and live-model
surfaces, while `api/types.ts` owns generated HTTP alias exports used across
`api/**`, `app/**`, and tests. Generated contract files themselves stay out of
those consumers. Styling follows same ownership split: `styles/app.css` is only
the import aggregator, `tokens.css`/`theme.css` own global token and color-mode
concerns, and `shell.css`, `components.css`, `maintenance*.css`,
`realtime*.css`, `history*.css`, and `settings-*.css` own the shared and
feature-specific surfaces directly.
Shared visual state conventions prefer stable data/ARIA selectors such as
`data-variant`, `data-choice-state`, `data-selected`, and `data-step-state`
instead of controller-side variant class interpolation.

## Shared reactive state contract

- Import shared reactive primitives from `app/ui_signals.ts` so runtime,
  feature, presenter, and view code shares one documented signals entrypoint.
- Use `signal()` for shared state that spans modules or needs to outlive a
  single component render. Keep component-local transient state in hooks.
- Use `computed()` for derived state instead of mirroring derived fields onto
  mutable state bags or manual render-model caches.
- Inside Preact components, prefer `useComputed()`, `useSignal()`, and
  `useSignalEffect()` over ad-hoc local refs or render-time signal reads when a
  hook-scoped reactive owner is clearer.
- When several JSX bindings unwrap stable properties from the same model signal,
  prefer `useSignalProperties()` from `app/ui_signals.ts` over repeating one
  `useComputed(() => model.value.foo)` line per property.
- Use `effect()` only for narrow imperative integrations such as timers,
  persistence, canvas/uPlot bridges, or other external-library coordination.
- Preact-rendered copy should come from `getUiText()` or `useUiText()`.
  Do not leave `data-i18n` attributes in JSX unless a non-Preact consumer still
  reads them.
- Existing mutable app-state objects and manual bridge rerenders are follow-up
  migration residue, not the default pattern for new frontend work.

## Architecture guardrails

- `app/dom/**` plus focused runtime/view helpers own island-host lookup and the
  remaining imperative DOM seams. Feature, runtime, and presenter modules
  should receive typed bridges or focused DOM surfaces instead of rebuilding
  page-wide registries or ad hoc `document.getElementById(...)` lookups.
- Generated HTTP / WS contracts stay behind narrow UI-owned seams. The approved
  generated-contract seams are the `api/*.ts` HTTP wrappers plus `api/types.ts`,
  `transport/live_models.ts`, `server_payload.ts`, `ws.ts`, and
  `ws_payload_validator.ts`; `app/**` code may import `transport/**` and
  `api/types.ts`, but not generated contract files directly.
- Normal UI rendering belongs in Preact owner surfaces. If code outside an
  island needs imperative DOM work, keep it narrowly scoped to non-render
  integrations such as download anchors, canvas/uPlot lifecycles, observers, or
  external-library mount points instead of generic HTML/string builder helpers.
- Expected feature shape is thin facade + focused workflow/transport/presenter
  or derived view-state modules. Workflow modules stay DOM-free, render-state
  derivation lives in one focused owner, and view surfaces decode local DOM
  events into typed actions for the owning feature.
- Mount Preact owner surfaces directly inside their owning runtime/view module.
  Do not scatter `preact.render(...)` calls across feature or presenter code.

## WebSocket contract boundary

- `src/contracts/ws_payload_schema.json` defines the JSON Schema for live WS payloads.
- `src/contracts/ws_payload_types.ts` is generated from that schema by the
  [contract sync flow](#contract-sync).
- `src/ws_payload_validator.ts` validates raw live payloads with Valibot schemas, while the large spectrum-number arrays stay on a custom finite-number-array guard so the live chart path avoids per-element schema object churn.
- `src/server_payload.ts` then adapts the validated `LiveWsPayload` with schema-version warnings, shared-`freq` fallback, and malformed/misaligned spectrum rejection.

Valibot-backed runtime validation now sits at the WebSocket boundary. Live payloads must satisfy the generated contract shape directly before the app-state adapter accepts them. The remaining UI-side handling is limited to current, explicit adapter behavior: schema-version warning logging, shared-`freq` fallback when the canonical shared axis is used, and dropping spectrum series that still cannot produce aligned bins for rendering.

Top-level `LiveWsPayload` fields:

- `schema_version` — current live-payload contract version.
- `server_time` — server UTC timestamp for the tick.
- `speed_mps` — resolved vehicle speed, or `null` when unavailable.
- `clients` — current lightweight client snapshots (connectivity, identity, latest metrics metadata).
- `selected_client_id` — the client whose heavier per-sensor detail the UI is currently focused on, or `null`.
- `rotational_speeds` — derived wheel/driveshaft/engine speed estimates and current order-band context, or `null`.
- `spectra` — heavier FFT payload data; omitted on light ticks and present on heavy ticks.

Server-side WebSocket error frames are separate from `LiveWsPayload`. The
current error payload is `{"error": "payload_build_failed"}`, which indicates
the backend could not assemble the live update tick and sent an explicit error
frame instead of the normal payload.

## Visual Tests

Playwright snapshot tests default to one intentional regression target:

| Viewport | Theme | Command |
|----------|-------|---------|
| Laptop (1280x800) | Light | `npm run test:visual` |

Use the broader visual audit sweep only on purpose:

| Viewport | Theme | Command |
|----------|-------|---------|
| Laptop (1280x800) | Light | `npm run test:visual:audit` |
| Laptop (1280x800) | Dark | `npm run test:visual:audit` |
| Tablet (768x1024) | Light | `npm run test:visual:audit` |
| Tablet (768x1024) | Dark | `npm run test:visual:audit` |

```bash
npx playwright install chromium   # first time only
npm run test:visual               # compare against baselines
npm run test:visual:update        # regenerate after intentional changes
npm run test:visual:audit         # run wider multi-viewport audit on purpose
```

Baselines live in `tests/snapshots/`. Tests use demo mode for deterministic
payloads. The default lane stays on `laptop-light`; the audit command keeps the
older multi-viewport sweep available when broader visual review is worth the
cost. Both visual commands only run `tests/visual.spec.ts`.

## Signal-driven island tests

- Prefer `tests/dom_render_test_support.ts::mountSignalView()` for isolated
  island tests. It installs an isolated DOM, mounts the Preact view once, and
  returns a typed bridge plus deterministic cleanup.
- Drive island state with `signal()` and `computed()` inputs instead of
  rebuilding the old `render(model)` fixture pattern.
  `tests/signal_view_reference_tests.ts` contains the reference panel coverage
  for direct signal JSX bindings, computed-driven output assertions, and
  effect-backed subscription seams.
- Run `npm run test:signals` to execute the reference signal-view coverage
  directly in Node with the same helper path used by future isolated island
  tests.
- Use `tests/async_test_helpers.ts::flushSignalUpdates()` after mutating signals
  or when waiting on effect-owned side effects.
  The same reference file also covers an effect-backed subscription seam through
  `mountSettingsShell()`.
- `createPanel()` and the raw fake-element builders remain only for legacy
  bridge-style feature fixtures such as `tests/esp_flash_feature.spec.ts`.
  Do not start new island tests from that pattern.

## Design Language

The UI follows the design system documented in
[docs/design_language.md](../../docs/design_language.md) — purple accent, minimal
flat aesthetic, token-driven styling.
