# Intake Buffering & Live Signal Processing

## Architecture

Sensor data flows through three decoupled stages:

```
UDP datagram → async queue → per-client ring buffer → processing loop → worker threads
```

### 1. Packet reception (`udp_data_rx.py`)

`DataDatagramProtocol.datagram_received()` fires on every UDP packet and
immediately enqueues it via `put_nowait()` (non-blocking). If the queue is
full, the packet is dropped and logged.

### 2. Queue consumer

`process_queue()` is an asyncio task that pulls items from the queue, parses
them, updates the client registry, writes samples into the ring buffer
(`SignalProcessor.ingest()`), and sends a UDP ACK. This runs on the main
event loop but each call is lightweight (microseconds per packet).

### 3. Live compute (`runtime/processing_loop.py` + `processing/processor.py`)

The async processing loop in `runtime/processing_loop.py` runs on a timer,
filters to active clients with fresh data, and calls `SignalProcessor.compute_all()`
via `asyncio.to_thread()` so the event loop never performs FFT work directly.

`SignalProcessor` is now a facade over three explicit subsystems:

- `processing/buffer_store.py`: coordinator over ingest, snapshot capture, stats, and shared buffer queries
- `processing/buffer_registry.py`: per-client buffers, epochs, eviction, and lock ordering
- `processing/buffer_mutations.py` + `processing/ingest_preparation.py`: buffer mutation policy plus chunk normalization/overflow trimming
- `processing/compute.py`: FFT cache ownership plus metric computation from snapshots
- `processing/processor.py`: facade class with payload shaping, debug output, and time-alignment views

Inside `SignalProcessor.compute_all()`, per-client FFT work is dispatched through
the shared `WorkerPool` when multiple clients are active. `compute_metrics()` now
reads top-to-bottom as “snapshot → compute → commit”, and still uses snapshot-based
locking:

- **Phase 1 (lock):** copy the ring buffer data (~20–100 μs).
- **Phase 2 (no lock):** heavy FFT / peak-finding / strength-db
  computation.
- **Phase 3 (lock):** store computed metrics back into the buffer struct
  (~10 μs).

Because the lock is held only during the brief snapshot and store phases,
`ingest()` (which also needs the lock) is blocked only briefly even while
background compute work is running.

## Signal-processing flow after ingest

`SignalProcessor.compute_metrics()` keeps the live path in a strict
snapshot -> compute -> store shape:

1. `buffer_store.snapshot_for_compute()` captures immutable arrays from the
   per-client ring buffer under a short lock and skips work when there is no
   fresh data or not enough samples for FFT.
2. `SignalMetricsComputer.compute()` runs the heavy CPU work without holding the
   buffer lock.
3. `buffer_store.store_metrics_result()` commits the new metrics/spectrum back
   onto the client buffer and invalidates cached payload views.

The snapshot contains two overlapping views from the same immutable capture:

- `time_window` keeps the wider waveform slice used for RMS/P2P metrics.
- `fft_block` keeps the most recent `fft_n` samples used for spectral analysis.

The FFT block is a suffix of the time window. VibeSensor does not run a dense
overlap-add FFT bank; each compute tick snapshots the current rolling tail once,
then analyzes that one block.

### FFT pipeline

`apps/server/vibesensor/infra/processing/compute.py` owns the cached FFT setup:

- `SignalMetricsComputer` precomputes a Hann window with
  `scipy.signal.windows.hann(config.fft_n)`.
- `fft_scale = 2.0 / max(1.0, sum(window))` keeps amplitudes normalized after
  windowing.
- `fft_params(sample_rate_hz)` caches the frequency slice and valid FFT indices
  per sample rate so repeated ticks do not rebuild them.

`apps/server/vibesensor/infra/processing/compute.py` coordinates the pure DSP
steps with shared FFT/strength helpers:

1. `medfilt3()` applies a 3-point median filter per axis before FFT work. This
   removes isolated transport/I2C spikes without blurring normal vibration
   content.
2. `SignalMetricsComputer.compute()` detrends the captured windows by removing
   the per-axis mean before RMS/P2P and FFT computation.
3. `compute_fft_spectrum()` applies the SciPy-backed Hann window, runs the
   planned pyFFTW RFFT backend, slices the configured frequency range via
   SciPy FFT frequency bins, and produces both per-axis spectra and a combined
   amplitude curve.
4. `compute_vibration_strength_db()` uses SciPy peak finding to select dominant
   candidate bins, estimates a P20/median noise floor, and converts the
   dominant peak band into the
   shared dB metric used by both live telemetry and post-stop analysis:

   ```text
   strength_db = 20 * log10((peak_rms + eps) / (floor + eps))
   eps = max(1e-9, floor * 0.05)
   ```

### Key invariants

- Each client buffer has its own lock, so ingestion and FFT work scale across
  clients without a global bottleneck.
- Generation counters decide freshness. If the ingest generation has not moved,
  the compute side can reuse the cached metrics/spectrum instead of rebuilding
  them.
- The combined vibration-strength formula lives in `vibration_strength.py`; the
  live path does not carry a second dB implementation.
- Payload serialization stays downstream of computation. The processing layer
  stores structured metrics and spectrum arrays first, and only later surfaces
  them to HTTP/WebSocket payload builders.

## Overflow / backpressure policy

| Layer | Buffer | Max size | Overflow behaviour |
|-------|--------|----------|--------------------|
| UDP queue | `asyncio.Queue` | `data_queue_maxsize` (default 1024 packets) | Oldest arriving packet is dropped; warning logged (rate-limited to 1/10 s); `note_server_queue_drop` counter incremented on client record. |
| Ring buffer | numpy array per client | `sample_rate_hz × waveform_seconds` (default 6400 samples) | Circular overwrite — oldest samples are silently replaced. |
| Worker pool | `WorkerPool` outstanding task cap | `max_workers + max_queue_size` | Submission blocks once the pool is saturated; no unbounded executor backlog is allowed. |
| Processing loop | One async tick loop | 1 | The runtime loop computes on the current set of fresh clients, then sleeps until the next tick. |

## Observability

The `/api/health` endpoint returns an `intake_stats` object:

```json
{
  "total_ingested_samples": 128000,
  "total_compute_calls": 42,
  "last_compute_duration_s": 0.0034
}
```

Use these to monitor:

- **Intake throughput:** `total_ingested_samples` should grow at
  `sample_rate_hz × num_sensors`.
- **Processing cadence:** `total_compute_calls` should grow at
  `fft_update_hz` (default 4/s).
- **Processing headroom:** `last_compute_duration_s` should be well below
  `1 / fft_update_hz` (250 ms at default settings).

Queue drops are logged as WARNING and counted in the client registry
(`server_queue_drops` field).
