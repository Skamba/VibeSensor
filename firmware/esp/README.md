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
- Dedicated high-priority sampling task owns `Wire`, ADXL345 access, sample cadence,
  and the software prefetch ring
- Deterministic deeper prefetch targets keep a materially larger software cushion
  before samples are declared missed
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
│   ├── runtime_sampling.*    ADXL345 sampling, prefetch, and catch-up logic
│   ├── runtime_transport.*   HELLO/DATA/ACK send/receive handling
│   ├── runtime_wifi.*        Wi-Fi scan, connect, and retry flow
│   └── runtime_led.*         Identify LED state machine
├── lib/
│   ├── adxl345/              I2C driver for ADXL345 accelerometer
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
- `runtime_sampling.*` owns the dedicated sampling task, ADXL345 runtime,
  prefetch ring, sensor re-init, and late-handling policy.
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
  separately. The sampling task now tries one immediate bounded refill retry,
  then one fast bus-recovery + retry step, before escalating to the heavier
  ADXL reinit path.
- **Partial FIFO progress**: samples completed before a burst-read failure are
  preserved and appended into the software prefetch ring before miss accounting
  is considered.
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

## Configure

Default network target already matches the Pi hotspot configuration:

- SSID `VibeSensor`
- PSK empty (open test AP)
- Server IP `10.4.0.1`
- UDP ports `9000/9001`

For canonical message IDs/packet sizes and port values, use `docs/protocol.md`.

Optional override via local file (recommended for non-default networks):

1. Copy `include/vibesensor_network.local.example.h` to `include/vibesensor_network.local.h`
2. Edit:
  - `VIBESENSOR_WIFI_SSID`
  - `VIBESENSOR_WIFI_PSK`
  - `VIBESENSOR_SERVER_IP_OCTETS`
3. Build and flash again

`include/vibesensor_network.local.h` is gitignored; do not commit secrets.

Wi-Fi credentials are intentionally configured at build time (default header or
gitignored local override), not mutated at runtime. The offline-first Pi
hotspot remains the deployment authority, so the firmware/server pair shares a
stable network target instead of exposing an on-device provisioning flow.

Runtime-critical firmware parameters can be overridden without editing source by
adding build flags in `platformio.ini` (`build_flags`).

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

## Sampling cadence note

Sampling now runs in a dedicated high-priority task released at the target
sample cadence (the stock path is 800 Hz / `1250 us`). That task is the sole
owner of `Wire`, ADXL345 access, the software prefetch ring, and the due-time
schedule. The main loop no longer sits in front of sensor acquisition; it drains
already-produced samples from a bounded handoff queue, builds frames, and then
handles transport, Wi-Fi, LED, and status work.

The software prefetch policy now maintains a deeper deterministic cushion:
steady-state refills target `24` buffered samples, while late or refill-shortfall
conditions target the full `32`-sample buffer. Late handling is now based on
real recovery context (prefetch occupancy, handoff headroom, and recent refill
progress) instead of a fixed loop-time budget.

The ADXL345/I2C path now uses bounded staged recovery inside the sampling task:
- one immediate retry after a transient refill/read failure
- one fast bus reinitialization + retry step before heavier recovery
- full ADXL reinit only after the lighter path is exhausted or the failure class
  points at deeper sensor-state loss

This is still a software-only resilience improvement: the code now gives
transient bus faults a bounded chance to recover before declaring missed
samples, but the real on-device benefit still needs hardware to prove.

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
