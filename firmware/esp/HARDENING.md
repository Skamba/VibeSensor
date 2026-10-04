# ESP Firmware hardening notes

Runtime ownership now lives in `src/runtime_*.{h,cpp}`, with `src/main.cpp`
reduced to startup wiring plus non-sampling service orchestration around the
dedicated sampling task.

## What was fixed

- Added compile-time guardrails for runtime tuning:
  - sample rate is clamped to `25..3200 Hz`
  - frame size is clamped so DATA packets always fit UDP MTU (`<= 1500` bytes)
- Hardened ADXL345 reads:
  - I2C register and burst reads now return explicit success/failure
  - FIFO overflows and I2C errors are detected and counted
  - repeated sensor read errors trigger bounded sensor re-init attempts
  - staged read recovery does one immediate retry, then one fast
    bus-level recovery + retry, before escalating to the heavier reinit path
  - FIFO status-read failures and FIFO data-read failures are tracked separately
- Hardened Wi-Fi reconnect behavior:
  - reconnect now uses exponential backoff with jitter and an upper cap (`60s`)
  - retry failure counter uses saturating increment (prevents wrap-around)
- Added reliability counters and status snapshots:
  - periodic `Serial` status line every 10s with queue, tx, sensor, wifi, parse and last-error fields
  - transmit packing/send failures and parser failures are now counted
- Added command guardrail:
  - identify blink duration is capped to `10s` to prevent long/accidental lockouts
- Added runtime watchdog and reboot diagnostics:
  - startup now logs `esp_reset_reason()` so crash/reset causes are visible over serial
  - the cooperative Arduino loop is now enrolled in the ESP task watchdog with a 15s timeout
- Added explicit startup control-plane handshake:
  - firmware now advertises HELLO-ack capability, waits for a server `HELLO_ACK`
    before sending DATA frames, and keeps the existing periodic HELLO beacons for
    control-port discovery and liveness
- Moved sampling onto a dedicated periodic task with explicit ownership:
  - the sampling task is the sole owner of `Wire`, ADXL345 access, and the
    sample clock
  - the main loop only drains produced samples, builds frames, and services
    transport, Wi-Fi, LED, and periodic logging
  - a bounded sample handoff queue now forms the producer/consumer boundary
  - the sampling task is pinned with an explicit core selection policy instead
    of inheriting whatever core happened to run startup; startup logging now
    prints the loop/current/sampling core choice once for validation
- Replaced timer-paced sampling with sensor-paced sampling (see README
  "Sample timing"):
  - the old per-sample one-shot timer was re-armed with a relative step, so
    callback latency stretched every period: ~742-758 samples/s were delivered
    while `t0_us` advanced on the nominal 800 Hz schedule (~55 ms/s behind real
    time) and the ADXL345 FIFO overflowed silently
  - the task now drains the whole FIFO on a dithered poll interval, stamps
    every sample with a second-order sample clock locked to the ESP clock, and
    resamples onto an exact grid of the declared rate; FIFO overflows and the
    samples they lost are counted and start a new frame
- Fixed ignored `beginPacket()` return value in `send_hello()` and `send_ack()`:
  - both functions now check whether `beginPacket()` succeeded before calling
    `write()` / `endPacket()`, preventing writes into an invalid UDP send state
- Fixed strict equality length check in `parse_data_ack()`:
  - changed `len != kDataAckBytes` to `len < kDataAckBytes` so future protocol
    extensions that append optional trailing fields are not silently rejected
- Bounded `service_data_rx()` loop:
  - the `while(true)` ACK-drain loop is now capped at `kMaxDataAckPacketsPerLoop`
    iterations per `loop()` call, preventing a burst of incoming ACKs from starving
    all other cooperative tasks
- Queue allocation log:
  - a `Serial` warning is emitted when the heap frame-queue allocation fails
    entirely so the operator knows buffering is unavailable; on success the
    allocated slot count and size are logged once at startup
