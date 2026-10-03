# Threading Model and Performance

## Summary

Live FFT/metrics computation runs serially, off the asyncio event loop, in one
worker thread per processing tick. There is no thread pool for live compute:
it is dominated by many small NumPy calls that hold the GIL, so thread pools
added contention instead of speedup.

## Live processing tick

- The async processing loop (`apps/server/vibesensor/live/processing_loop.py`)
  filters to active clients with fresh data and calls
  `SignalProcessor.compute_all()` via `anyio.to_thread.run_sync()`, so the event
  loop never performs FFT work directly.
- `compute_all()` computes each client in turn. One client's failure is logged
  and skipped; the remaining clients still compute.
- `compute_metrics()` uses snapshot-based locking: copy the ring buffer under the
  client lock, compute without the lock, then commit results under the lock if the
  buffer generation still matches. `ingest()` is therefore blocked only briefly.

### Measured cost (8 sensors, 800 Hz, `FFT_N=2048`, 8 s window)

Measured on a 32-thread x86 dev host with fresh data every tick (no cache hits):

| Mode | `compute_all()` median | p95 |
|------|------------------------|-----|
| Serial | ~9 ms | ~12–15 ms |
| Former 4-thread `WorkerPool` | ~53–56 ms | ~61–63 ms |

The default tick interval is 250 ms (`FFT_UPDATE_HZ=4`), and the low-load fast
path caps the loop's duty cycle at 50%. Even at a 5–10× slower Raspberry Pi
4/5 core, serial compute (~45–90 ms) stays well inside the tick budget.

## Post-analysis and UDP ingest

- `PostAnalysisWorker` in `apps/server/vibesensor/analysis/post_analysis.py`
  owns a single daemon thread for completed-run post-analysis. Report requests
  read persisted analysis and render on demand.
- The UDP ingest path is single-threaded: it is I/O-bound, very fast (buffer
  append under a brief lock), and the bounded async queue provides backpressure
  with explicit drop logging.

## Benchmarks

```bash
make benchmark-backend BENCHMARK_OPTS="--benchmark-save=baseline"
make benchmark-compare-backend
```

`make benchmark-backend` uses the default backend benchmark target list defined in
the repository `Makefile`. Override `BACKEND_BENCHMARK_TARGETS` only for ad hoc
single-file runs so the documented default cannot drift from the Makefile.
