# Intake Buffering & Analysis Separation

## Architecture

Sensor data flows through three decoupled stages:

```
UDP datagram → async queue → ring buffer → (analysis runs in background thread)
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

### 3. Analysis (`processing_loop` in `app.py`)

`compute_all()` runs FFT and metrics computation for all active clients. It
is dispatched to a **worker thread** via `asyncio.to_thread()` so it never
blocks the event loop. `compute_metrics()` uses snapshot-based locking:

- **Phase 1 (lock):** copy the ring buffer data (~20–100 μs).
- **Phase 2 (no lock):** heavy FFT / peak-finding / strength-db
  computation.
- **Phase 3 (lock):** store computed metrics back into the buffer struct
  (~10 μs).

Because the lock is held only during the brief snapshot and store phases,
`ingest()` (which also needs the lock) is never blocked for more than a
fraction of a millisecond, even while analysis is running.

## Overflow / backpressure policy

| Layer | Buffer | Max size | Overflow behaviour |
|-------|--------|----------|--------------------|
| UDP queue | `asyncio.Queue` | `data_queue_maxsize` (default 1024 packets) | Oldest arriving packet is dropped; warning logged (rate-limited to 1/10 s); `note_server_queue_drop` counter incremented on client record. |
| Ring buffer | numpy array per client | `sample_rate_hz × waveform_seconds` (default 6400 samples) | Circular overwrite — oldest samples are silently replaced. |
| Analysis scheduling | One pending `compute_all` at a time | 1 | If the previous cycle is still running, the event loop yields to `asyncio.to_thread()` and waits; at most one "next" cycle is pending. |

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
- **Analysis cadence:** `total_compute_calls` should grow at
  `fft_update_hz` (default 4/s).
- **Analysis headroom:** `last_compute_duration_s` should be well below
  `1 / fft_update_hz` (250 ms at default settings).

Queue drops are logged as WARNING and counted in the client registry
(`server_queue_drops` field).
