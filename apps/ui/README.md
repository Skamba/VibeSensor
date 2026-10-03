# Web UI

Single-page TypeScript application that provides real-time vibration monitoring,
sensor management, run history, and car configuration. Communicates with the Pi
server over HTTP (REST) and WebSocket (live data).

## Tech Stack

- **TypeScript** — application logic
- **Preact + @preact/signals** — UI rendering plus shared reactive state
- **`src/poll.ts`** — interval + visibility polling for page stores (pre-rewrite pages still use @tanstack/query-core)
- **Vite** — build tool and dev server
- **Canvas chart renderer** — custom live spectrum visualization
- **Vitest + happy-dom** — canonical fast unit/integration test runner
- **Playwright** — browser smoke testing
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
npm run lint:unused  # knip dead-file/dependency/export checks
npm run format:check # Biome formatter drift check
npm run dev          # Dev server on http://localhost:5173
npm run dev:open     # Same dev server, but opens the browser on local desktops
npm run dev:docker   # Docker-oriented wrapper: guarded npm ci + Vite
npm run build        # Production build to dist/
npm run typecheck    # Type check without emitting
```

From the repo root, `make setup` uses the shared UI bootstrap helper and records
the current `package-lock.json` marker after `npm ci`. For UI-only dependency
refreshes, use `npm ci` from this directory against the checked-in lockfile.
Only use `npm install` when you are intentionally adding or updating UI
dependencies so the resulting `package-lock.json` change is deliberate.

The source-mounted Docker dev stack calls `npm run dev:docker` inside the UI
container. It re-runs `npm ci` only when `node_modules` is missing or the
checked-in `package-lock.json` changes.

The Vite dev server proxies `/api`, `/ws`, and `/static` to
`http://127.0.0.1:8000` by default so you can use HMR without manually swapping
backend URLs. Override that backend target with `VITE_BACKEND_ORIGIN` when your
server is listening elsewhere.

The built output in `dist/` is copied to `apps/server/vibesensor/static/` for serving by FastAPI.
Use `python tools/build_ui_static.py` from the repo root to build and sync
in one step.

## Contract sync

The UI's backend contracts are generated TypeScript, committed to the repo:

- `src/generated/http_api_contracts.ts` (from the FastAPI OpenAPI schema)
- `src/contracts/ws_payload_types.ts` (from the `LiveWsPayload` JSON Schema)
- `src/constants.ts` (from backend-owned shared constants)

`make sync-contracts` (repo root) is the only regeneration entrypoint. It
exports the OpenAPI/JSON Schema documents to a temp dir, runs
`openapi-typescript` from `node_modules`, and rewrites the files above plus
`docs/protocol.md`. It needs the backend venv and UI `node_modules`
(`make setup`). Run it after changing backend API payloads, WS payloads, or
shared constants, and commit the result. CI's `integration` job
reruns it and fails on `git diff --exit-code`.

UI typecheck, tests, and builds use the committed files and need only Node.

## Code Quality

- `npm run lint` checks the hand-written TypeScript, config, and support scripts
  with Biome.
- `npm run lint:deps` runs dependency-cruiser against the current `src/`
  boundary rules so feature/runtime/view and transport/app seams stay explicit.
- `npm run lint:unused` runs knip's dead-file, dependency, and cleaned-up unused
  export checks. Exported-type checks still stay out until their remaining
  signal is worth the extra noise.
- `npm run format:check` checks Biome formatter drift without rewriting files.
- `npm run format` rewrites the supported files when you want to apply the repo
  UI formatting locally.

Generated contract artifacts stay out of the lint/format path on purpose so the
source-of-truth export commands remain the only writers for those files.

## Server-state ownership

Each page store owns its server state as signals and calls the `api/*`
wrappers directly. Polling goes through `src/poll.ts`: `poll({ active,
intervalMs, load, onData, onError })` loads when `active` turns true and the
page is visible, re-polls after each result, and only delivers the latest
request's result, so a slow older response never overwrites newer data. Call
`refresh()` after a mutation instead of patching a cache.

