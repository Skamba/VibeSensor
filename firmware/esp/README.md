# ESP32 Firmware

PlatformIO firmware for the M5Stack ATOM Lite (ESP32-PICO) that reads an
ADXL345 accelerometer at 800 Hz and streams 100 ms sample frames to the Pi
server over UDP. The default build target stays on the ATOM Lite, and the repo
also carries an experimental ESP32-C3 compile-only environment to catch
board-specific assumptions earlier.

## Features

- Wi-Fi station mode to Pi AP (`VibeSensor`)
- HELLO + DATA protocol packets
- Buffered frame queue to reduce sample loss during short Wi-Fi stalls
- UDP command listener for identify blink with ACK response
- Identify command blinks only the single onboard RGB LED on ATOM Lite
- ADXL345 I2C driver at 800 Hz with error-checked initialisation
- Dedicated high-priority sampling task owns `Wire` and ADXL345 access, drains
  the sensor FIFO on a dithered poll interval, stamps every sample on the ESP
  clock and resamples onto an exact 800 Hz grid (see "Sample timing" below)
- FIFO overflows are counted, with the samples they lost, and start a new frame
- Bounded sample handoff queue decouples sensor acquisition from Wi-Fi, ACK, LED,
  and status/reporting work in the main loop
- No synthetic vibration injection in production builds

Authoritative protocol and port contract: `docs/protocol.md`
(generated from code + shared contracts).

## Project Structure

```
firmware/esp/
├── src/
│   ├── main.cpp              Setup/loop orchestration only
│   ├── runtime_config.h      Runtime constants and build-flag overrides
│   ├── runtime_status.*      Shared counters and status reporting
│   ├── runtime_queue.*       Frame queue state and ACK compaction
│   ├── runtime_sampling.*    Sampling task: FIFO drain, retries, re-init
│   ├── runtime_transport.*   HELLO/DATA/ACK send/receive handling
│   ├── runtime_wifi.*        Wi-Fi scan, connect, and retry flow
│   └── runtime_led.*         Identify LED state machine
├── lib/
│   ├── adxl345/              I2C driver for ADXL345 accelerometer
│   ├── sample_timing/        Sample clock, resampler, poll dither (host-tested)
│   └── vibesensor_proto/     Protocol packet builder
├── include/
│   ├── vibesensor_network.local.example.h   Network override template
│   └── vibesensor_network.local.h           Local overrides (gitignored)
└── platformio.ini            PlatformIO build config
```

## Runtime module layout

- `main.cpp` owns startup wiring and the non-sampling service order.
- `runtime_queue.*` owns buffered frame state, enqueue/drop behavior, and ACK
  compaction.
- `runtime_sample_handoff.*` owns the bounded raw-sample handoff queue between
  the sampling task and the main loop.
- `runtime_sampling.*` owns the dedicated sampling task, ADXL345 runtime, FIFO
  drain, read retry / bus recovery / re-init policy; the timing maths lives in
  `lib/sample_timing`.
- `runtime_transport.*` owns HELLO, DATA, ACK, and control-packet handling.
- `runtime_wifi.*` owns target AP discovery plus reconnect/backoff behavior.
- `runtime_led.*` owns identify blinking for the single onboard RGB LED.
- `runtime_status.*` owns counters, last-error tracking, and periodic status
  snapshots.

## Error Handling

- **I2C init**: Every register write during `ADXL345::begin()` is validated;
  if any write fails the sensor is marked unavailable and the sampling task
  falls back to bounded reinit attempts instead of injecting held or synthetic
  samples.
- **I2C reads**: FIFO status reads and FIFO data reads are classified
  separately. The sampling task tries one immediate retry, then one fast
  bus-recovery + retry step, before escalating to the heavier ADXL reinit path.
- **Partial FIFO progress**: samples read before a burst-read failure are kept.
- **FIFO overflow**: a poll that finds the 32-entry FIFO full counts an
  overflow; if the sample clock then sees samples missing they are counted as
  lost (`lost`/`resync` in the status line) and the next frame starts after
  the gap, so `t0_us` stays true.
- **Wi-Fi**: Automatic reconnect with configurable retry interval
  (`kWifiRetryIntervalMs`).

## Build and Flash

Default ATOM Lite build and flash path:

```bash
cd firmware/esp
pio run -e m5stack_atom -t upload
pio device monitor
```

Experimental ESP32-C3 compile coverage:

```bash
cd firmware/esp
pio run -e esp32-c3-devkitm-1
```

The ESP32-C3 environment is compile coverage only for now. It keeps the current
runtime defaults from `src/runtime_config.h`, which still assume the ATOM Lite
LED and ADXL345 pin mapping. Override those settings before treating a C3 build
as real hardware support.

CI firmware parity also checks protocol fixtures and native tests:

```bash
python tools/firmware/generate_protocol_contract_fixtures.py --check
cd firmware/esp
pio test -e native
```

## Configure