- Fixed blocking WiFi scan in `service_wifi()`:
  - `refresh_target_ap()` previously used `WiFi.scanNetworks(false, ...)` (synchronous),
    which could stall the cooperative loop for 1–4+ seconds during reconnection,
    causing hundreds of dropped accelerometer samples
  - `service_wifi()` now uses `start_ap_scan()` (async, non-blocking) during the
    backoff idle period and `poll_ap_scan()` to consume results without stalling;
    the blocking `refresh_target_ap()` is retained for the startup path only, where
    blocking before sampling begins is acceptable
- Fixed unnecessary NVS flash writes in `service_wifi()`:
  - `WiFi.disconnect(true, true)` with `eraseap=true` was called on every reconnect
    attempt, causing a flash write per retry; credentials are always supplied
    programmatically so erasing is unnecessary; changed to `eraseap=false`
- Fixed partial sensor read results silently discarded:
  - when `read_samples()` returned both `io_error=true` and a non-zero `read_count`
    (valid samples delivered before the I2C failure), the sampling path ignored them
    entirely due to `else if (read_count > 0)` gating; changed to process valid
    partial samples unconditionally while keeping the consecutive-error counter
    update only on fully clean reads (no io_error) as before
- Removed dead code in `parse_mac()`:
  - the `values[i] > 0xFF` guard in the MAC-parsing loop was unreachable because
    `%2x` in `sscanf` reads at most two hex digits (0–255); removed to save flash
- Added native firmware contract/queue coverage:
  - the native PlatformIO suite now exercises the firmware UDP protocol codec against
    fixtures generated from the backend Python codec and covers queue frame building,
    overflow/drop accounting, and ACK-driven eviction behavior
- Pinned the firmware PlatformIO platform:
  - `platform` points at one exact pioarduino release zip (Arduino-ESP32 3.x on
    ESP-IDF 5), which fixes the Arduino core and toolchain versions, so local and
    CI firmware builds stop drifting with upstream default updates
- Added PR-time firmware native CI coverage:
  - CI now verifies the generated protocol fixtures are in sync and runs
    `pio test -e native` automatically on pull requests


## Build and test

```bash
cd firmware/esp
python3 ../../tools/firmware/generate_protocol_contract_fixtures.py --check
pio run -e m5stack_atom
pio run -e esp32-c3-devkitm-1
pio test -e native
```

`esp32-c3-devkitm-1` is an experimental compile-only target. It helps catch
single-core and board-specific build assumptions, but the runtime pin defaults
still target the ATOM Lite layout.

## Runtime counters/status to monitor

Status snapshots are printed as:

`status wifi=... q=current/cap drop=... tx_fail={...} sensor={...} wifi_retry={...} parse={...} last_error=code@ms`

Key fields:

- `drop`: queue overflow drops
- `tx_fail.pack|begin|end`: packet encoding / UDP begin / UDP send failures
- `sensor.err`: sensor I2C read failures
- `sensor.stat|data`: FIFO status-register failures vs FIFO data-read failures
- `sensor.ovf`: polls that found the ADXL345 FIFO full (one at boot is normal:
  the FIFO fills before the first poll)
- `sensor.lost`: samples lost to FIFO overflows, as measured by the sample clock
- `sensor.resync`: sample-clock restarts (each starts a new frame)
- `sensor.bus`: successful fast bus recoveries / attempted bus recoveries
- `sensor.reinit`: `successes/attempts` of ADXL reinitialization after repeated errors
- `sensor.handoff`: samples dropped because the sample handoff queue was already full
- `sensor.sq`: current handoff-queue fill / capacity
- `sensor.fifo`: FIFO entries found by the latest poll
- `sensor.read` / `sensor.samples`: samples read from the sensor / resampled
  samples produced (800 per second)
- `sensor.rate_mhz`: the sensor's own sample rate as the clock tracks it (mHz)
- `sensor.clk_err_us`: latest FIFO-depth timing estimate minus the clock
- `wifi_retry.attempts|fail`: reconnect attempts and initial connect failures
- `parse.ctrl|ack`: invalid control command / DATA_ACK packets
- `last_error`: latest error code and timestamp (ms)
