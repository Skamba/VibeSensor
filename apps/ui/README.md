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
npm run dev          # Dev server on http://localhost:5173
npm run dev:open     # Same dev server, but opens the browser on local desktops
npm run dev:docker   # Docker-oriented wrapper: contract check + guarded npm ci + Vite
npm run build        # Production build to dist/
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

## Code Quality

- `npm run lint` checks the hand-written TypeScript, config, and support scripts
  with Biome.
- `npm run format` rewrites the supported files when you want to apply the repo
  UI formatting locally.

Generated contract artifacts stay out of the lint/format path on purpose so the
source-of-truth export commands remain the only writers for those files.

## Source Modules

| File | Purpose |
|------|---------|
| `main.ts` | Thin Vite entry that boots the UI runtime |
| `app/start_ui_app.ts` | CSS-aware startup entry that mounts the Preact shell chrome, resolves and mounts the centralized panel bootstrap, then constructs and starts the app runtime |
| `app/ui_panel_host_registry.ts` | Centralized host registry for dashboard, history, and settings panel mount points so startup and tests stop depending on one host getter module per panel |
| `app/ui_panel_bootstrap.ts` | Centralized host registry and panel-mount bootstrap for dashboard, history, and settings islands so startup/runtime stop wiring one host getter per panel |
| `app/dom/` | Focused DOM lookup helpers that remain after the panel bootstrap cleanup, including `requiredById` and other non-panel runtime locators |
| `app/ui_app_runtime.ts` | UI composition root that wires state, feature-scoped DOM locators, focused runtime controllers, and explicit feature port bundles |
| `app/ui_app_state.ts` | Canonical AppState shape plus reactive slice helpers that keep object-style reads/writes working while shared shell/transport/realtime/history/settings/spectrum state becomes signal-observable |
| `app/ui_signals.ts` | Canonical re-export surface for shared `signal`, `computed`, and `effect` usage across runtime, features, and views |
| `app/runtime/ui_preact_mount.ts` | Canonical helper for mounting and disposing incremental Preact islands inside existing DOM hosts |
| `app/runtime/ui_shell_chrome.tsx` | Preact owner for the primary nav, header preferences, pills, and app-level error banner plus the typed shell chrome bridge |
| `app/runtime/ui_shell_controller.ts` | Menu/view shell, language and preference hydration, and the reactive shell-chrome model that feeds header pills, feedback, and app-level banners |
| `app/runtime/ui_live_transport_controller.ts` | Demo/WebSocket transport coordinator that queues payloads through AppState, throttles live-session adaptation, and lets shell/spectrum react from signal-backed state |
| `app/runtime/ui_spectrum_controller.ts` | Thin spectrum coordinator that wires overlay updates plus the extracted canvas, interaction, and panel modules |
| `app/runtime/spectrum_canvas_renderer.ts` | Spectrum frame preparation, plot lifecycle, tweening, and canvas draw plugin orchestration |
| `app/runtime/spectrum_interaction_controller.ts` | Spectrum focus, band-toggle, cursor, and legend/isolation interaction state with explicit ports |
| `app/runtime/spectrum_panel_view.ts` | Typed spectrum panel contract for the signal-backed legend, band legend, inspector, band-toggle, and chart-host refs |
| `app/app_feature_bundle.ts` | Creates concrete feature instances, then exposes explicit shell, transport, and startup port bundles back to the runtime |
| `app/features/` | Feature owners for state changes, API calls, shared polling control, and typed actions emitted from local view binders |
| `app/features/esp_flash_feature.ts` | Thin ESP flash facade that wires the workflow, presenter, and typed island action bridge together |
| `app/features/esp_flash_feature_workflow.ts` | DOM-free ESP flash workflow/controller for port refreshes, flash status polling, log/history hydration, and start/cancel orchestration |
| `app/features/cars_feature.ts` | Thin car-wizard facade that wires the DOM-free workflow plus island-owned wizard DOM adapter into typed wizard actions |
| `app/features/cars_feature_transport.ts` | Car-library transport wrapper for loading wizard brands, types, and models through the UI API facade |
| `app/features/cars_feature_workflow.ts` | DOM-free car-wizard workflow/controller for step transitions, library loading, branch selection, and finish validation |
| `app/features/realtime_feature.ts` | Thin realtime facade that wires the workflow, presenter, and typed logging/sensor action bridges together |
| `app/features/realtime_feature_workflow.ts` | DOM-free realtime workflow/controller for polling, logging actions, location updates, and client mutations |
| `app/features/settings_cars_module.ts` | Settings-side car controller that owns list loading, activation/deletion flows, highlight feedback, and typed tab/view-driven feedback dismissal plus the explicit open-wizard port |
| `app/features/settings_cars_transport.ts` | Settings-car transport wrapper over load/activate/delete API calls |
| `app/features/settings_analysis_module.ts` | Analysis-settings behavior owner for validation, save/reset orchestration, field guidance, and spectrum refreshes behind the typed analysis-panel bridge |
| `app/features/settings_speed_source_module.ts` | Thin speed-source settings facade that wires the transport seam, DOM-free workflow, pure presenter, typed panel actions, and typed navigation subscriptions into the shared panel bridge |
| `app/features/settings_speed_source_transport.ts` | Speed-source settings transport wrapper over the UI-local settings and OBD APIs |
| `app/features/settings_speed_source_workflow.ts` | DOM-free speed-source workflow/controller for draft state, validation, save/load orchestration, and background OBD rescans |
| `app/views/analysis_panel.tsx` | Signal-backed Preact owner for the analysis-settings shell; local refs/effects handle guidance and field focus while analysis and car-selection modules feed typed model and availability updates |
| `app/views/settings_shell.tsx` | Preact owner for the shared settings tab chrome and tab-panel wrappers that mount the per-tab panel hosts, keep tab selection in signal-backed shell state, and expose typed settings navigation APIs |
| `app/views/esp_flash_panel.tsx` | Preact owner for the ESP flash settings shell, typed flash actions, and log-autoscroll lifecycle alongside the render bridge for port selection, readiness, journey, history, and logs |
| `app/views/internet_panel.tsx` | Preact owner for the full internet settings surface that renders USB status, transport choices, Wi-Fi credentials, and readiness guidance through a typed bridge |
| `app/views/update_panel.tsx` | Preact owner for the full update settings surface that renders the action row plus current status, health, journey, issues, latest attempt, and log cards through a typed bridge |
| `app/views/sensors_panel.tsx` | Signal-backed Preact owner for the sensors settings shell that keeps the sensor table reactive while exposing typed identify/remove/location callbacks to the realtime feature |
| `app/views/speed_source_panel.tsx` | Preact owner for the speed-source shell that renders the full tab plus live diagnostics in JSX, owns typed save/scan/select/input callbacks, and exposes the shared bridge consumed by the speed-source and GPS-status modules |
| `app/views/cars_panel.tsx` | Signal-backed Preact owner for the full car-management surface; it renders saved-car guidance/list rows plus the full add-car wizard in JSX, owns wizard focus/return-focus/scroll lifecycle locally, and exposes typed list and wizard bridges |
| `app/views/cars_feature_presenter.ts` | Thin car-wizard presenter that turns workflow state into typed wizard render models and delegates focus/manual-input access through the island bridge |
| `app/views/car_wizard_view.ts` | Typed add-car wizard render-model builders for progress, option sections, selected specs, and summary rows reused by the Preact car-management island |
| `app/features/update_feature.ts` | Thin update facade that binds typed island actions, delegates island render-model updates to the presenter, and delegates update commands to the workflow |
| `app/features/update_feature_workflow.ts` | DOM-free update workflow/controller for update polling, internet-status normalization, and start/cancel command orchestration |
| `app/features/history_feature.ts` | Single owner for history refresh, expanded-run/detail state, download/delete actions, collapsed-preview prefetch, and the typed panel render model |
| `app/features/history_download.ts` | Focused blob-download helper for the history PDF/report flow |
| `app/views/esp_flash_feature_presenter.ts` | ESP flash presenter that derives typed panel models for the island-owned ESP flash bridge while leaving workflow state in the feature workflow |
| `app/views/history_table_models.ts` | Typed row/detail/finding/heatmap view models that describe history table rendering without HTML fragments |
| `app/views/history_table_presenters.ts` | Presenter builders that turn runs plus loaded insights/preview detail into typed history row and details models |
| `app/views/history_panel.tsx` | Preact owner for the history panel shell that renders summary/toolbar chrome and binds typed row actions through a bridge |
| `app/views/history_table_content.tsx` | History island JSX renderer that turns typed row/detail models into empty state, table rows, expanded evidence cards, and action affordances |
| `app/views/history_table_view.ts` | Thin history-panel bridge that defines the typed empty/table render contract consumed by the Preact history island |
| `app/views/realtime_logging_view_models.ts` | Typed realtime logging and readiness view-model builders for summary, checklist, and control-state derivation |
| `app/views/realtime_live_overview.tsx` | Signal-backed Preact owner for the live overview card that consumes typed status/sensor models without manual island rerender loops |
| `app/views/realtime_logging_panel.tsx` | Signal-backed Preact owner for the run-recording card that renders typed logging/readiness models, owns the setup-layout marker locally, and binds start/stop plus summary CTA actions through the shared bridge |
| `app/views/settings_car_list_view.ts` | Typed saved-car list and guidance view-model builders reused by the car-management island for row, empty-state, and highlight rendering |
| `app/views/settings_speed_source_presenter.ts` | Pure speed-source presenter that turns typed workflow state and live status payloads into panel and diagnostics render models |
| `app/views/update_feature_presenter.ts` | Update presenter that derives typed update/internet panel models from workflow state plus draft form inputs and toggles |
| `app/views/internet_status_view.ts` | Pure USB-internet status model builder reused by the Preact internet panel |
| `app/views/update_status_view_models.ts` | Typed update-status section builders for current status, journey, issues, attempt history, health, and log cards |
| `app/views/maintenance_readiness_view.ts` | Shared maintenance-readiness model and Preact component contract reused by update and ESP flash readiness flows |
| `app/views/` | Focused render-model builders, event-target decoding, and disposable delegated event binders for settings, cars wizard, realtime, history, and updater surfaces |
| `app/views/realtime_feature_presenter.ts` | Realtime presenter that owns derived live/logging panel state, elapsed-timer sync, and cross-view navigation clicks |
| `transport/` | UI-local HTTP / WS DTOs plus adapter helpers that isolate generated contract files from app state and feature code |
| `api.ts` | REST API facade that returns local transport DTOs while `api/types.ts` stays the generated HTTP boundary |
| `ws.ts` | WebSocket client with auto-reconnect, stale detection, and direct writes into the signal-backed transport slice |
| `config.ts` | Centralized UI tuning constants for polling intervals, spectrum ranges, and history heatmap positions |
| `i18n.ts` | Internationalization dictionary (English, Dutch) |
| `spectrum.ts` | uPlot chart wrapper for interactive spectrum visualization |
| `server_payload.ts` | Transport-boundary WebSocket payload adaptation and schema-version guardrails around the generated WS types |
| `diagnostics.ts` | Strength band normalization and vibration matrix helpers |
| `vehicle_math.ts` | Tire diameter, order tolerance, and uncertainty calculations |
| `format.ts` | Number, byte, and timestamp formatting utilities |
| `constants.ts` | Generated sensor location codes and shared strength field names from backend sources |
| `theme.ts` | Chart color palette and order band fill colors |
| `styles/app.css` | Thin stylesheet aggregator that imports the UI style modules in cascade order |
| `styles/{tokens,shell,components,maintenance,realtime,history,settings,adaptive,theme}.css` | Shared tokens/primitives plus feature-scoped and cross-cutting style ownership for shell, updater, realtime, history, settings, responsive, and theme overrides |

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
chart behavior, or page-wide DOM state. Startup mounts the live Preact owner
surfaces first — shell chrome, dashboard/history shells, the shared settings
shell, and the per-settings-tab panel hosts. The spectrum island now owns the
chart host refs internally and passes that typed bridge to the runtime.
`app_feature_bundle.ts` creates the concrete features, wires explicit
cross-feature ports, and returns only the shell, transport, and startup
contracts the runtime needs.

