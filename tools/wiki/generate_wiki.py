#!/usr/bin/env python3
"""Generate a user-centric GitHub wiki seed for VibeSensor.

The page content is derived from the live repository docs and current product
surfaces. This script writes markdown pages and expects curated screenshots to
be present under ``images/`` in the output directory.
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

VibeSensor is an offline-first vibration diagnostic kit for cars. A Raspberry Pi
creates its own Wi-Fi hotspot, wireless sensor nodes stream accelerometer data
to it, and the browser dashboard turns a road test into live graphs, saved run
history, and PDF reports. You do not need internet access and you do not need
to install a phone app.

## Start here

1. [Get the hardware](Get-the-Hardware)
2. [Initial install](Initial-Install)
3. [Configure VibeSensor](Configure-VibeSensor)
4. [Run a diagnostic drive](Run-a-Diagnostic-Drive)
5. [Troubleshooting and maintenance](Troubleshooting-and-Maintenance)

## What a normal workflow looks like

1. Assemble a Pi plus one or more wireless sensor nodes.
2. Flash the Pi image or do the manual Raspberry Pi install once.
3. Power on the Pi and connect your phone, tablet, or laptop to the
   `VibeSensor` hotspot.
4. Open `http://10.4.0.1`, add the car you are testing, assign sensor
   locations, and choose a speed source.
5. Use the **Live** view to confirm the sensors are streaming and the graph has
   real movement.
6. Record a drive, then open **History** to review the diagnosis and export a
   PDF report.

## The main operator screens

### Live view

![Live dashboard](images/live-dashboard.png)

Use **Live** while mounting sensors, checking signal quality, and recording a
test drive.

### History

![History overview](images/history-overview.png)

Use **History** after a run to compare sessions, review the strongest findings,
and export customer-facing reports.

### Settings

![Cars tab](images/settings-cars.png)

Use **Settings** to choose the active car, tune analysis inputs when needed, and
select a speed source.

## Good starter kits

- **Minimum bench kit:** 1 Raspberry Pi, 1 sensor node, and 1 browser device.
- **Typical road-test kit:** 1 Raspberry Pi plus multiple sensor nodes so you
  can compare corners of the car during the same run.
- **Expanded diagnostic kit:** add an engine-bay sensor and a GPS receiver if
  you want automatic speed instead of manual speed entry.

## Need the deeper technical docs?

- Top-level README: [`README.md`]({_blob_url(repo_url, "README.md")})
- Hardware BOM: [`hardware/README.md`]({_blob_url(repo_url, "hardware/README.md")})
- Pi image build/install reference: [`infra/pi-image/pi-gen/README.md`]({_blob_url(repo_url, "infra/pi-image/pi-gen/README.md")})
- Server config reference: [`docs/configuration_reference.md`]({_blob_url(repo_url, "docs/configuration_reference.md")})
- Field troubleshooting runbook: [`docs/operational-runbooks.md`]({_blob_url(repo_url, "docs/operational-runbooks.md")})
"""


