# Web UI

Single-page TypeScript application that provides real-time vibration monitoring,
sensor management, run history, and car configuration. Communicates with the Pi
server over HTTP (REST) and WebSocket (live data).

## Tech Stack

- **TypeScript** — application logic
- **Preact + @preact/signals** — UI rendering plus shared reactive state
- **`src/poll.ts`** — interval + visibility polling for page stores
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
exports the OpenAPI/JSON Schema documents, renders their schemas as
`components["schemas"][Name]` types in Python (`tools/config/sync_contracts.py`),
and rewrites the files above plus `docs/protocol.md`. It needs only the backend
venv (`make setup`). Run it after changing backend API payloads, WS payloads, or
shared constants, and commit the result. CI's `integration` job
reruns it and fails on `git diff --exit-code`.

UI typecheck, tests, and builds use the committed files and need only Node.

## Code Quality

- `npm run lint` checks the hand-written TypeScript/TSX, config, and support
  scripts with Biome (recommended rules, including the a11y set for TSX).
- `npm run lint:unused` runs knip's dead-file, dependency, and cleaned-up unused
  export checks. Exported-type checks still stay out until their remaining
  signal is worth the extra noise.
- `npm run format:check` checks Biome formatter drift without rewriting files.
- `npm run format` rewrites the supported files when you want to apply the repo
  UI formatting locally.

Generated contract artifacts stay out of the lint/format path on purpose so the
source-of-truth export commands remain the only writers for those files.

## Architecture

`src/main.tsx` renders one Preact tree, `App` from `src/app.tsx`, into `#app`
and calls `startApp()`, which loads shared settings and connects the live feed.
The build is one JS bundle plus the lazily loaded Dutch catalog.

- **Shell** — `src/app.tsx` is the header, navigation, status pills, error
  banner, confirmation dialog, the
  Live/History/Settings views, and the settings tab strip. `src/app_store.ts`
  owns the shell state as module-level signals: active view and settings tab,
  `navigate()` (with per-view loaders registered through `onViewEnter()`),
  `showError()`, `requestConfirmation()`, and the persisted preferences.
- **Pages** — `src/pages/<page>/`: a `<Page>.tsx` component that reads its
  store's signals and calls its commands, a `<page>_store.ts` that owns signals,
  polling, and `api/*` calls, and pure helper modules with unit tests. Pages:
  `dashboard` (setup checklist, overview, recording and the action bar),
  `spectrum`, `history`, `cars` (list + add-car wizard), `analysis`,
  `speed_source`, `sensors`, `update` (Internet + Update tabs), `esp_flash`,
  `preferences` (the General tab: unit and language). `tests/page_boundaries.spec.ts` keeps pages from
  importing each other; the shell composes them (for example it passes
  `<Spectrum/>` into the dashboard and opens the wizard for its add-car prompt).
- **Shared stores** outside `src/pages/`: `app_store.ts` (shell),
  `settings_store.ts` (cars, analysis tuning, speed source and its live status),
  and `live_store.ts` (sensors, selection, speed, spectra, location codes, link
  state, and `runsChanged`, which the dashboard bumps when a run starts, stops,
  or finishes so History reloads). Pure helpers sit beside them
  (`vehicle_settings.ts`, `car_selection.ts`, `speed_source.ts`,
  `sensor_locations.ts`, `live_sync.ts`).
- **Text** — `src/i18n.ts` owns the single `t()` and the `lang` signal; the
  English catalog ships in the bundle and the Dutch one loads on demand.
  Components call `t()` while rendering, so a language switch re-renders them.

### Server state and polling

Each page store owns its server state as signals and calls the `api/*`
wrappers directly. Polling goes through `src/poll.ts`: `poll({ active,
intervalMs, load, onData, onError })` loads when `active` turns true and the
page is visible, re-polls after each result, and only delivers the latest
request's result, so a slow older response never overwrites newer data. Call
`refresh()` after a mutation instead of patching a cache.

