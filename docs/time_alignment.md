# Multi-Sensor Time Alignment

## Problem

When the system compares data from multiple sensors (spectrum overlay,
strongest-location ranking), each
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
| `last_ingest_mono_s` | Server monotonic time of the most recent ingest. |
| `last_t0_us` | Sensor-clock timestamp (µs) of the most recently ingested frame. After `CMD_SYNC_CLOCK` this is server-relative. |
| `samples_since_t0` | Samples ingested since `last_t0_us` was recorded. |

`ingest()` accepts an optional `t0_us` parameter; the UDP data
receiver passes `msg.t0_us` through.

### 3. Analysis Time-Range Computation

`ClientBuffer.analysis_time_range()` returns an `AnalysisTimeRange`
(`start_s`, `end_s`, `synced`). Each metrics snapshot records it, so
`SignalProcessor.latest_analysis_time_range()` reports the window the latest
metrics cover (used to place recorded samples on the timeline):

- **Synced path** (preferred): When `last_t0_us > 0`, the window end is
  computed from the sensor timestamp plus the frame duration.  The
  start is `end − window_duration`.
- **Fallback path**: Uses `last_ingest_mono_s` (server arrival time)
  and the buffer sample count to estimate the window.

### 4. Multi-Spectrum Payload

`multi_spectrum_payload()` includes an `alignment` block when two or more
sensors with a computed spectrum are present. `overlap_ratio` is the fraction
of the union covered by the intersection of all sensor windows, `aligned` is
`True` when `overlap_ratio ≥ 0.5`, and `clock_synced` is `True` when every
sensor uses synced timestamps:

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

### 5. Persisted Raw Replay

Post-stop raw replay now uses the persisted raw chunk timeline instead
of assuming that summary-sample `t_s` starts at raw sample index zero.
Raw-capture manifests store the run anchor plus **per-sensor clock-sync
proof** captured at finalize time:

- whether the sensor `t0_us` was proven to be in the server monotonic
  clock domain,
- the last successful sync-ack monotonic timestamp,
- the applied offset and measured RTT,
- the proof status (`verified`, `stale_sync`, `high_rtt`,
  `missing_sync`, or `missing_registry_record`).

Replay only treats `t0_us` as server-monotonic when that proof is
explicitly `verified`. Older artifacts without the per-sensor proof, or
newer artifacts whose proof is stale/missing/high-RTT, fall back to the
persisted summary sample instead of guessing raw alignment. Gaps,
overlaps, dropped chunks, and other incomplete raw coverage still fall
back per window and emit deterministic warnings.

### 6. Simulator Parity

`vibesensor-sim` follows the same contract as the firmware: it streams
only after `HELLO_ACK`, answers `CMD_SYNC_CLOCK` with the sync-clock ACK
(device receive/send timestamps), applies the server offset once a sync
carries a measured RTT, and stamps `t0_us` from a per-sensor sample clock
(device timer with a few tens of ppm drift) rather than from send time.
Simulator recordings are therefore raw-backed like real sensors. As with
real hardware, the offset is applied from the second sync exchange (about
10 s after a sensor connects); a recording started earlier contains one
clock step per sensor.

## Fallback Behaviour

| Scenario | Behaviour |
|----------|-----------|
| Sensor has no `t0_us` yet (pre-sync) | Falls back to server arrival time for alignment. |
| One sensor missing data | Excluded from alignment; remaining sensors compared normally. |
| Overlap ratio < 50 % | `aligned = False`; consumers can choose to skip the comparison. |
| Single sensor | Trivially aligned (`overlap_ratio = 1.0`). |

## How to Run the Tests

```bash
# Focused alignment tests:
python -m pytest apps/server/tests/infra/processing/test_time_alignment.py -v

# Full backend suite:
pytest -q apps/server/tests
```