The live UI architecture is now fully Preact for every page, tab, and
feature surface.
`app/runtime/ui_shell_chrome.tsx` owns the primary navigation, header
preferences, pills, and app banner; `app/views/settings_shell.tsx` owns the
shared settings tab strip and panel wrappers; and the individual page/settings
panel islands own their local chrome plus typed bridges. The remaining
imperative paths are deliberate runtime integrations rather than alternate UI
renderers: the shell controller still owns app-level status/preference state,
the spectrum controller still owns the uPlot/canvas lifecycle through
island-owned chart refs, and a few follow-up migration issues still materialize
typed wizard or status models behind island-owned hosts. Those transitional
bridge patterns should not be copied into new work now that the signals
contract below is available.

Realtime follows that same split explicitly: `realtime_feature.ts` is the thin
facade, `realtime_feature_workflow.ts` owns the controller-style polling and
mutation flow, `realtime_feature_presenter.ts` owns realtime-specific panel
state plus typed navigation actions, `app/views/realtime_live_overview.tsx`
and `app/views/realtime_logging_panel.tsx` keep the dashboard cards in
signal-backed island state, and `realtime_logging_view_models.ts` builds the
logging/readiness models consumed by the recording card. `app/views/` now owns
typed view-model builders, event-target decoding, and disposable delegated
listener binders for reusable multi-action panels.