Pages that have not moved to `src/pages/` yet still use the TanStack
`QueryClient` created in `src/app/runtime/ui_query_client.ts`; it goes away
with the last of them.

## Live transport ownership

Frontend live transport ingress is signal-native end to end.

- `src/ws.ts` owns raw WebSocket lifecycle, reconnect/stale timers, and the
  latest raw payload signal from the socket.
- `src/app/runtime/ui_live_transport_controller.ts` owns the reactive bridge
  from that socket signal into `AppState.transport`, client-selection sends, and
  payload application into the runtime state slices.
- Keep render throttling/RAF pacing only where it is explicitly needed for
  spectrum or DOM performance. Do not reintroduce callback-style payload fan-out
  from `ws.ts` into app/runtime consumers.

## Spectrum frame preparation

Spectrum frames are prepared synchronously on the main thread (a handful of
sensors at a few frames per second is cheap).

- `src/app/runtime/ui_spectrum_controller.ts` prepares a frame on every spectra
  update, surfaces preparation failures in the overlay, and owns teardown.
- `src/app/runtime/spectrum_frame_preparer.ts` owns the typed frame-prep
  contract and the pure, cached preparation logic. Do not add a second owner
  for spectrum frame preparation.
- `src/app/runtime/spectrum_canvas_renderer.ts` does not prepare frames from
  raw AppState. It only composes chart-band metadata, owns the canvas chart
  lifecycle, and renders already prepared frames.

## HTTP boundary tests with MSW

Use `msw` as the shared HTTP mocking layer for UI tests that exercise the real
browser-side fetch boundary.

- Install the shared Node-side lifecycle from `tests/msw/node.ts` whenever the
  spec calls the real UI HTTP client or otherwise exercises the fetch boundary.
  The harness normalizes relative `/api/...` requests onto the test origin and
  fails unhandled HTTP requests loudly by default, so missing handlers stay
  obvious instead of silently falling through.
- Keep reusable feature-area handlers under `tests/msw/handlers/`. Organize
  them by the feature that owns the HTTP surface (`history.ts`, `settings.ts`)
  instead of by individual spec files.
- Keep cross-feature HTTP primitives in `tests/msw/http.ts`. That file owns the
  shared origin, route helpers, and any low-level helpers that are reused across
  multiple feature handler modules.
- Name reusable handler composition helpers `build<Feature>Handlers(...)` or
  `build<Feature><Scenario>Handlers(...)` when a feature needs a narrower
  scenario bundle. Name payload builders `make<Feature><Thing>Payload(...)` so
  handlers and callers read consistently.
- Prefer composing a realistic scenario from those shared builders over
  redefining ad hoc `fetch` replacements inside one spec. Reuse existing
  contract-shaped payload builders instead of inventing mock-only response
  shapes.

Use MSW when the behavior under test depends on the real HTTP boundary:

- request URLs, methods, payloads, or status handling matter
- the feature should exercise the actual `fetch`/API wrapper path end to end
- one shared handler can serve multiple specs in the same feature area

Do **not** use MSW when the test is already below the network seam:

- pure presenters, state derivations, and DOM-only views should stay network-free
- feature controller tests that only need canned or deferred responses should
  fake the `api/*` wrapper module the controller imports (`vi.mock("../src/api/settings", ...)`)
  instead of layering on MSW; controllers do not take injectable transport ports
- WebSocket behavior is separate; keep using the existing fake WebSocket helpers
  for live-session flows instead of trying to route WS traffic through MSW

## Features

- **Live view** — multi-sensor spectrum chart and recording controls
- **History view** — recorded runs with insights, PDF download, ZIP export (CSV raw samples + JSON run details)
- **Settings view** — car profiles (tire/drivetrain wizard with car library), analysis parameters, speed source, sensor naming and location mapping
- **Auto theme** — follows system light/dark preference
- **Drive sizing** — larger touch targets on tablet viewports
- **Demo mode** — deterministic UI state via `?demo=1` for testing

