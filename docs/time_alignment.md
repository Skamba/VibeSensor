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
2 seconds) to every connected sensor.  The command carries the
server's monotonic time in microseconds.

| Layer | Change |
|-------|--------|
| Protocol | New `CMD_SYNC_CLOCK = 2` command type with 8-byte `server_time_us` payload. |
| Firmware (ESP) | On receipt, compute `offset = server_time_us − esp_timer_get_time()` and store.  Apply offset to every subsequent `t0_us` in DATA frames. |
| Server control plane | `UDPControlPlane.broadcast_sync_clock()` iterates active sensors and sends the command. |
| Processing loop | Calls `broadcast_sync_clock()` every `CLOCK_SYNC_INTERVAL_S` (2 s) of monotonic time, independent of the tick rate. |

After synchronisation all sensors report `t0_us` relative to the
server's monotonic clock, making timestamps directly comparable across
sensors.

The 2 s interval is deliberate. Sensors apply the offset from their second
exchange, so a newly connected sensor is synced after 2–4 s. It also leaves
room under the two age limits that depend on it: the registry's 8 s
slow-exchange hold (about three slow exchanges in a row are skipped before an
old estimate is replaced) and the 15 s sync-age limit of the raw-capture proof
(several lost exchanges in a row still leave a sensor `verified` at finalize).
Only the server schedules exchanges; firmware and simulator just answer them,
so the interval changes without re-flashing sensors. The loop used to count
ticks for a nominal ≈5 s, which the 10 Hz low-load fast path (up to 8 sensors)
turned into ≈2 s; the schedule is now timed, so sensor count and CPU load no
longer change it.

### 2. Per-Buffer Timing Metadata

`ClientBuffer` now stores:

| Field | Purpose |
|-------|---------|
| `last_ingest_mono_s` | Server monotonic time of the most recent ingest. |
| `last_t0_us` | Sensor-clock timestamp (µs) of the most recently ingested frame. After `CMD_SYNC_CLOCK` this is server-relative. |
| `samples_since_t0` | Samples ingested since `last_t0_us` was recorded. |

`ingest()` accepts an optional `t0_us` parameter; the UDP data
receiver passes `msg.t0_us` through once the sensor is clock-synced. Before
that, `t0_us` is the sensor's own uptime, so the buffer keeps using server
arrival time.

### 3. Analysis Time-Range Computation

`ClientBuffer.analysis_time_range()` returns an `AnalysisTimeRange`
(`start_s`, `end_s`, `synced`) for the newest FFT block (`fft_n` samples,
2.56 s at 800 Hz): the spectrum, its peaks and the vibration strength describe
only that block, not the longer waveform buffer. Each metrics snapshot records
it, so `SignalProcessor.latest_analysis_time_range()` reports the window the
latest metrics cover. The recorder uses it to place each sample row on the
timeline, to take the row's speed at the window's midpoint, and to skip rows
whose synced window still starts before the recording did (that vibration was
measured before the user pressed start, and the raw capture cannot replay it):

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

Raw capture only stores chunks stamped on the server clock. The registry
marks a sensor clock-synced once the sensor acknowledges a sync command
that carried an offset to apply (the second exchange), and a chunk is
captured only when its `t0_us` also reads as server-clock time rather than
bare device time (this catches queued pre-sync frames that arrive after the
acknowledgement). Chunks a sensor sends before that are dropped — the live
view still uses them — so each sensor's raw capture starts at its first
synced chunk and summary rows from before it are simply not raw-backed. On a
clean network every recorded row of a sensor that synced before the start is
raw-backed, so the report's data-quality checks all pass. A
sensor reboot forgets its sync until it re-syncs.

Sensors apply every offset the server sends, so a wrong estimate steps their
`t0_us`. An exchange delayed on either side (a scheduling stall, a Wi-Fi retry)
has an inflated round trip and an offset error of up to half of it, so the
registry keeps its current offset when an exchange's round trip exceeds twice
(and by more than 1 ms) the round trip behind that offset, unless that offset
is older than 8 s.

The manifest's sample-rate proof compares consecutive chunks in `t0_us` order.
A dropped chunk or a remaining clock step breaks one of those steps; replay
records it as a gap or overlap and skips only the windows that cross it. A
sensor is `timing_inconsistent` (and replays entirely from summary rows) only
when more than 10% of its chunk steps disagree with the median rate.

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
real hardware, the offset is applied from the second sync exchange (2–4 s
after a sensor connects); a recording started earlier drops each
sensor's pre-sync chunks and replays from its first synced chunk.

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
python -m pytest apps/server/tests/live/test_time_alignment.py -v

# Full backend suite:
pytest -q apps/server/tests
```