`src/transport/` owns the UI-local DTO and adapter layer between generated HTTP
/ WS contracts and `app/**`, so feature, runtime, and view modules no longer
need to import `api/types.ts` or generated WS contract files directly. Styling
follows the same ownership split: `styles/app.css` is only the import
aggregator, `tokens.css`/`theme.css` own global token and color-mode concerns,
and `shell.css`, `components.css`, `maintenance.css`, `realtime.css`,
`history.css`, and `settings.css` own the shared and feature-specific surfaces.
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
- Use `effect()` only for narrow imperative integrations such as timers,
  persistence, canvas/uPlot bridges, or other external-library coordination.
- Preact-rendered copy comes from `useUiTranslation()`. Do not leave
  `data-i18n` attributes in JSX unless a non-Preact consumer still reads them.
- Existing mutable app-state objects and manual bridge rerenders are follow-up
  migration residue, not the default pattern for new frontend work.

## Architecture guardrails

- `app/dom/**` plus focused runtime/view helpers own island-host lookup and the
  remaining imperative DOM seams. Feature, runtime, and presenter modules
  should receive typed bridges or focused DOM surfaces instead of rebuilding
  page-wide registries or ad hoc `document.getElementById(...)` lookups.
- Generated HTTP / WS contracts stay behind the transport boundary. The approved
  generated-contract seams are the `api/*.ts` HTTP wrappers plus `api/types.ts`,
  `transport/http_models.ts`, `transport/live_models.ts`, `server_payload.ts`,
  `ws.ts`, and `ws_payload_validator.ts`; `app/**` code imports `transport/**`,
  not generated contract files or `api/types.ts`.