def _hardware_page(repo_url: str) -> str:
    return f"""# Get the Hardware

VibeSensor does not currently ship from this repository as a single boxed kit.
Today, you build a kit from the prototype bill of materials and then flash the
Pi and sensor software yourself or through whoever prepares devices for your
team.

## Core parts you need

| Part | Typical quantity | Why you need it |
| --- | --- | --- |
| Raspberry Pi 3 A+ | 1 | Runs the hotspot, server, history database, and browser UI |
| microSD card | 1 | Holds the Pi image or manual install |
| Pi power supply | 1 | Powers the Pi during use |
| M5Stack ATOM Lite ESP32 | 1 per sensor node | Wi-Fi sensor node that streams data to the Pi |
| M5Stack Accel Unit (ADXL345) | 1 per sensor node | Measures vibration on three axes |
| M5Stack Atomic Battery Base | 1 per sensor node | Makes each ATOM Lite portable |
| Phone, tablet, or laptop with Wi-Fi | 1 | Connects to the Pi hotspot and opens the dashboard |
| GPS receiver supported by `gpsd` | Optional | Lets VibeSensor use live GPS speed instead of manual speed |

The current prototype hardware list in the repo is:
[`hardware/README.md`]({_blob_url(repo_url, "hardware/README.md")}).

## How many sensor nodes should you buy?

- **At minimum:** 1 node for bench work, quick checks, or a single suspect area.
- **Most useful starting point:** multiple nodes so you can compare locations in
  one drive instead of moving one sensor around between runs.
- **Common full-car layout:** one sensor near each wheel.
- **Extra coverage:** add an engine-bay sensor when engine-order vibration is
  part of the complaint.

Multiple sensor nodes can connect to one Pi at the same time.

## Assembly

Each sensor node is made from:

1. an M5Stack ATOM Lite,
2. an M5Stack Accel Unit,
3. and an Atomic Battery Base.

The ATOM Lite connects to the accelerometer through the 4-pin Unit port, so the
prototype build does not require soldering. The default wiring in this repo is:

- `SDA = GPIO26`
- `SCL = GPIO32`
- `ADDR = 0x53`

See the hardware reference and firmware README for the wiring and firmware-side
network defaults:

- [`hardware/README.md`]({_blob_url(repo_url, "hardware/README.md")})
- [`firmware/esp/README.md`]({_blob_url(repo_url, "firmware/esp/README.md")})

## Before you take the kit to a vehicle

- Charge each Battery Base.
- Label the physical nodes so you can match them to locations in the UI.
- Decide how many locations you want to instrument for the first session.
- If you want automatic speed, prepare a GPS receiver; otherwise plan to use the
  manual speed option in Settings.
"""


def _install_page(repo_url: str) -> str:
    return f"""# Initial Install

There are two supported ways to get VibeSensor onto a Raspberry Pi:

1. a **prebuilt Pi image** (best for repeatable deployments),
2. or a **manual install** on Raspberry Pi OS Lite.

If someone on your team already prepared the SD card for you, you can skip
straight to the **First boot** section below.

## Option A: Prebuilt Pi image

This is the easiest path for a workshop or repeat deployment because the image
already includes the server, the built web UI, and the hotspot services.

### If you are preparing the image yourself

On a Linux machine with Docker:

```bash
git clone https://github.com/Skamba/VibeSensor.git
cd VibeSensor
./infra/pi-image/pi-gen/build.sh
```

The image artifact is written under:

- `infra/pi-image/pi-gen/out/vibesensor-rpi3a-plus-trixie-lite.img`

Flash that image to a microSD card with Raspberry Pi Imager, insert the card
into the Pi 3 A+, and power it on.

Detailed image-build notes live here:
[`infra/pi-image/pi-gen/README.md`]({_blob_url(repo_url, "infra/pi-image/pi-gen/README.md")}).

## Option B: Manual install on Raspberry Pi OS Lite

If you want to start from a stock Raspberry Pi OS Lite card instead of the
prebuilt image, run the repo install scripts on the Pi:

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/Skamba/VibeSensor.git
cd VibeSensor
sudo ./apps/server/scripts/install_pi.sh
sudo ./apps/server/scripts/hotspot_nmcli.sh
```

This path is useful when you want to control the base OS image yourself.

## First boot

After the Pi boots:

1. Look for the Wi-Fi network `VibeSensor`.
2. Connect a phone, tablet, or laptop to that hotspot.
3. Open `http://10.4.0.1`.
4. If the primary listener is not serving, try `http://10.4.0.1:8000`.

Default recovery credentials on generated images are:

- SSH user: `pi`
- SSH password: `vibesensor`

The default hotspot is intentionally prototype-friendly:

- SSID: `VibeSensor`
- Password: empty / open hotspot

Change those defaults before field deployment outside a trusted environment.

## Flash and power the sensor nodes

The firmware defaults already match the Pi hotspot in this repo:

- SSID `VibeSensor`
- empty PSK
- server IP `10.4.0.1`
- UDP ports `9000/9001`

To flash a node:

```bash
cd firmware/esp
pio run -t upload
pio device monitor
```

Once the node is flashed and powered, it should connect to the Pi automatically
when it is in range.

If you intentionally use a different Wi-Fi name, password, or server IP, create
`include/vibesensor_network.local.h` from the example file and rebuild the
firmware. That advanced path is documented in:
[`firmware/esp/README.md`]({_blob_url(repo_url, "firmware/esp/README.md")}).

## First checks after install

- Open the dashboard and confirm the UI loads.
- Wait for one or more sensors to appear in the live client list.
- If you support the device over SSH, you can also verify:

```bash
curl -sf http://10.4.0.1/api/health || curl -sf http://10.4.0.1:8000/api/health
curl -sf http://10.4.0.1/api/clients || curl -sf http://10.4.0.1:8000/api/clients
```
"""


