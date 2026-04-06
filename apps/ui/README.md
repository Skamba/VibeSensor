# Web UI

Single-page TypeScript application that provides real-time vibration monitoring,
sensor management, run history, and car configuration. Communicates with the Pi
server over HTTP (REST) and WebSocket (live data).

## Tech Stack

- **TypeScript** — application logic
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

`npm run check:contracts` is the lightweight derivative-only guard used by Node-only flows like `pretypecheck`, `prebuild`, and `dev:docker`. CI contract drift and human-facing regeneration should use `make sync-contracts`.

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
| `app/start_ui_app.ts` | CSS-aware startup entry that constructs and starts the app runtime |
| `app/ui_runtime_dom.ts` | Startup bundle that resolves feature-scoped DOM locators and fails early when required feature anchors are missing |
| `app/dom/` | Feature-scoped DOM locator modules for shell, spectrum, realtime, history, settings, cars, update, and ESP flash surfaces |
| `app/ui_app_runtime.ts` | UI composition root that wires state, feature-scoped DOM locators, focused runtime controllers, and explicit feature port bundles |
| `app/runtime/ui_shell_controller.ts` | Menu/view shell, language and preference hydration, connection pill/banner, and other chrome state |
| `app/runtime/ui_live_transport_controller.ts` | Demo/WebSocket transport, payload adaptation, and throttled live-session rendering |
| `app/runtime/ui_spectrum_controller.ts` | Thin spectrum coordinator that wires overlay updates plus the extracted canvas, interaction, and panel modules |
| `app/runtime/spectrum_canvas_renderer.ts` | Spectrum frame preparation, plot lifecycle, tweening, and canvas draw plugin orchestration |
| `app/runtime/spectrum_interaction_controller.ts` | Spectrum focus, band-toggle, cursor, and legend/isolation interaction state with explicit ports |
| `app/runtime/spectrum_panel_view.ts` | Spectrum legend, band legend, inspector, and band-toggle DOM rendering with button reuse |
| `app/app_feature_bundle.ts` | Creates concrete feature instances, then exposes explicit shell, transport, and startup port bundles back to the runtime |
| `app/features/` | Feature owners for state changes, API calls, shared polling control, and typed actions emitted from local view binders |
| `app/features/esp_flash_feature.ts` | Thin ESP flash facade that wires the workflow, presenter, and feature-local bindings together |
| `app/features/esp_flash_feature_workflow.ts` | DOM-free ESP flash workflow/controller for port refreshes, flash status polling, log/history hydration, and start/cancel orchestration |
| `app/features/cars_feature.ts` | Thin car-wizard facade that wires the DOM-free workflow, presenter, and typed wizard bindings together |
| `app/features/cars_feature_transport.ts` | Car-library transport wrapper for loading wizard brands, types, and models through the UI API facade |
| `app/features/cars_feature_workflow.ts` | DOM-free car-wizard workflow/controller for step transitions, library loading, branch selection, and finish validation |
| `app/features/realtime_feature.ts` | Thin realtime facade that wires the workflow, presenter, and delegated event bindings together |
| `app/features/realtime_feature_workflow.ts` | DOM-free realtime workflow/controller for polling, logging actions, location updates, and client mutations |
| `app/features/settings_cars_module.ts` | Settings-side car controller that owns list loading, activation/deletion flows, highlight feedback, and the explicit open-wizard port |
| `app/features/settings_cars_transport.ts` | Settings-car transport wrapper over load/activate/delete API calls |
| `app/features/settings_speed_source_module.ts` | Thin speed-source settings facade that wires the transport seam, DOM-free workflow, presenter, and typed bindings together |
| `app/features/settings_speed_source_transport.ts` | Speed-source settings transport wrapper over the UI-local settings and OBD APIs |
| `app/features/settings_speed_source_workflow.ts` | DOM-free speed-source workflow/controller for draft state, validation, save/load orchestration, and background OBD rescans |
| `app/views/cars_feature_bindings.ts` | Typed car-wizard bindings for open/close/step/manual-input actions without leaving raw DOM parsing in the feature |
| `app/views/cars_feature_presenter.ts` | Car-wizard presenter that owns dialog visibility, step rendering, summary updates, and focus targets from workflow state |
| `app/features/update_feature.ts` | Thin update facade that binds DOM events, delegates state rendering to the presenter, and delegates update commands to the workflow |
| `app/features/update_feature_workflow.ts` | DOM-free update workflow/controller for update polling, internet-status normalization, and start/cancel command orchestration |
| `app/views/dom_render.ts` | Shared low-level DOM render helper for fragments, element creation, text updates, and class-state toggles |
| `app/views/esp_flash_feature_bindings.ts` | Feature-local ESP flash bindings for start/cancel/refresh/select actions without leaving raw DOM event parsing in the feature |
| `app/views/esp_flash_feature_presenter.ts` | ESP flash presenter that owns readiness/banner/journey/history/log/select rendering from workflow state |
| `app/views/history_table_models.ts` | Typed row/detail/finding/heatmap view models that describe history table rendering without HTML fragments |
| `app/views/history_table_presenters.ts` | Presenter builders that turn runs plus loaded insights/preview detail into typed history row and details models |
| `app/views/history_table_row_renderers.ts` | Focused history row/detail DOM builders that materialize typed history models into table rows and expanded evidence cards |
| `app/views/history_table_view.ts` | Thin history-table view boundary that renders DOM rows/empty state and decodes typed table interactions |
| `app/views/realtime_logging_view_models.ts` | Typed realtime logging and readiness view-model builders for summary, checklist, and control-state derivation |
| `app/views/realtime_logging_view.ts` | Dedicated realtime logging/readiness DOM renderer built from typed view-model objects |
| `app/views/settings_cars_presenter.ts` | Settings-car presenter that owns car-list rendering, active-car guidance, and analysis-control affordances from typed car state |
| `app/views/settings_speed_source_bindings.ts` | Typed speed-source form bindings that decode radio/input/navigation/device actions away from the workflow |
| `app/views/settings_speed_source_presenter.ts` | Speed-source presenter that owns summary, validation, and OBD-device-list DOM rendering from typed workflow state |
| `app/views/update_feature_presenter.ts` | Update presenter that owns readiness derivation, transport/control DOM state, and typed handoff into the update status/internet panels |
| `app/views/update_status_view.ts` | Thin update-status coordinator that assembles typed section models into the settings update panel |
| `app/views/update_status_view_models.ts` | Typed update-status section builders for current status, journey, issues, attempt history, health, and log cards |
| `app/views/update_status_overview_view.ts` | Focused current-status and journey card renderers built from typed section inputs |
| `app/views/update_status_history_view.ts` | Focused issues and latest-attempt card renderers for update history and failure context |
| `app/views/update_status_health_view.ts` | Dedicated background-service health card renderer for the update panel |
| `app/views/update_status_log_view.ts` | Dedicated updater log card renderer for empty, running, and populated log states |
| `app/views/` | Focused DOM rendering, render-helper composition, event-target decoding, and disposable delegated event binders for settings, cars wizard, realtime, history, and update panels |
| `app/views/realtime_feature_presenter.ts` | Realtime presenter that owns derived panel state, DOM rendering, elapsed-timer sync, and cross-view navigation clicks |
| `transport/` | UI-local HTTP / WS DTOs plus adapter helpers that isolate generated contract files from app state and feature code |
| `api.ts` | REST API facade that returns local transport DTOs while `api/types.ts` stays the generated HTTP boundary |
| `ws.ts` | WebSocket client with auto-reconnect and stale detection |
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

