# Intake Buffering & Live Compute Separation

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

Inside `SignalProcessor.compute_all()`, per-client FFT work is dispatched through
the shared `WorkerPool` when multiple clients are active. `compute_metrics()` uses
snapshot-based locking:

- **Phase 1 (lock):** copy the ring buffer data (~20–100 μs).
- **Phase 2 (no lock):** heavy FFT / peak-finding / strength-db
  computation.
- **Phase 3 (lock):** store computed metrics back into the buffer struct
  (~10 μs).

Because the lock is held only during the brief snapshot and store phases,
`ingest()` (which also needs the lock) is blocked only briefly even while
background compute work is running.

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