def _config_page(repo_url: str) -> str:
    return f"""# Configure VibeSensor

Most day-to-day setup happens from the **Settings** view in the browser UI. The
important operator tasks are:

1. choose the car you are testing,
2. assign sensor names and locations,
3. choose the speed source,
4. and only then adjust analysis settings if the defaults are not enough.

## Cars

![Cars tab](images/settings-cars.png)

Use the **Cars** tab to store one or more vehicle profiles and pick the active
car for the next run.

Make sure the active car matches the vehicle on the lift or road test, because
wheel and drivetrain information feeds the order-tracking analysis.

The important values to get right are:

- tire width / aspect / rim size,
- final drive ratio,
- and current gear ratio for the gear used during the run.

If you test multiple cars, keep separate saved profiles and switch the active
car before each session.

## Sensor names and locations

Use Settings to give each sensor a clear name and location so the Live view,
History view, heatmaps, and PDF reports read like the real car instead of
anonymous device IDs.

Typical location labels include:

- front left wheel,
- front right wheel,
- rear left wheel,
- rear right wheel,
- engine bay.

If you are unsure which physical node is which, use the identify/blink action to
match the on-screen entry to the ATOM Lite in your hand.

## Analysis settings

![Analysis settings](images/settings-analysis.png)

The **Analysis** tab controls how tightly VibeSensor matches wheel, driveshaft,
and engine orders.

Recommended operator approach:

- Start with the defaults.
- Save a correct car profile first.
- Change analysis tuning only when you have a specific reason, such as an
  unusual drivetrain or a known tolerance issue.
- If experimentation made things worse, use the reset-to-defaults path.

## Speed source

![Speed source](images/settings-speed-source.png)

The **Speed Source** tab decides how VibeSensor gets vehicle speed for
speed-aware order tracking.

- Use **GPS** for normal road tests when you have a receiver connected and good
  sky view.
- Use **Manual** speed for indoor work, dyno/bench work, or whenever GPS is not
  available.

If GPS has poor signal or no fix, switching to manual speed is usually better
than retrying the same bad GPS setup.

## Language, units, and operator preferences

User-facing preferences such as language and speed units are stored with the
runtime settings, so you can set the device up for the operator who uses it.

## Workshop/admin configuration on the Pi

For changes that live below the browser UI, edit the Pi config file:

- `/etc/vibesensor/config.yaml`

Common admin-level changes include:

- changing the hotspot name (`ap.ssid`),
- adding a hotspot password (`ap.psk`),
- changing history retention (`logging.run_retention_days`),
- or disabling GPS on a bench system (`gps.gps_enabled`).

Validate the file before restarting services:

```bash
vibesensor-config-preflight /etc/vibesensor/config.yaml
```

Key references:

- Config reference: [`docs/configuration_reference.md`]({_blob_url(repo_url, "docs/configuration_reference.md")})
- Pi/backend operations: [`apps/server/README.md`]({_blob_url(repo_url, "apps/server/README.md")})
"""