## Features

- **Live view** — multi-sensor spectrum chart and recording controls
- **History view** — recorded runs with insights, PDF download, ZIP export (CSV raw samples + JSON run details)
- **Settings view** — car profiles (tire/drivetrain wizard with car library), analysis parameters, speed source, sensor naming and location mapping
- **Auto theme** — follows system light/dark preference
- **Drive sizing** — larger touch targets on tablet viewports
- **Demo mode** — deterministic UI state via `?demo=1` for testing

The runtime layer is intentionally split so `ui_app_runtime.ts` stays a
composition root instead of becoming a single-file owner for transport, shell,
chart behavior, or page-wide DOM state. Startup resolves feature-scoped DOM
locators once in `ui_runtime_dom.ts`, then passes those local surfaces into the
owning runtime controllers and into `app_feature_bundle.ts`. That bundle
creates the concrete features, wires their explicit cross-feature ports, and
returns only the shell, transport, and startup contracts the runtime needs.
Realtime now follows that same split explicitly: `realtime_feature.ts` is the
thin facade, `realtime_feature_workflow.ts` owns the controller-style polling
and mutation flow, and `realtime_feature_presenter.ts` owns realtime-specific
DOM rendering and navigation actions. The logging/readiness subsection is now
further split so `realtime_logging_view_models.ts` owns the typed summary /
checklist / readiness models and `realtime_logging_view.ts` owns the DOM
rendering for those models.
`app/views/` still owns focused HTML rendering helpers, the shared low-level DOM
render helper, typed event-target decoding, and disposable delegated listener
binders for reusable multi-action panels.
`src/transport/` owns the UI-local DTO and adapter layer between generated HTTP /
WS contracts and `app/**`, so feature, runtime, and view modules no longer need
to import `api/types.ts` or generated WS contract files directly.
Styling now follows the same ownership split: `styles/app.css` is only the
import aggregator, `tokens.css`/`theme.css` own global token and color-mode
concerns, `shell.css` and `components.css` own shared chrome/primitives, and
`maintenance.css`, `realtime.css`, `history.css`, and `settings.css` own the
feature surfaces. Shared visual state conventions now prefer stable data/ARIA
selectors such as `data-variant`, `data-choice-state`, `data-selected`, and
`data-step-state` instead of controller-side variant class interpolation.

## Architecture guardrails

- `app/dom/**` plus `app/ui_runtime_dom.ts` own page lookup. Feature, runtime, and
  presenter modules should receive feature-scoped DOM surfaces instead of
  rebuilding page-wide DOM registries or ad hoc `document.getElementById(...)`
  lookups.
- Generated HTTP / WS contracts stay behind the transport boundary. The approved
  generated-contract seams are the `api/*.ts` HTTP wrappers plus `api/types.ts`,
  `transport/http_models.ts`, `transport/live_models.ts`, `server_payload.ts`,
  `ws.ts`, and `ws_payload_validator.ts`; `app/**` code imports `transport/**`,
  not generated contract files or `api/types.ts`.
- Raw HTML escape hatches belong only in `app/views/**` rendering helpers. When a
  module outside `app/views/**` needs to update DOM structure, prefer
  `renderChildren()`, `createElementNode()`, or a dedicated view/helper module
  instead of `innerHTML`, `insertAdjacentHTML`, or contextual fragments.
- Expected feature shape is thin facade + focused workflow/transport/presenter or
  binding modules. Workflow modules stay DOM-free, presenters own rendering, and
  bindings decode DOM events into typed actions for the owning feature.

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
