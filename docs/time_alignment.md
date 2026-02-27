# Multi-Sensor Time Alignment

## Problem

When the system compares data from multiple sensors (spectrum overlay,
strongest-location ranking, live-diagnostics combined groups), each
sensor's analysis window must cover the **same real-world time interval**.
Without alignment, a sensor that received data 5 seconds ago could be
compared against one that received data now, producing misleading
differences that are really just timing artefacts.

## Root Cause (Confirmed)

Prior to this change, each sensor's analysis window was selected
independently as the "last N samples" from its circular buffer.  No
mechanism ensured that these windows overlapped in wall-clock time.
The timing metadata available per frame (`t0_us`) was tracked in the
registry for jitter/drift monitoring but **never propagated** to the
processing buffer or alignment logic.

## Solution

### 1. Sensor Clock Synchronisation (`CMD_SYNC_CLOCK`)

The server periodically broadcasts a `CMD_SYNC_CLOCK` command (every
≈5 seconds) to every connected sensor.  The command carries the
server's monotonic time in microseconds.

| Layer | Change |
|-------|--------|
| Protocol | New `CMD_SYNC_CLOCK = 2` command type with 8-byte `server_time_us` payload. |
| Firmware (ESP) | On receipt, compute `offset = server_time_us − esp_timer_get_time()` and store.  Apply offset to every subsequent `t0_us` in DATA frames. |
| Server control plane | `UDPControlPlane.broadcast_sync_clock()` iterates active sensors and sends the command. |
| Processing loop | Calls `broadcast_sync_clock()` every ≈5 seconds. |

After synchronisation all sensors report `t0_us` relative to the
server's monotonic clock, making timestamps directly comparable across
sensors.

### 2. Per-Buffer Timing Metadata

`ClientBuffer` now stores:

| Field | Purpose |
|-------|---------|
| `first_ingest_mono_s` | When the buffer first received data (reset on flush). |
| `last_t0_us` | Sensor-clock timestamp (µs) of the most recently ingested frame. After `CMD_SYNC_CLOCK` this is server-relative. |
| `samples_since_t0` | Samples ingested since `last_t0_us` was recorded. |

`ingest()` accepts an optional `t0_us` parameter; the UDP data
receiver passes `msg.t0_us` through.

### 3. Analysis Time-Range Computation

`_analysis_time_range(buf)` returns `(start_s, end_s, synced)`:

- **Synced path** (preferred): When `last_t0_us > 0`, the window end is
  computed from the sensor timestamp plus the frame duration.  The
  start is `end − window_duration`.
- **Fallback path**: Uses `last_ingest_mono_s` (server arrival time)
  and the buffer sample count to estimate the window.

### 4. Alignment Computation

`time_alignment_info(client_ids)` computes:

| Field | Description |
|-------|-------------|
| `per_sensor` | Per-client `{start_s, end_s, duration_s, synced}`. |
| `shared_window` | Intersection of all sensor windows, or `None`. |
| `overlap_ratio` | Fraction of the union covered by the intersection (0–1). |
| `aligned` | `True` when `overlap_ratio ≥ 0.5`. |
| `clock_synced` | `True` when all included sensors use synced timestamps. |
| `sensors_included` / `sensors_excluded` | Partition of inputs. |

### 5. Multi-Spectrum Payload

`multi_spectrum_payload()` now includes an `alignment` block when two
or more sensors are present:

```json
{
  "alignment": {
    "overlap_ratio": 0.95,
    "aligned": true,
    "shared_window_s": 1.9,
    "sensor_count": 3,
    "clock_synced": true
  }
}
```

### 6. Live Diagnostics

The existing `_multi_sync_window_ms = 800 ms` recency check in
`_process_combined_groups()` already enforces a tight temporal
alignment for real-time multi-sensor events.  No change was needed
here.

## Fallback Behaviour

| Scenario | Behaviour |
|----------|-----------|
| Sensor has no `t0_us` (pre-sync or simulator) | Falls back to server arrival time for alignment. |
| One sensor missing data | Excluded from alignment; remaining sensors compared normally. |
| Overlap ratio < 50 % | `aligned = False`; consumers can choose to skip the comparison. |
| Single sensor | Trivially aligned (`overlap_ratio = 1.0`). |

## How to Run the Tests

```bash
# Focused alignment tests (29 tests, <1 s):
python -m pytest apps/server/tests/test_time_alignment.py -v

# Full backend suite:
python3 tools/tests/pytest_progress.py --show-test-names -- -m "not selenium" apps/server/tests
```