`src/main.tsx` renders one Preact tree, `App` from `src/app.tsx`, into
`#app`, then starts the features. `app.tsx` is the whole shell: navigation,
the unit and language selects, status pills, error banner, confirmation dialog,
the Live/History/Settings views, and the settings tab strip. `src/app_store.ts`
owns the shell state as module-level signals: active view and settings tab,
`navigate()` (with per-view loaders registered through `onViewEnter()`),
`showError()`, `requestConfirmation()`, and the persisted language and speed
unit preferences. `src/i18n.ts` owns the single `t()` and the `lang` signal;
the English catalog ships in the bundle and the Dutch one loads on demand.

The build is one JS bundle plus the lazily loaded Dutch catalog. Pages are
being moved to `src/pages/<page>/` (a component, a small signal store, and pure
helpers); `.dependency-cruiser.cjs` keeps pages from importing each other.
Until a page moves, its old feature controller and panel bridge are wired in
`src/app/feature_wiring.ts`.

Realtime follows the same controller shape: `realtime_feature.ts` owns the
polling, mutation flow, logging state signals, and panel action binding,
`realtime_feature_view_state.ts` derives the live overview/logging/sensors models plus idle readiness signatures
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

- AppState top-level slices returned by `createAppState()` are stable signal-field objects composed from feature-owned state modules. Keep new slice defaults and pure update helpers in `app/{shell,transport,realtime,history,settings,spectrum}_state.ts`, and keep `ui_app_state.ts` as the thin composition/compatibility surface.
- Import shared reactive primitives from `app/ui_signals.ts` so runtime,
  feature, presenter, and view code shares one documented signals entrypoint.
- Use `signal()` for shared state that spans modules or needs to outlive a
  single component render. Keep component-local transient state in hooks.
- Use `computed()` for derived state instead of mirroring derived fields onto
  mutable state bags or manual render-model caches. Keep those computed owners
  in runtime, feature, presenter, or shared adapter modules instead of
  rebuilding ad-hoc derived state inside view components.
- Inside Preact components, prefer plain signal reads for already-derived view
  models. Reach for `useSignal()`, `useSignalEffect()`, or shared adapter hooks
  only when the component truly owns transient local state or an imperative
  integration.
- When several JSX bindings unwrap stable properties from the same model signal,
  prefer `useSignalProperties()` from `app/ui_signals.ts` over repeating
  property access or per-property `useComputed(...)` adapters.
- Use `effect()` only for narrow imperative integrations such as timers,
  persistence, canvas chart bridges, or other external-library coordination.
- Preact-rendered copy should come from `getUiText()` or `useUiText()`.
  Do not leave `data-i18n` attributes in JSX unless a non-Preact consumer still
  reads them.
- Existing mutable app-state objects and manual bridge rerenders are follow-up
  migration residue, not the default pattern for new frontend work.
- Top-level AppState slices are owned by focused modules:
  `shell_state.ts`, `transport_state.ts`, `realtime_state.ts`,
  `history_state.ts`, `settings_state.ts`, and `spectrum_state.ts`.
  Add new slice fields, defaults, and pure update helpers there instead of
  growing `ui_app_state.ts`.

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
  `npm run lint:deps` (dependency-cruiser) enforces that boundary.
- Normal UI rendering belongs in Preact owner surfaces. If code outside an
  island needs imperative DOM work, keep it narrowly scoped to non-render
  integrations such as download anchors, canvas chart lifecycles, observers, or
  external-library mount points instead of generic HTML/string builder helpers.
- Expected page shape is `src/pages/<page>/`: a `<Page>.tsx` component that
  reads the store's signals and calls its commands, a `<page>_store.ts` that
  owns signals, polling (`src/poll.ts`), and `api/*` calls, and pure helper
  modules (for example `esp_flash_model.ts`, `update_model.ts`) for text and
  state derivations with unit tests. Pre-rewrite features still follow the old
  controller + presenter + panel-bridge shape until their page moves.