- Normal UI rendering belongs in Preact owner surfaces. If code outside an
  island needs imperative DOM work, keep it narrowly scoped to non-render
  integrations such as download anchors, canvas/uPlot lifecycles, observers, or
  external-library mount points instead of generic HTML/string builder helpers.
- Expected feature shape is thin facade + focused workflow/transport/presenter or
  binding modules. Workflow modules stay DOM-free, presenters own rendering, and
  bindings decode DOM events into typed actions for the owning feature.
- Preact owner surfaces mount through `app/runtime/ui_preact_mount.ts`; do not
  scatter raw `preact.render(...)` calls across feature modules.

## WebSocket contract boundary

- `src/contracts/ws_payload_schema.json` defines the JSON Schema for live WS payloads.
- `src/contracts/ws_payload_types.ts` is generated from that schema by the
  [contract sync flow](#contract-sync).
- `src/ws_payload_validator.ts` compiles AJV against `ws_payload_schema.json` and validates raw live payloads at runtime.
- `src/server_payload.ts` then adapts the validated `LiveWsPayload` with schema-version warnings, shared-`freq` fallback, and malformed/misaligned spectrum rejection.

AJV-backed runtime validation now sits at the WebSocket boundary. Live payloads must satisfy that JSON Schema directly before the app-state adapter accepts them. The remaining UI-side handling is limited to current, explicit adapter behavior: schema-version warning logging, shared-`freq` fallback when the canonical shared axis is used, and dropping spectrum series that still cannot produce aligned bins for rendering.

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

Playwright snapshot tests capture the UI across 4 viewports:

| Viewport | Theme |
|----------|-------|
| Laptop (1280x800) | Light |
| Laptop (1280x800) | Dark |
| Tablet (768x1024) | Light |
| Tablet (768x1024) | Dark |

```bash
npx playwright install chromium   # first time only
npm run test:visual               # compare against baselines
npm run test:visual:update        # regenerate after intentional changes
npm run wiki:screenshots          # capture release/wiki screenshots (build dist first)
```

Baselines live in `tests/snapshots/`. Tests use demo mode for deterministic payloads.

The release/wiki screenshot flow is separate from the visual-regression baselines.
It runs `tests/wiki_screenshots.spec.ts` through `playwright.wiki.config.ts` and
captures a curated laptop-light set of product screenshots with realistic seeded
data for Live, History, Cars, Analysis, and Speed Source. Release CI publishes
only these screenshot assets into the existing GitHub wiki; the wiki markdown
pages are seeded manually.

## Design Language

The UI follows the design system documented in
[docs/design_language.md](../../docs/design_language.md) — purple accent, minimal
flat aesthetic, token-driven styling.
