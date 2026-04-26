# Documentation Index

Every documentation file in the repository and a short description of what it covers.

## AI Guidance

Start with `.github/copilot-instructions.md`; it is the AI entry point and
links onward to the scoped instruction files and repo map below.

| File | Description |
|------|-------------|
| `.github/copilot-instructions.md` | AI entry point: high-level orientation, instruction sources, and common commands. |
| `docs/ai/repo-map.md` | Detailed repo layout, entry points, and module ownership. |
| `.github/instructions/general.instructions.md` | Shared workflow, validation, and execution guardrails for AI work. |
| `.github/instructions/backend.instructions.md` | Backend-specific coding rules and deltas for AI work. |
| `.github/instructions/frontend.instructions.md` | Frontend-specific rules and deltas for AI work. |
| `.github/instructions/firmware.instructions.md` | Firmware-specific rules and validation deltas for `firmware/esp/**`. |
| `.github/instructions/pi-image.instructions.md` | Pi-image-specific rules and validation deltas for `infra/pi-image/**`. |
| `.github/instructions/tests.instructions.md` | Backend test-specific conventions and commands for `apps/server/tests/**`. |

## Architecture & Design

| File | Description |
|------|-------------|
| `docs/domain-model.md` | Domain object graph, modeling rules, and adapter inventory. |
| `docs/dataflows.md` | Canonical four-flow map for live, recording, raw capture, and report paths. |
| `docs/car_library_architecture.md` | Exact vehicle-configuration rows, legacy picker compatibility, and car-library source-of-truth rules. |
| `docs/analysis_pipeline.md` | Post-stop diagnostics pipeline: steps, modules, and data flow. |
| `docs/order_tracking.md` | Order-reference math, tolerance bands, and order-finding flow. |
| `docs/report_pipeline.md` | Report generation flow from analysis to PDF. |
| `docs/design_language.md` | Visual design decisions for report layout and UI. |
| `docs/metrics.md` | Vibration metric definitions and unit rules. |
| `docs/metrics_to_report_mapping.md` | How metrics map to report sections. |
| `docs/protocol.md` | UDP and WebSocket protocol details between ESP32 and server. |

## Infrastructure & Operations

| File | Description |
|------|-------------|
| `docs/operational-runbooks.md` | Troubleshooting and operational procedures. |
| `docs/configuration_reference.md` | Runtime config keys, defaults, constraints, and common override examples. |
| `docs/runtime_support_matrix.md` | Canonical Python and Node support policy by environment plus update ownership. |
| `docs/history_db_schema.md` | SQLite history database schema. |
| `docs/run_lifecycle.md` | Recording lifecycle, persistence retries, and post-analysis queue semantics. |
| `docs/run_schema_v2.md` | Run data persistence schema v2. |
| `docs/intake_buffering.md` | Sample intake, buffering, and live signal-processing flow. |
| `docs/time_alignment.md` | Multi-sensor time alignment approach. |
| `docs/multithreading_performance.md` | Threading model and performance considerations. |

## API & contract quick path

Start with `apps/server/README.md` § "HTTP and WebSocket surface" for the
human-facing route-group overview, schema export commands, and common
HTTP/WebSocket error semantics. Pair it with `apps/ui/README.md` §
"WebSocket contract boundary" for the live payload field guide and
`docs/operational-runbooks.md` for `/api/health` interpretation and stale-live-update debugging.

## Testing

| File | Description |
|------|-------------|
| `docs/testing.md` | Test layout plus backend, frontend, firmware, and Pi-image validation quick paths. |

## READMEs (setup and orientation)

| File | Description |
|------|-------------|
| `README.md` | Project overview and quickstart. |
| `CONTRIBUTING.md` | Development workflow and setup paths. |
| `CHANGELOG.md` | Release history. |
| `apps/server/README.md` | Backend setup, deployment, and CLI usage. |
| `apps/ui/README.md` | Frontend setup and build workflow. |
| `firmware/esp/README.md` | ESP32 firmware setup and flashing. |
| `firmware/esp/HARDENING.md` | Firmware security hardening notes. |
| `hardware/README.md` | Hardware components and wiring. |
| `infra/ci/README.md` | CI pipeline overview. |
| `infra/pi-image/pi-gen/README.md` | Raspberry Pi image build flow. |

## Data & reference

| File | Description |
|------|-------------|
| `apps/server/vibesensor/data/vehicle_configurations.json` | Canonical exact vehicle configurations with inline ratio/tire confidence and evidence metadata. |
| `apps/server/vibesensor/data/car_sources/*.json` | Reusable source-document metadata referenced from canonical vehicle configurations. |
