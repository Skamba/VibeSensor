#!/usr/bin/env python3
"""Generate a GitHub wiki page seed for VibeSensor.

The page content is derived from the live repository structure and current
product surfaces. This script writes markdown pages and expects curated
screenshots to be present under ``images/`` in the output directory.
"""

from __future__ import annotations

import argparse
from pathlib import Path

SCREENSHOT_FILES = (
    "images/live-dashboard.png",
    "images/history-overview.png",
    "images/settings-cars.png",
    "images/settings-analysis.png",
    "images/settings-speed-source.png",
)


def _blob_url(repo_url: str, path: str) -> str:
    return f"{repo_url.rstrip('/')}/blob/main/{path}"


def _release_label(version: str | None, commit_sha: str | None) -> str:
    parts: list[str] = []
    if version:
        parts.append(f"release `{version}`")
    if commit_sha:
        parts.append(f"commit `{commit_sha[:7]}`")
    if not parts:
        return "development snapshot"
    return " / ".join(parts)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def _home_page(repo_url: str, release_note: str) -> str:
    return f"""# VibeSensor

_Reviewed against {release_note}._

VibeSensor is an offline-first vehicle vibration diagnostics system: ESP32 sensor
nodes stream accelerometer data to a Raspberry Pi, the Pi performs FFT/order
analysis locally, and the browser dashboard turns the result into live views,
run history, and PDF reports.

## Start here

- [Web UI tour](Web-UI)
- [System architecture](System-Architecture)
- [Release and deployment](Release-and-Deployment)
- [Repo README]({_blob_url(repo_url, "README.md")})
- [Backend HTTP/WebSocket reference]({_blob_url(repo_url, "apps/server/README.md")}#http-and-websocket-surface)
- [Frontend architecture]({_blob_url(repo_url, "apps/ui/README.md")})

## Product flow

1. Mount sensors and connect to the Pi hotspot.
2. Use the **Live** dashboard to confirm signal quality and record a drive.
3. Review **History** for findings, heatmaps, PDF reports, and exports.
4. Manage **Cars**, **Analysis**, and **Speed Source** settings from the Settings view.
5. Ship release artifacts from CI: Python wheel, firmware bundle, and refreshed wiki screenshots.

## Screenshot tour

### Live dashboard

![Live dashboard](images/live-dashboard.png)

### History overview

![History overview](images/history-overview.png)

### Cars and setup

![Cars tab](images/settings-cars.png)

For the full UI breakdown with page-by-page notes, use [Web UI](Web-UI).

## Source-of-truth files

- UI feature composition: [`apps/ui/src/app/app_feature_bundle.ts`]({_blob_url(repo_url, "apps/ui/src/app/app_feature_bundle.ts")})
- UI shell & transport: [`apps/ui/src/app/runtime/`]({_blob_url(repo_url, "apps/ui/src/app/runtime")})
- UI design system: [`apps/ui/src/styles/app.css`]({_blob_url(repo_url, "apps/ui/src/styles/app.css")}) and [`docs/design_language.md`]({_blob_url(repo_url, "docs/design_language.md")})
- Backend/report stack: [`apps/server/`]({_blob_url(repo_url, "apps/server")})
- Release workflow: [`.github/workflows/main-release.yml`]({_blob_url(repo_url, ".github/workflows/main-release.yml")})
"""


