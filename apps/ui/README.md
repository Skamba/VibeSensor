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
| `api.ts` | REST API client with typed request/response interfaces |
| `ws.ts` | WebSocket client with auto-reconnect and stale detection |
| `i18n.ts` | Internationalization dictionary (English, Dutch) |
| `spectrum.ts` | uPlot chart wrapper for interactive spectrum visualization |
| `server_payload.ts` | WebSocket payload adaptation for the live spectrum dashboard |
| `vehicle_math.ts` | Tire diameter, order tolerance, and uncertainty calculations |
| `format.ts` | Number, byte, and timestamp formatting utilities |
| `constants.ts` | Sensor location codes |
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
and chart behavior. If you change startup wiring or long-lived UI ownership,
update this README and the AI repo maps in the same change set.

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
