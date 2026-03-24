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

```bash
cd apps/ui
npm ci
npm run lint         # Biome lint over the hand-written UI/config/test files
npm run dev          # Dev server on http://localhost:5173
npm run dev:open     # Same dev server, but opens the browser on local desktops
npm run build        # Production build to dist/
npm run typecheck    # Type check without emitting
```

Use `npm ci` for normal repo bootstrap and dependency refresh from the checked-in
lockfile. Only use `npm install` when you are intentionally adding or updating
UI dependencies so the resulting `package-lock.json` change is deliberate.

The Vite dev server proxies `/api`, `/ws`, and `/static` to
`http://127.0.0.1:8000` by default so you can use HMR without manually swapping
backend URLs. Override that backend target with `VITE_BACKEND_ORIGIN` when your
server is listening elsewhere.

The built output in `dist/` is copied to `apps/server/vibesensor/static/` for serving by FastAPI.
Use `python tools/build_ui_static.py` from the repo root to build and sync
in one step.

## Contract sync

Use `npm run sync:contracts` to refresh the generated frontend contracts and shared constants.

It regenerates:

- `src/generated/http_api_contracts.ts`
- `src/contracts/ws_payload_types.ts`
- `src/contracts/ws_payload_schema.generated.ts`
- `src/constants.ts`

`npm run check:contracts` fails if any of those generated files are stale.

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
| `app/ui_app_runtime.ts` | UI composition root that wires state, DOM, features, and focused runtime controllers |
| `app/runtime/ui_shell_controller.ts` | Menu/view shell, language and preference hydration, connection pill/banner, and other chrome state |
| `app/runtime/ui_live_transport_controller.ts` | Demo/WebSocket transport, payload adaptation, and throttled live-session rendering |
| `app/runtime/ui_spectrum_controller.ts` | Spectrum chart lifecycle, overlays, order-band calculation, and animation |
| `app/app_feature_bundle.ts` | Feature composition for dashboard, realtime, settings, cars, history, update, and ESP flash flows |
| `app/features/` | Feature owners for state changes, API calls, shared polling control, and delegated UI event wiring |
| `app/views/` | Focused DOM rendering and event-target decoding for settings, cars wizard, realtime, history, and update panels |
| `api.ts` | REST API client with typed request/response interfaces |
| `ws.ts` | WebSocket client with auto-reconnect and stale detection |
| `config.ts` | Centralized UI tuning constants for polling intervals, spectrum ranges, and history heatmap positions |
| `i18n.ts` | Internationalization dictionary (English, Dutch) |
| `spectrum.ts` | uPlot chart wrapper for interactive spectrum visualization |
| `server_payload.ts` | Runtime WebSocket payload adaptation and schema-version guardrails around the generated WS types |
| `diagnostics.ts` | Strength band normalization and vibration matrix helpers |
| `vehicle_math.ts` | Tire diameter, order tolerance, and uncertainty calculations |
| `format.ts` | Number, byte, and timestamp formatting utilities |
| `constants.ts` | Generated sensor location codes and shared strength field names from backend sources |
| `theme.ts` | Chart color palette and order band fill colors |
| `styles/app.css` | Full CSS with light/dark theme tokens |

## Features

- **Live view** — multi-sensor spectrum chart and recording controls
- **History view** — recorded runs with insights, PDF download, ZIP export (CSV raw samples + JSON run details)
- **Settings view** — car profiles (tire/drivetrain wizard with car library), analysis parameters, speed source, sensor naming and location mapping
- **Auto theme** — follows system light/dark preference
- **Drive sizing** — larger touch targets on tablet viewports
- **Demo mode** — deterministic UI state via `?demo=1` for testing

The runtime layer is intentionally split so `ui_app_runtime.ts` stays a
composition root instead of becoming a single-file owner for transport, shell,
chart behavior, or feature-specific DOM rendering. Feature modules own state,
network calls, and delegated event binding, while `app/views/` owns focused
HTML rendering helpers and event-target decoding for reusable panels.

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
```

Baselines live in `tests/snapshots/`. Tests use demo mode for deterministic payloads.

## Design Language

The UI follows the design system documented in
[docs/design_language.md](../../docs/design_language.md) — purple accent, minimal
flat aesthetic, token-driven styling.
