# ESP Firmware hardening notes

## What was fixed

- Added compile-time guardrails for runtime tuning:
  - sample rate is clamped to `25..3200 Hz`
  - frame size is clamped so DATA packets always fit UDP MTU (`<= 1500` bytes)
- Hardened ADXL345 reads:
  - I2C register and burst reads now return explicit success/failure
  - FIFO truncation and I2C errors are detected and counted
  - repeated sensor read errors trigger bounded sensor re-init attempts
- Hardened Wi-Fi reconnect behavior:
  - reconnect now uses exponential backoff with jitter and an upper cap (`60s`)
  - retry failure counter uses saturating increment (prevents wrap-around)
- Added reliability counters and status snapshots:
  - periodic `Serial` status line every 10s with queue, tx, sensor, wifi, parse and last-error fields
  - transmit packing/send failures and parser failures are now counted
- Added command guardrail:
  - identify blink duration is capped to `10s` to prevent long/accidental lockouts
- Fixed sampling missed-sample double-count:
  - when `sample_once()` returns false (sensor unavailable), the code now advances
    `g_next_sample_due_us` before breaking so the post-loop lag detector does not
    re-count the same slot as an additional missed sample
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

## Build and test

```bash
cd firmware/esp
pio run -e m5stack_atom
pio test -e native
```

## Runtime counters/status to monitor

Status snapshots are printed as:

`status wifi=... q=current/cap drop=... tx_fail={...} sensor={...} wifi_retry={...} parse={...} last_error=code@ms`

Key fields:

- `drop`: queue overflow drops
- `tx_fail.pack|begin|end`: packet encoding / UDP begin / UDP send failures
- `sensor.err`: sensor I2C read failures
- `sensor.trunc`: FIFO truncation events (reader could not consume full FIFO depth in one pass)
- `sensor.reinit`: `successes/attempts` of ADXL reinitialization after repeated errors
- `sensor.miss`: missed/skipped sampling slots
- `wifi_retry.attempts|fail`: reconnect attempts and initial connect failures
- `parse.ctrl|ack`: invalid control command / DATA_ACK packets
- `last_error`: latest error code and timestamp (ms)
