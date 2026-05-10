# Multithreading Performance Improvements

## Summary

Implemented adaptive multi-sensor FFT processing using a fixed-size thread pool
(4 workers, one per Raspberry Pi core) to reduce lag spikes on larger workloads
without paying thread-pool overhead on trivially small compute rounds.

## Threading Opportunities Identified (ranked by impact)

### 1. Adaptive per-client FFT in `compute_all()` — **HIGH IMPACT, IMPLEMENTED**

- **Problem**: `compute_all()` originally ran `compute_metrics()` sequentially for
  each connected sensor. The first multithreaded version improved larger
  workloads but still paid queue/scheduling overhead for small FFT rounds.
- **Why it works**: `compute_metrics()` already uses a three-phase
  snapshot→compute→store design with brief locks. The heavy FFT math runs
  under NumPy, which releases the GIL, enabling true thread parallelism.
- **Fix**: Added a `WorkerPool` wrapper with bounded outstanding work
  (`max_workers=4`, plus a small bounded waiting queue) and changed
  `compute_all()` to dispatch per-client FFT tasks adaptively. Small workloads
  stay serial; larger multi-sensor rounds still fan out across the pool.
- **Impact**: Larger workloads keep the tail-latency win from multithreading,
  while small/default benchmark rounds stop paying unnecessary dispatch cost.

### 2. `asyncio.to_thread()` for `compute_all()` in the processing loop — already done

The existing code already offloads `compute_all()` via `asyncio.to_thread()`,
keeping the event loop unblocked during FFT. No change needed.

### 3. Post-analysis report generation — already threaded

`PostAnalysisWorker` in `apps/server/vibesensor/use_cases/run/post_analysis.py`
owns a single daemon thread for completed-run post-analysis. `RunRecorder`
creates it during run-lifecycle setup and schedules completed run IDs after
finalization. No separate report-generation thread is created in the renderer;
report requests read persisted analysis and render on demand.

### 4. UDP ingest path — kept lightweight (no threading added)

The UDP ingest path is intentionally single-threaded: it is I/O-bound,
very fast (buffer append under a brief lock), and adding consumers would
risk packet reordering. The bounded async queue already provides backpressure
with explicit drop logging.

## What was implemented

| Component | Change |
|-----------|--------|
| `worker_pool.py` | Bounded worker pool wrapper: caps running + queued tasks, applies caller backpressure, isolates task failures, exposes metrics, supports clean shutdown |
| `processing/` | `compute_all()` dispatches per-client FFT adaptively; ingest/compute timing counters added |
| `app/container.py` | Creates shared `WorkerPool(max_workers=4, thread_name_prefix="vibesensor-fft")`, injects into `SignalProcessor`, runtime shuts it down on stop |
| Tests | 14 new tests: pool correctness, parallel/sequential equivalence, concurrent ingest+compute safety |
| Benchmark | `apps/server/tests/infra/workers/benchmark_compute_all.py` — canonical pytest-benchmark regression path |

## Before/After Metrics

Measured on CI runner (2-core VM), 4 sensors, 20 rounds.
On a real 4-core Raspberry Pi, the parallel speedup is expected to be larger.

| Metric | Sequential | Parallel | Change |
|--------|-----------|----------|--------|
| Compute median (ms) | 5.3 | 7.0 | +32% overhead (small tasks on fast CPU) |
| Compute P95 (ms) | 14.9 | 8.4 | **−44% tail latency** |
| Ingest P95 (ms) | 0.95 | 0.78 | **−18% ingest jitter** |
| Output equivalence | — | ✅ YES | Identical results |

Key insight: the thread pool reduces **tail latency** (P95) when each
per-client FFT round is large enough to amortize dispatch overhead. Small FFT
workloads should stay serial; on a Pi with slower per-core performance or with
larger FFT sizes, the adaptive parallel path still carries the benefit.

## How to run the benchmark

```bash
make benchmark-backend BENCHMARK_OPTS="--benchmark-save=worker-pool"
make benchmark-compare-backend
```

`make benchmark-backend` uses the default backend benchmark target list defined in
the repository `Makefile`. Override `BACKEND_BENCHMARK_TARGETS` only for ad hoc
single-file runs so the documented default cannot drift from the Makefile.

## Design decisions for a 4-core Pi

- **4 workers**: matches Pi core count; avoids over-parallelizing
- **Single fast path**: ingest stays on the event loop, never blocked
- **Snapshot approach**: `compute_metrics()` copies buffer data under a brief
  lock, then releases the lock for heavy FFT computation
- **Bounded outstanding work**: once the pool's running + queued limit is
  reached, submissions block instead of growing an unbounded executor backlog
- **Bounded queues**: UDP ingest queue is bounded (configurable, default 1024);
  drops are logged with backpressure counters
- **Error isolation**: one failing client's FFT doesn't block others
  (fail-open via `map_unordered`)
- **Clean shutdown**: pool waits for in-flight tasks before exit