def _run_page() -> str:
    return """# Run a Diagnostic Drive

This is the normal operator workflow once the Pi and sensor nodes are already
installed.

## 1. Mount the sensors

- Place the sensors on the areas you want to compare.
- Keep the sensor locations consistent with the names you assign in Settings.
- Make sure the Battery Base on each node is charged before the run.

The most useful first pass is usually multiple simultaneous locations so you can
compare vibration strength across the car in one recording.

## 2. Confirm the setup in Live

![Live dashboard](images/live-dashboard.png)

Before driving, use the **Live** view to confirm:

- the expected sensors are connected,
- the active car is correct,
- the speed source looks sensible,
- and the spectrum traces are actually moving.

If the screen is static or a sensor is missing, fix that before you start
recording.

## 3. Record the run

When everything looks healthy:

1. press **Start**,
2. drive through the speed range where the vibration is noticeable,
3. hold steady speeds long enough for the order-tracking logic to settle,
4. and press **Stop** once you captured the complaint clearly.

If you are comparing before/after repairs, try to keep the route, speed range,
and sensor placement as similar as possible between runs.

## 4. Review the result in History

![History overview](images/history-overview.png)

Open **History** after the run to:

- compare saved runs,
- inspect the most likely source,
- review the heatmap and supporting evidence,
- and export a PDF report or a ZIP bundle.

Typical examples the current product surfaces well are:

- wheel imbalance,
- driveshaft-related vibration,
- engine-order vibration.

If you want the plain-language explanation of how the system uses repeated
frequency patterns plus mounted sensor locations to narrow down a fault, see
[How VibeSensor Diagnoses Issues](How-VibeSensor-Diagnoses-Issues).

## 5. Save or share the evidence

Use the built-in exports when you want to hand findings to a technician,
customer, or teammate:

- **PDF** for a human-readable report,
- **ZIP export** when you want the raw samples and run details too.

## Operator tips

- Always check the active car before starting a run.
- If GPS is unreliable, switch to manual speed instead of forcing a bad capture.
- Run again after a repair so you can compare the new result against the old one
  in History.
"""


def _diagnosis_page() -> str:
    return """# How VibeSensor Diagnoses Issues

VibeSensor does not decide from one sensor in isolation. The useful clue is the
combination of:

- **frequency or order**: the same repeating vibration showing up at a specific
  Hz value or a wheel / driveshaft / engine order,
- **location**: which mounted sensor sees that vibration most strongly,
- **speed context**: whether that vibration grows or repeats in the speed range
  where the complaint happens.

## Why frequency matters

Many vehicle problems repeat at a predictable rate.

- A wheel-related issue tends to show up at wheel order.
- A driveshaft issue tends to show up at driveshaft order.
- An engine-related issue tends to follow engine order.

That means VibeSensor is not only looking for "something is shaking." It is
looking for **what repeating pattern** is present.

## Why sensor location matters

The same vibration can be visible across more than one sensor, but it is often
strongest near the source.

Examples:

- If a repeating vibration is strongest at the front-left wheel sensor and much
  weaker elsewhere, that points more toward that corner than toward the rear of
  the car.
- If multiple wheel sensors all show the same pattern strongly, the source may
  be more central or may be propagating through the chassis.
- If an engine-bay sensor sees the strongest matching pattern, that shifts the
  suspicion away from a single wheel corner.

This is why correct sensor naming and correct mounted locations matter so much.

## How the pieces come together

During a run, VibeSensor compares the same vibration event across all connected
sensors and asks:

1. what repeating frequency or order is present,
2. where it is strongest,
3. and whether it appears in the speed range where the complaint happens.

If one repeating frequency is strongest at the front-left wheel and it tracks
the wheel-related order for the active car, that points much more toward that
corner than toward the engine bay or rear axle.

If that same pattern matches the expected behavior of a driveshaft or engine
order instead, VibeSensor ranks those causes higher even if a wheel sensor also
picked up some of the vibration.

## Why the car profile matters

The active car profile gives VibeSensor the context it needs for order tracking,
such as tire and drivetrain information.

If the wrong car profile is selected, the system can still show useful raw
vibration data, but the order-matching part of the diagnosis is less reliable.

## What gives the best results

- Use multiple sensors at the same time when possible.
- Assign the correct location to each sensor in Settings.
- Make sure the active car matches the vehicle being tested.
- Capture the speed range where the vibration is actually noticeable.
- Compare before/after runs with similar sensor placement and route conditions.

That combination gives VibeSensor the best chance to match both **what
frequency the issue follows** and **where in the car it is strongest**.
"""


