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
| Server control plane | `UDPControlPlane.broadcast_sync_clock()` sends the command to every active sensor; `send_sync_clock()` sends it to one. A HELLO from a sensor that is not on the server clock, or that was silent for over 1 s, starts an exchange at once, and the ACK of its first (measuring) exchange triggers the exchange that carries the offset. |
| Processing loop | Calls `broadcast_sync_clock()` every `CLOCK_SYNC_INTERVAL_S` (2 s) of monotonic time, independent of the tick rate. |

After synchronisation all sensors report `t0_us` relative to the
server's monotonic clock, making timestamps directly comparable across
sensors.

Sensors apply the offset from their second exchange. Both exchanges run as soon
as a sensor says HELLO, so a newly connected sensor stamps on the server clock
within two round trips, before its first frame; waiting for two broadcasts used
to leave it unsynced for 2–4 s, which raw capture drops (a recording started
right after the sensors, or a sensor that reconnected mid-run, lost that much
raw-backed analysis plus one FFT window). A rebooted sensor is re-synced at its
next HELLO or broadcast (≤ 2 s); a HELLO from a sensor that was silent for over
1 s, longer than a streaming sensor ever is, starts an exchange at once. Until
the server notices the reboot, that exchange still carries the previous boot's
offset; the sensor applies it and stamps frames seconds in the past, which after
a session shorter than 2 s do not rewind far enough to reveal the reboot. The
acknowledgement measures an offset more than 2 s larger, which only a reboot
explains, so the registry starts a new session and sends the fresh offset at
once, before the sensor's first frame. The 2 s broadcast interval leaves room under the two age limits that depend on it: the registry's 8 s
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
  `timing_unreliable`, `missing_sync`, or `missing_registry_record`).
  `timing_unreliable` means the sensor was synced but the server-side
  timing guard (see "Sensor timing guard" below) flagged its stamps as
  falling behind real time or its delivered rate as off from the declared one.

Raw capture only stores chunks stamped on the server clock. The registry
marks a sensor clock-synced once the sensor acknowledges a sync command
that carried an offset to apply (the second exchange). The firmware stamps a
frame when it queues it and sends the queue stop-and-wait, retransmitting the
head for up to 0.75 s, so frames queued just before the offset was applied can
still arrive after the acknowledgement, on bare device time. The registry
spots them because they continue the sensor's device timeline (its last
pre-sync frame's `t0_us` plus one frame duration per sequence step, for up to
8 frames), whereas frames stamped after the offset was applied are the offset
away from it. Judging by arrival time instead fails at car start, when the Pi
and the sensors boot together and a device timer reads within a second or two
of server time: a synced frame held back by a retransmission then looks like
device time and was dropped. Chunks a sensor sends before the sync are dropped — the live
view still uses them — so each sensor's raw capture starts at its first
synced chunk and summary rows from before it are simply not raw-backed. On a
clean network every recorded row of a sensor that synced before the start is
raw-backed, so the report's data-quality checks all pass. A
sensor reboot forgets its sync until it re-syncs.

Sensors apply every offset the server sends, so a changed estimate steps their
`t0_us`. An exchange delayed on either side (a scheduling stall, a Wi-Fi retry)
has an inflated round trip and an offset error of up to half of it, so the
registry keeps its current offset when an exchange's round trip exceeds twice
(and by more than 1 ms) the round trip behind that offset, unless that offset
is older than 8 s. Accepted exchanges still differ by up to half their round
trip in either direction, and a step beyond 0.75 sample breaks the raw timeline
(see below); with a re-sync every 2 s and 2.56 s FFT windows, every window
crosses one. So once a sensor stamps with an offset, each new estimate moves it
by at most 200 µs (`_SYNC_MAX_SLEW_US`, under the timeline tolerance even at
3200 Hz, and enough for 100 ppm of crystal drift). Only an offset that an
exchange proves wrong by more than 5 ms beyond that exchange's half round trip
(a first estimate from a stalled exchange) is replaced outright. Before this,
the noise of each estimate went straight into the stamps: under CPU load
re-syncs stepped them by milliseconds and short runs replayed no raw window at
all (`raw_capture_mode: summary_only`). On the Pi, with a ~9 ms Wi-Fi round
trip, re-syncs stepped them by 0.6–4.2 ms, so every run with zero loss still
reported replay gaps and overlaps and the frame-integrity warning.

The manifest's sample-rate proof takes the median rate of consecutive chunks in
`t0_us` order. A dropped chunk or a remaining clock step breaks one of those
steps; replay records it as a gap or overlap (beyond 0.75 sample) and skips
only the windows that cross it, however many there are. Windows between breaks
hold the same samples the live spectra used, so there is nothing to gain from
dropping a whole sensor with many breaks: a lossy or congested sensor keeps its
intact windows raw-backed.

Replay only treats `t0_us` as server-monotonic when that proof is
explicitly `verified`. Older artifacts without the per-sensor proof, or
newer artifacts whose proof is stale/missing/high-RTT/timing-unreliable, fall back to the
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
real hardware, the offset is applied from the second sync exchange, which
follows the first as soon as its ACK arrives (both start at the sensor's
HELLO); a recording that catches a sensor before that drops its pre-sync
chunks and replays from its first synced chunk.

### 7. Sensor Timing Guard

A sync offset only maps the sensor's clock onto the server clock; it does not
prove the sensor stamps its samples correctly. Firmware that stamped `t0_us`
from a nominal 800 Hz schedule while its ADXL345 delivered ~740 samples/s
fell ~55 ms per second behind real time; summary rows were then skipped (their
analysis window started before the run) and a 15 s recording ended with no
samples. The registry therefore checks every synced sensor in 20 s windows of
receive time (`vibesensor/ingest/sensor_timing.py`):

- **arrival lag**: receive time minus the time of the frame's last sample, as
  the window minimum (strips Wi-Fi and retransmit delays). Above 1 s (frames
  are held back at most 0.75 s), or more than 0.25 s ahead, the state is
  `timestamp_lag`.
- **effective rate**: samples delivered per second of receive time, frames
  lost in transit counted from sequence gaps. More than 2 % off the declared
  rate is `rate_mismatch`.

A flagged sensor shows up as the health degradation reason
`sensor_timestamp_lag` / `sensor_rate_mismatch` (with per-client
`timing_state`, `timing_min_lag_ms` and `effective_sample_rate_hz` under
`ingest.clients`), fails the `sensors_ready` capture-readiness check with
`sensor_timing_unreliable`, and gets the raw-capture clock proof
`timing_unreliable`. A run that still ends without samples is recorded in
History with the error "No samples collected during run".

The firmware side (`firmware/esp/lib/sample_timing/sample_timing.h`) stamps
each sample from the sensor's measured period, locked to the ESP clock, and
resamples onto an exact grid of the declared rate, so `t0_us` is the real time
of the frame's first sample and the declared rate is the delivered one.

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
