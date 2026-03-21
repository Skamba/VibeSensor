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
npm run dev          # Dev server on http://localhost:5173
npm run build        # Production build to dist/
npm run typecheck    # Type check without emitting
```

The built output in `dist/` is copied to `apps/server/vibesensor/static/` for serving by FastAPI.
Use `python tools/build_ui_static.py` from the repo root to build and sync
in one step.

## Contract sync

Use `npm run sync:contracts` to refresh the generated frontend contracts.

It regenerates:

- `src/generated/http_api_contracts.ts`
- `src/contracts/ws_payload_types.ts`
- `src/contracts/ws_payload_schema.generated.ts`

It does **not** rewrite `src/constants.ts`; backend hygiene tests guard drift
for `LOCATION_CODES` and `METRIC_FIELDS` there.

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
| `app/features/` | Feature owners for state changes, API calls, polling loops, and delegated UI event wiring |
| `app/views/` | Focused DOM rendering and event-target decoding for settings, realtime, history, and update panels |
| `api.ts` | REST API client with typed request/response interfaces |
| `ws.ts` | WebSocket client with auto-reconnect and stale detection |
| `i18n.ts` | Internationalization dictionary (English, Dutch) |
| `spectrum.ts` | uPlot chart wrapper for interactive spectrum visualization |
| `server_payload.ts` | Runtime WebSocket payload adaptation and schema-version guardrails around the generated WS types |
| `ws_payload_normalization.ts` | Small pre-AJV compatibility shim for legacy spectra and `strength_metrics` payload quirks |
| `diagnostics.ts` | Strength band normalization and vibration matrix helpers |
| `vehicle_math.ts` | Tire diameter, order tolerance, and uncertainty calculations |
| `format.ts` | Number, byte, and timestamp formatting utilities |
| `constants.ts` | Sensor location codes and shared strength field names, with backend hygiene tests guarding drift |
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
- `src/ws_payload_normalization.ts` keeps the pre-validation compatibility shim small: it only normalizes the supported legacy `strength_metrics` and malformed-spectra quirks before AJV runs.
- `src/ws_payload_validator.ts` compiles AJV against `ws_payload_schema.json` and validates that normalized live payload at runtime.
- `src/server_payload.ts` then adapts the validated `LiveWsPayload` with schema-version warnings, shared-`freq` fallback, and malformed/misaligned spectrum rejection.

AJV-backed runtime validation now sits at the WebSocket boundary. The UI still preserves the intentionally supported compatibility behavior called out in the original investigation—partial `strength_metrics` defaults, malformed peak dropping, shared-`freq` fallback, schema-version warning logging, and dropping malformed spectrum series before they can misalign bins—but the rest of the payload now has to satisfy that JSON Schema before the app state adapter accepts it.

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