def _web_ui_page(repo_url: str) -> str:
    return f"""# Web UI

The TypeScript/Vite app is a single-page dashboard with three top-level views:
**Live**, **History**, and **Settings**. The overall UI architecture is described in
[`apps/ui/README.md`]({_blob_url(repo_url, "apps/ui/README.md")}), while the feature
wiring lives in [`apps/ui/src/app/app_feature_bundle.ts`]({_blob_url(repo_url, "apps/ui/src/app/app_feature_bundle.ts")}).

## Main views

| View | What it is for | Key source files |
| --- | --- | --- |
| Live | Real-time spectrum monitoring, event log, recording controls, sensor coverage | [`realtime_feature.ts`]({_blob_url(repo_url, "apps/ui/src/app/features/realtime_feature.ts")}), [`ui_spectrum_controller.ts`]({_blob_url(repo_url, "apps/ui/src/app/runtime/ui_spectrum_controller.ts")}) |
| History | Recorded runs, diagnosis previews, heatmap/details, PDF and ZIP export | [`history_feature.ts`]({_blob_url(repo_url, "apps/ui/src/app/features/history_feature.ts")}), [`history_table_view.ts`]({_blob_url(repo_url, "apps/ui/src/app/views/history_table_view.ts")}) |
| Settings | Cars, analysis tuning, speed source, sensors, update, ESP flash | [`settings_feature.ts`]({_blob_url(repo_url, "apps/ui/src/app/features/settings_feature.ts")}), [`views/`]({_blob_url(repo_url, "apps/ui/src/app/views")}) |

## Live dashboard

![Live dashboard](images/live-dashboard.png)

The seeded screenshots use deterministic mocked HTTP and WebSocket data so the
wiki always shows:

- a populated multi-sensor spectrum chart with visible plotted data,
- the live sensor coverage roster with multiple mounted sensors,
- live speed/order context,
- and the status surfaces that matter during a road test.

Useful code anchors:

- Screenshot fixture data: [`apps/ui/tests/wiki_screenshot_data.ts`]({_blob_url(repo_url, "apps/ui/tests/wiki_screenshot_data.ts")})
- Route/WebSocket helpers: [`apps/ui/tests/smoke.helpers.ts`]({_blob_url(repo_url, "apps/ui/tests/smoke.helpers.ts")})
- Release wiki capture: [`apps/ui/tests/wiki_screenshots.spec.ts`]({_blob_url(repo_url, "apps/ui/tests/wiki_screenshots.spec.ts")})

## History view

![History overview](images/history-overview.png)

The curated wiki scenario shows multiple analyzed runs so the page demonstrates the
actual workflow: summary rows, preview diagnosis context, and enough data to explain
why users come back after a drive.

The mocked release screenshot data intentionally includes:

- multiple completed runs,
- different root-cause summaries,
- speed-band context,
- confidence labels,
- and enough sensor intensity evidence for the heatmap/detail entry points.

Useful code anchors:

- History state/features: [`apps/ui/src/app/features/history_feature.ts`]({_blob_url(repo_url, "apps/ui/src/app/features/history_feature.ts")})
- History rendering: [`apps/ui/src/app/views/history_table_view.ts`]({_blob_url(repo_url, "apps/ui/src/app/views/history_table_view.ts")})
- Smoke coverage: [`apps/ui/tests/smoke.history.spec.ts`]({_blob_url(repo_url, "apps/ui/tests/smoke.history.spec.ts")})

## Settings: Cars

![Cars tab](images/settings-cars.png)

The Cars tab is where the product connects vehicle metadata to the order-analysis
math. The release screenshot seeds multiple cars so the wiki demonstrates:

- active-car selection,
- stored vehicle specs (tire, final drive, gear),
- and why the product treats car configuration as part of the analysis contract.

Useful code anchors:

- Cars feature: [`apps/ui/src/app/features/cars_feature.ts`]({_blob_url(repo_url, "apps/ui/src/app/features/cars_feature.ts")})
- Cars table renderer: [`settings_car_list_view.ts`]({_blob_url(repo_url, "apps/ui/src/app/views/settings_car_list_view.ts")})
- Wizard smoke test: [`smoke.car-wizard.spec.ts`]({_blob_url(repo_url, "apps/ui/tests/smoke.car-wizard.spec.ts")})

## Settings: Analysis

![Analysis settings](images/settings-analysis.png)

This tab exposes the tuning inputs behind wheel/driveshaft/engine order matching.
The screenshot uses a valid active car and real response-shape data so the wiki can
show the same controls CI validates:

- bandwidth percentages,
- uncertainty knobs,
- reset-to-defaults behavior,
- and the guided helper disclosures added to keep the defaults understandable.

Useful code anchors:

- Analysis settings module: [`settings_analysis_module.ts`]({_blob_url(repo_url, "apps/ui/src/app/features/settings_analysis_module.ts")})
- Settings smoke coverage: [`smoke.settings.spec.ts`]({_blob_url(repo_url, "apps/ui/tests/smoke.settings.spec.ts")})

## Settings: Speed Source

![Speed source](images/settings-speed-source.png)

Speed source is documented separately because it directly affects the order-tracking
pipeline. The release screenshot keeps GPS connected with live effective speed so the
wiki always shows the intended happy path for speed-backed analysis.

Useful code anchors:

- Speed source module: [`settings_speed_source_module.ts`]({_blob_url(repo_url, "apps/ui/src/app/features/settings_speed_source_module.ts")})
- GPS diagnostics helpers in tests: [`smoke.helpers.ts`]({_blob_url(repo_url, "apps/ui/tests/smoke.helpers.ts")})

## Design & visual testing

- Design system: [`docs/design_language.md`]({_blob_url(repo_url, "docs/design_language.md")})
- Visual regression baselines: [`apps/ui/tests/snapshots/visual.spec.ts/`]({_blob_url(repo_url, "apps/ui/tests/snapshots/visual.spec.ts")})
- Wiki screenshot generator: [`apps/ui/tests/wiki_screenshots.spec.ts`]({_blob_url(repo_url, "apps/ui/tests/wiki_screenshots.spec.ts")}) and [`apps/ui/playwright.wiki.config.ts`]({_blob_url(repo_url, "apps/ui/playwright.wiki.config.ts")})
"""