### Live transport

- `src/ws.ts` owns the raw WebSocket lifecycle, reconnect/stale timers, and the
  latest raw payload signal.
- `src/live_transport.ts` (`startLive()`) mirrors the link state into
  `live_store`, validates and applies payloads at most once per animation frame
  and every 100 ms, keeps an unchanged spectrum frame by reference so the chart
  does not redraw (`live_sync.mergeSpectra`), and sends the selected sensor
  once per connection and on every change (`live_sync.createSelectionSender`).
- `?demo` skips the server: `startLive()` installs a demo car and applies the
  canned payload from `src/demo.ts`; recording-status polling stays off.

### Spectrum

Frames are prepared synchronously on the main thread (a handful of sensors at
a few frames per second is cheap).

- `pages/spectrum/frame_preparer.ts` turns the live spectra into aligned dB
  series with a per-sensor cache; it is the only owner of frame preparation.
- `pages/spectrum/spectrum_renderer.ts` owns the canvas chart lifecycle
  (`src/spectrum_chart.ts`, the custom renderer), tweening between frames
  (`spectrum_animation.ts`), order bands, and the focus marker.
- `pages/spectrum/spectrum_store.ts` re-renders on every new spectra object and
  owns trace focus, reference bands, the inspector line, and the overlay; the
  text for those lives in the pure `spectrum_model.ts`.

### Conventions

- Use module-level `signal()`s in a store for state that outlives a render,
  `computed()` for anything derived, and component hooks only for transient
  local state. Keep `effect()` for imperative integrations: timers, polling,
  the canvas chart, the WebSocket.
- Put text and state derivations in pure modules and unit-test them; rendered
  behaviour belongs in the Playwright journeys.
- No pass-through wrappers, per-feature `*Ports`/`*Deps` interfaces, or
  facades for a single implementation. Test HTTP by faking the `api/*` module
  (or `tests/fetch_stub.ts` when the real request matters).
- Generated HTTP/WS contracts stay behind `api/*.ts` + `api/types.ts`,
  `transport/live_models.ts`, `server_payload.ts`, `ws.ts`, and
  `ws_payload_validator.ts`; other code imports those, not `src/generated/` or
  `src/contracts/` directly.
- Shared visual state uses stable data/ARIA selectors such as `data-variant`,
  `data-choice-state`, `data-selected`, and `data-step-state` instead of
  variant class interpolation. `styles/app.css` only aggregates the per-surface
  stylesheets.

## Features

- **Live view** — overview, recording controls, and the multi-sensor spectrum
- **History view** — recorded runs with the diagnosis, PDF download, and ZIP export
- **Settings view** — car profiles (wizard with car library), analysis parameters, speed source, sensors, Internet, updates, ESP flashing
- **Auto theme** — follows system light/dark preference
- **Demo mode** — `?demo` shows canned live data without a server

## HTTP boundary tests

Tests of the `api/*` wrappers that need the real `fetch` path (status codes,
timeouts, request bodies) use `tests/fetch_stub.ts`: `stubFetch().use(route("GET
/api/health", () => json({...})))`. Unrouted requests fail loudly, and an
aborted signal rejects the call like a real `fetch`. Tests above the network
seam fake the `api/*` module instead, and Playwright journeys mock HTTP with
`page.route` and WebSocket traffic with the fake socket in `tests/smoke.helpers.ts`.

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
- Page stores may surface validated boundary failures to the UI, but they
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
| **Unit** | Vitest (`happy-dom`) | Payload decoders, API wrappers, poll/ws helpers, the spectrum renderer, and each page's pure model — anything that does not require a real browser | `npm run test:unit` |
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
then `npm run test:smoke`). The journeys start a Vite dev server on port 4173,
or reuse one already there; set `PLAYWRIGHT_SMOKE_PORT` to run several
worktrees side by side.

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