Default network target already matches the Pi hotspot configuration:

- SSID `VibeSensor`
- PSK empty (open test AP)
- Server IP `10.4.0.1`
- UDP ports `9000/9001`

At boot the firmware loads the hotspot SSID/PSK from NVS (Preferences
namespace `vs_wifi`, keys `ssid` and `psk`; a stored SSID without `psk` means an
open hotspot) and falls back to the compile-time values below when NVS holds
none (`load_wifi_credentials` in `src/runtime_wifi.cpp`). The Pi flasher
(*Settings → ESP Flash*) erases the chip and writes an NVS image built from the
Pi's current `ap.ssid` / `ap.psk`
(`apps/server/vibesensor/updates/firmware/sensor_wifi_nvs.py`), so a sensor
flashed from the Pi always joins that Pi's hotspot. `pio run -t upload` does not
erase NVS: a sensor once flashed from a Pi keeps those stored credentials over
the compile-time ones until you run `pio run -t erase`.

For canonical message IDs/packet sizes and port values, use `docs/protocol.md`.

Optional override via local file (recommended for non-default networks):

1. Copy `include/vibesensor_network.local.example.h` to `include/vibesensor_network.local.h`
2. Edit:
  - `VIBESENSOR_WIFI_SSID`
  - `VIBESENSOR_WIFI_PSK`
  - `VIBESENSOR_SERVER_IP_OCTETS`
3. Build and flash again

`include/vibesensor_network.local.h` is gitignored; do not commit secrets.

The firmware has no on-device provisioning flow: credentials come from the Pi
flasher's NVS image or the build-time defaults, never from the sensor at
runtime. The offline-first Pi hotspot remains the deployment authority.

Runtime-critical firmware parameters can be overridden without editing source by
adding build flags in `platformio.ini` (`build_flags`).

Shared ESP32 build settings live in the `env:firmware_esp32` base environment
inside `platformio.ini`. Board-specific environments extend that base and pin
third-party firmware libraries through PlatformIO registry dependencies, including
`adafruit/Adafruit NeoPixel@1.15.5`.

## Platform upgrades