def _architecture_page(repo_url: str) -> str:
    return f"""# System Architecture

## Runtime pipeline

```text
ESP32 + ADXL345 sensors
  -> UDP data/control on the Pi hotspot
  -> FastAPI backend + FFT/order analysis + report generation
  -> HTTP + WebSocket UI for live monitoring, history, and configuration
```

The repository keeps the product split into four primary runtime areas:

| Area | What it owns | Primary references |
| --- | --- | --- |
| `apps/server/` | FastAPI, live processing, persisted runs, PDF reports, updater logic | [`apps/server/README.md`]({_blob_url(repo_url, "apps/server/README.md")}) |
| `apps/ui/` | Browser dashboard, settings flows, Playwright coverage | [`apps/ui/README.md`]({_blob_url(repo_url, "apps/ui/README.md")}) |
| `firmware/esp/` | ESP32 sampling and UDP transport | [`firmware/esp/README.md`]({_blob_url(repo_url, "firmware/esp/README.md")}) |
| `infra/pi-image/` | Pi image build and offline hotspot packaging | [`infra/pi-image/pi-gen/README.md`]({_blob_url(repo_url, "infra/pi-image/pi-gen/README.md")}) |

## Important architectural rules

- The product is **offline first**: hotspot boot and core workflows must not depend on internet access.
- Persisted report outputs expose vibration intensity in **dB** for the user-facing summary/report surfaces.
- Shared logic lives in the backend package and is exported into the UI via generated contracts/constants, not duplicated in ad hoc files.
- The browser UI consumes typed HTTP and WebSocket contracts and validates live WS payloads before rendering.

Key references:

- Repo map: [`docs/ai/repo-map.md`]({_blob_url(repo_url, "docs/ai/repo-map.md")})
- Domain model: [`docs/domain-model.md`]({_blob_url(repo_url, "docs/domain-model.md")})
- Protocol details: [`docs/protocol.md`]({_blob_url(repo_url, "docs/protocol.md")})
- Testing layout: [`docs/testing.md`]({_blob_url(repo_url, "docs/testing.md")})

## Browser contract boundary

The UI depends on generated schemas and runtime validation instead of treating payloads
as loose records:

- HTTP types: [`apps/ui/src/generated/http_api_contracts.ts`]({_blob_url(repo_url, "apps/ui/src/generated/http_api_contracts.ts")})
- WS types: [`apps/ui/src/contracts/ws_payload_types.ts`]({_blob_url(repo_url, "apps/ui/src/contracts/ws_payload_types.ts")})
- WS validator: [`apps/ui/src/ws_payload_validator.ts`]({_blob_url(repo_url, "apps/ui/src/ws_payload_validator.ts")})
- Payload adaptation: [`apps/ui/src/server_payload.ts`]({_blob_url(repo_url, "apps/ui/src/server_payload.ts")})
"""