def _troubleshooting_page(repo_url: str) -> str:
    return f"""# Troubleshooting and Maintenance

This page is for the most common field problems: no hotspot, no sensors, no
speed, or an unhealthy Pi.

## Quick checks

- Try `http://10.4.0.1`.
- If that does not load, try `http://10.4.0.1:8000`.
- Confirm the Pi hotspot `VibeSensor` is visible.
- Confirm the sensor nodes are powered and nearby.

## Common problems

| Problem | Check first | What to do next |
| --- | --- | --- |
| I cannot see the hotspot | Wait for the Pi to finish booting | Reboot the Pi and check the hotspot service if you have SSH access |
| The dashboard opens but no sensors appear | Battery charge, firmware flashed, sensor in range | Reflash the node if needed and confirm it still targets `VibeSensor` / `10.4.0.1` |
| GPS speed is empty or unstable | GPS receiver present, sky view available | Switch to manual speed for indoor or poor-signal work |
| The run finished but History looks wrong | Active car, sensor names, speed source | Run another capture after correcting setup so the comparison is clean |
| The Pi was fine before but now behaves strangely | Service health and disk space | Review system status, logs, and the backend health endpoint |

## Service commands for the person supporting the device

If you have SSH access to the Pi:

```bash
sudo systemctl status vibesensor.service vibesensor-hotspot.service --no-pager
sudo systemctl restart vibesensor.service
sudo systemctl restart vibesensor-hotspot.service
sudo journalctl -u vibesensor.service -u vibesensor-hotspot.service -n 200 --no-pager
```

The prebuilt image defaults are:

- SSH user: `pi`
- SSH password: `vibesensor`

## Health and API checks

These are useful when the browser UI is up but you want to confirm the backend
state directly:

```bash
curl -sf http://10.4.0.1/api/health || curl -sf http://10.4.0.1:8000/api/health
curl -sf http://10.4.0.1/api/clients || curl -sf http://10.4.0.1:8000/api/clients
```

Healthy devices should reach `startup_state: ready`.

## Changing Wi-Fi name, password, or other Pi settings

Edit:

- `/etc/vibesensor/config.yaml`

Then validate and restart the affected service:

```bash
vibesensor-config-preflight /etc/vibesensor/config.yaml
sudo systemctl restart vibesensor.service
sudo systemctl restart vibesensor-hotspot.service
```

## When you need the deeper references

- Operational runbooks: [`docs/operational-runbooks.md`]({_blob_url(repo_url, "docs/operational-runbooks.md")})
- Config reference: [`docs/configuration_reference.md`]({_blob_url(repo_url, "docs/configuration_reference.md")})
- Server/Pi operations: [`apps/server/README.md`]({_blob_url(repo_url, "apps/server/README.md")})
- Sensor firmware setup: [`firmware/esp/README.md`]({_blob_url(repo_url, "firmware/esp/README.md")})
- Pi image build/install: [`infra/pi-image/pi-gen/README.md`]({_blob_url(repo_url, "infra/pi-image/pi-gen/README.md")})
"""


def _sidebar() -> str:
    return """### VibeSensor Wiki

- [Home](Home)
- [Get the Hardware](Get-the-Hardware)
- [Initial Install](Initial-Install)
- [Configure VibeSensor](Configure-VibeSensor)
- [Run a Diagnostic Drive](Run-a-Diagnostic-Drive)
- [How VibeSensor Diagnoses Issues](How-VibeSensor-Diagnoses-Issues)
- [Troubleshooting and Maintenance](Troubleshooting-and-Maintenance)
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
            "missing expected screenshot files in output dir: "
            f"{missing_text}. Run `npm --prefix apps/ui run wiki:screenshots -- "
            f"{output_dir / 'images'}` first."
        )

    release_note = _release_label(args.release_version, args.commit_sha)
    _write(output_dir / "Home.md", _home_page(args.repo_url, release_note))
    _write(output_dir / "Get-the-Hardware.md", _hardware_page(args.repo_url))
    _write(output_dir / "Initial-Install.md", _install_page(args.repo_url))
    _write(
        output_dir / "Configure-VibeSensor.md",
        _config_page(args.repo_url),
    )
    _write(
        output_dir / "Run-a-Diagnostic-Drive.md",
        _run_page(),
    )
    _write(
        output_dir / "How-VibeSensor-Diagnoses-Issues.md",
        _diagnosis_page(),
    )
    _write(
        output_dir / "Troubleshooting-and-Maintenance.md",
        _troubleshooting_page(args.repo_url),
    )
    _write(output_dir / "_Sidebar.md", _sidebar())
    print(f"Generated wiki bundle in {output_dir}")


if __name__ == "__main__":
    main()