The firmware builds on Arduino-ESP32 3.3.12 (ESP-IDF 5.5) through the community
[pioarduino](https://github.com/pioarduino/platform-espressif32) platform, pinned
to one release zip in `platformio.ini`. The official `platformio/espressif32`
platform stops at Arduino-ESP32 2.0.17.

Dependabot cannot track a URL platform, so check for a newer stable release when
you bump the other dependencies:

```bash
curl -s https://api.github.com/repos/pioarduino/platform-espressif32/releases/latest | grep tag_name
```

`releases/latest` skips pre-releases (the `-RC` builds); stay on stable releases.
To upgrade, change the release tag in the `platform` URL, then run
`pio test -e native` and `pio run -e m5stack_atom -e esp32-c3-devkitm-1`, and
check Espressif's Arduino-ESP32 migration notes for the new core. A new
pioarduino release changes the CI PlatformIO cache key, so the first CI run
downloads the toolchain again.

Build output per environment in `.pio/build/<env>/`: `bootloader.bin` (0x1000 on
ESP32, 0x0 on ESP32-C3), `partitions.bin` (0x8000), `firmware.bin` (the app,
0x10000 with the default partition table) and `firmware.factory.bin` (all of them
merged; not shipped). The release workflow ships the first three plus
`flash.json`, which `tools/release/main_release.py` derives from the build:

- each env's `chip` (the esptool `--chip` name) comes from the chip ID in the
  `firmware.bin` image header;
- bootloader and partition-table offsets come from PlatformIO's flash images
  (`pio project metadata`), the same offsets `pio run -t upload` uses;
- the app offset comes from the built partition table (factory app, else `ota_0`).

Environments are listed alphabetically. The Pi flasher (*Settings → ESP Flash*)
always flashes the `m5stack_atom` environment by name (`SENSOR_FIRMWARE_ENV` in
`apps/server/vibesensor/updates/firmware/esp_flash_types.py`) and passes its
`chip` to esptool, so other envs in the bundle (such as the ESP32-C3 build) are
never picked by position. Release validation fails when `m5stack_atom` is missing.

Supported override macros:

- `VIBESENSOR_SAMPLE_RATE_HZ`
- `VIBESENSOR_FRAME_SAMPLES`
- `VIBESENSOR_MAX_UDP_PAYLOAD`
- `VIBESENSOR_SERVER_DATA_PORT`
- `VIBESENSOR_SERVER_CONTROL_PORT`
- `VIBESENSOR_CONTROL_PORT_BASE`
- `VIBESENSOR_FRAME_QUEUE_LEN_TARGET`
- `VIBESENSOR_FRAME_QUEUE_LEN_MIN`
- `VIBESENSOR_WIFI_CONNECT_TIMEOUT_MS`
- `VIBESENSOR_WIFI_RETRY_BACKOFF_MS`
- `VIBESENSOR_WIFI_RETRY_INTERVAL_MS`
- `VIBESENSOR_WIFI_INITIAL_CONNECT_ATTEMPTS`
- `VIBESENSOR_WIFI_SCAN_INTERVAL_MS`
- `VIBESENSOR_SAMPLING_TASK_CORE`
- `VIBESENSOR_SAMPLING_POLL_INTERVAL_US` / `VIBESENSOR_SAMPLING_POLL_JITTER_US`
  (FIFO poll interval and its dither; keep the jitter, see "Sampling cadence note")

Example:

```ini
build_flags =
  -D CORE_DEBUG_LEVEL=0
  -D VIBESENSOR_ATOM_ESP32_PICO=1
  -D VIBESENSOR_SAMPLE_RATE_HZ=1000
  -D VIBESENSOR_FRAME_SAMPLES=80
  -D VIBESENSOR_WIFI_RETRY_INTERVAL_MS=2500
```

Settings that still remain in `src/runtime_config.h`:

- `kClientName`
- I2C settings (`kI2cSdaPin`, `kI2cSclPin`, `kAdxlI2cAddr`)

## Sample timing

The sampling task polls the ADXL345 FIFO (stream mode, 32 entries plus the
output registers) and drains everything in it on each poll. It does not pace
the samples: the ADXL345 does, with its own oscillator, which is not trimmed.
One ATOM Lite unit measured ~823 Hz for a nominal 800 Hz (+2.9 %), wandering
by a few tenths of a percent over seconds.

- `SampleClock` (`lib/sample_timing`) stamps each drained sample on the ESP
  clock. Each poll's FIFO depth places the oldest entry in time; a
  second-order loop tracks the sensor's real period and phase from those
  estimates (Q16 fixed-point microseconds).
- `Resampler` interpolates the stamped stream (32-tap Kaiser-windowed sinc,
  64 phases) onto an exact grid of the declared rate on the ESP clock. Frames
  therefore carry exactly 800 samples per second and each `t0_us` is the real
  time of the frame's first sample, as the protocol says; the server needs no
  knowledge of the sensor's oscillator.

Before this (firmware up to cf117a43e) a per-sample one-shot timer was re-armed
with a relative step, so callback latency stretched every period: the sensor
delivered ~742-758 samples/s while `t0_us` advanced on the nominal 800 Hz
schedule, falling ~55 ms per second behind real time, and the FIFO overflowed
silently. Measured after the change: 799.6 samples/s at the Pi (2.5 min), the
lag of `t0_us` behind the recording start stays at 40-70 ms over 10 minutes
(was 14.5 s and growing), and the overflow counter stays at its boot value.

## Sampling cadence note

The I2C read cadence must not be periodic. #507 found that fixed 8-sample FIFO
bursts imprinted a line plus harmonics on the spectrum (the bus/supply activity
of each read couples into the measurement); #508 randomised the refill sizes
through a prefetch ring and added this note. 062b29fe2 changed the
randomisation to a deterministic dither, and 322861d41 ("isolate sampling
from loop work") made refills fully deterministic again and deleted the note;
raw run 41079ae1 then showed a 47.03 Hz line with harmonics at ~1 LSB on all
three axes.

The poll interval is now drawn uniformly from
`VIBESENSOR_SAMPLING_POLL_INTERVAL_US` +/- `VIBESENSOR_SAMPLING_POLL_JITTER_US`
(10 +/- 5 ms, xorshift32), so burst sizes vary between ~4 and ~13 samples with
bounded work per poll. A/B at rest on hardware (45 s raw captures, Hann FFT,
LSB):

| Poll cadence | Line | x / y / z |
|---|---|---|
| fixed 10 ms (`JITTER_US=0`) | 97.65 Hz (poll rate) | 1.13 / 1.26 / 1.36, plus 195.3 Hz and +/-9.8 Hz sidebands |
| dithered 10 +/- 5 ms | none above the ~0.1 LSB floor | 0.11 / 0.13 / 0.15 at 97.65 Hz |

Do not make the poll or burst cadence periodic again.

The ADXL345/I2C path uses bounded staged recovery inside the sampling task:
- one immediate retry after a transient read failure
- one fast bus reinitialization + retry step before heavier recovery
- full ADXL reinit only after the lighter path is exhausted or the failure class
  points at deeper sensor-state loss

On ESP32 dual-core builds, the sampling task is now pinned explicitly instead of
inheriting the startup core. By default it targets the opposite core from the
configured Arduino loop task (`CONFIG_ARDUINO_RUNNING_CORE` / `ARDUINO_RUNNING_CORE`);
if the loop task is configured with no affinity, the firmware falls back to core
`0`. Override with `VIBESENSOR_SAMPLING_TASK_CORE=<core>` when you need a
different placement.

Default ATOM Lite Unit-port mapping used in this repo (4-pin Unit cable):

- `SDA = GPIO26`
- `SCL = GPIO32`
- `ADDR = 0x53`