def _release_page(repo_url: str, release_note: str) -> str:
    return f"""# Release and Deployment

_Reviewed against {release_note}._

## Release workflow

The release automation is defined in [`.github/workflows/main-release.yml`]({_blob_url(repo_url, ".github/workflows/main-release.yml")}).
The job currently builds:

1. the synced UI static bundle,
2. the version-stamped backend wheel,
3. the firmware artifacts + flash manifest,
4. release-smoke validation,
5. curated UI screenshots for the wiki,
6. refreshes only the wiki screenshot assets,
7. and the GitHub Release itself.

## Release outputs

| Output | Source |
| --- | --- |
| Python wheel (`apps/server/dist/*.whl`) | backend build step |
| Firmware ZIP (`vibesensor-fw-v*.zip`) | PlatformIO build + bundle step |
| Wiki screenshots | Playwright capture driven by [`apps/ui/tests/wiki_screenshots.spec.ts`]({_blob_url(repo_url, "apps/ui/tests/wiki_screenshots.spec.ts")}) |

## Manual wiki page seed

The core wiki pages are seeded manually from the repository. This script,
[`tools/wiki/generate_wiki.py`]({_blob_url(repo_url, "tools/wiki/generate_wiki.py")}),
is a helper for that one-time or occasional page refresh. Release CI does not
overwrite the wiki markdown pages; it only refreshes the screenshot assets in
`images/`.

## Deployment modes

### Native + Vite

- backend: `python -m pip install -e "./apps/server[dev]"`
- frontend: `npm --prefix apps/ui ci && npm --prefix apps/ui run dev`
- simulator: `vibesensor-sim --count 5 --server-host 127.0.0.1 --no-auto-server`

### Docker dev stack

- `make dev` for source-mounted backend + UI development
- `docker compose up --build` for a product-style local stack

### Raspberry Pi image

- Pi image pipeline: [`infra/pi-image/pi-gen/README.md`]({_blob_url(repo_url, "infra/pi-image/pi-gen/README.md")})
- Installer scripts: [`apps/server/scripts/`]({_blob_url(repo_url, "apps/server/scripts")})

## Validation references

- Full contributor workflow: [`CONTRIBUTING.md`]({_blob_url(repo_url, "CONTRIBUTING.md")})
- Test layout and commands: [`docs/testing.md`]({_blob_url(repo_url, "docs/testing.md")})
- Release smoke script: [`tools/tests/run_release_smoke.py`]({_blob_url(repo_url, "tools/tests/run_release_smoke.py")})
"""


def _sidebar() -> str:
    return """### VibeSensor Wiki

- [Home](Home)
- [Web UI](Web-UI)
- [System Architecture](System-Architecture)
- [Release and Deployment](Release-and-Deployment)
"""


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Generate the VibeSensor GitHub wiki page seed."
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory that will receive the generated wiki bundle.",
    )
    parser.add_argument(
        "--repo-url",
        default="https://github.com/Skamba/VibeSensor",
        help="Repository URL used for source links inside the wiki.",
    )
    parser.add_argument(
        "--release-version",
        default=None,
        help="Optional release version displayed in the generated wiki.",
    )
    parser.add_argument(
        "--commit-sha",
        default=None,
        help="Optional commit SHA displayed in the generated wiki.",
    )
    args = parser.parse_args(argv)

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "images").mkdir(parents=True, exist_ok=True)

    missing = [path for path in SCREENSHOT_FILES if not (output_dir / path).exists()]
    if missing:
        missing_text = ", ".join(missing)
        raise SystemExit(
            f"missing expected screenshot files in output dir: {missing_text}"
        )

    release_note = _release_label(args.release_version, args.commit_sha)
    _write(output_dir / "Home.md", _home_page(args.repo_url, release_note))
    _write(output_dir / "Web-UI.md", _web_ui_page(args.repo_url))
    _write(output_dir / "System-Architecture.md", _architecture_page(args.repo_url))
    _write(
        output_dir / "Release-and-Deployment.md",
        _release_page(args.repo_url, release_note),
    )
    _write(output_dir / "_Sidebar.md", _sidebar())
    print(f"Generated wiki bundle in {output_dir}")


if __name__ == "__main__":
    main()