- Do not add pass-through `*_transport.ts` wrappers, per-feature
  `*Ports`/`*Deps` interfaces, or facade/workflow splits for a single
  implementation. Pass controllers a plain context object; test HTTP by faking
  the `api/*` module (or MSW when the real request matters) and view effects
  through a fake panel bridge.
- Mount Preact owner surfaces directly inside their owning runtime/view module.
  Do not scatter `preact.render(...)` calls across feature or presenter code.

## WebSocket contract boundary

- `src/contracts/ws_payload_types.ts` is generated from the backend
  `LiveWsPayload` JSON Schema by the [contract sync flow](#contract-sync).
- `src/ws_payload_validator.ts` validates raw live payloads with Valibot schemas, while the large spectrum-number arrays stay on a custom finite-number-array guard so the live chart path avoids per-element schema object churn.
- `src/server_payload.ts` then adapts the validated `LiveWsPayload` with schema-version warnings, shared-`freq` fallback, and malformed/misaligned spectrum rejection.

Valibot-backed runtime validation now sits at the WebSocket boundary. Live payloads must satisfy the generated contract shape directly before the app-state adapter accepts them. The remaining UI-side handling is limited to current, explicit adapter behavior: schema-version warning logging, shared-`freq` fallback when the canonical shared axis is used, and dropping spectrum series that still cannot produce aligned bins for rendering.

## HTTP runtime boundary validation

- Generated HTTP TypeScript aliases in `src/api/types.ts` are compile-time shapes,
  not runtime proof. Owned server-controlled responses must validate `unknown`
  payloads at the API boundary before feature/runtime code reads them.
- `src/runtime_boundary_validation.ts` owns the shared Valibot error-path/message
  helper for frontend runtime boundaries.
- `src/api/update_validators.ts` is the canonical HTTP pattern: parse once,
  validate once, then return typed data from the API module.
- Feature controller code may surface validated boundary failures to the UI, but it
  must not rebuild ad hoc `typeof` normalizers for the same payload shape.
- Keep custom fast-path validators only where large numeric arrays or similar hot
  paths would make generic schema validation measurably more expensive.

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

## Test layers

The UI has complementary test layers; pick the one that matches the seam
under test.

| Layer | Runner | What it covers | Command |
|-------|--------|----------------|---------|
| **Unit / integration** | Vitest (`happy-dom`) | Payload decoders, runtime helpers, feature orchestration, signal-mounted islands, view-level pure helpers — anything that does not require a real browser | `npm run test:unit` |
| **Smoke** | Playwright (Chromium) | User journeys per page against a real Vite dev server with mocked HTTP/WebSocket; file pattern `tests/smoke.*.spec.ts` | `npm run test:smoke` |

Vitest is the canonical fast test layer for pure logic; reach for it whenever
the test does not need a real browser. Playwright journeys cover what a user
does on each page.

```bash
npm run test:unit            # run the Vitest unit suite once
npm run test:unit:watch      # watch mode during local iteration
make ui-test                 # same unit suite from the repo root
```

Vitest auto-discovers `tests/**/*.spec.ts` and excludes the Playwright-owned
`smoke.*.spec.ts` files via [`vitest.config.ts`](./vitest.config.ts). New
logic-level tests should land as `tests/<feature>_*.spec.ts`. Page journeys
live in `tests/smoke.<page>.spec.ts`; `tests/smoke.critical.spec.ts` keeps the
cross-page boot/record/history flows (`npx playwright install chromium` once,
then `npm run test:smoke`).

## Unit tests

- Unit-test pure logic (validators, contracts, formatting, spectrum math,
  status text, car confidence, view-model builders) without a DOM where
  possible. Rendered behaviour belongs in the Playwright journeys.
- Use `tests/async_test_helpers.ts::flushSignalUpdates()` after mutating
  signals or when waiting on effect-owned side effects.

## Design Language

The UI follows the design system documented in
[docs/design_language.md](../../docs/design_language.md) — purple accent, minimal
flat aesthetic, token-driven styling.
