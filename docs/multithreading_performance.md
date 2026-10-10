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
- Post-analysis stays on that one thread. Its cost is many small steps per
  window (the raw replay's strength pipeline, order matching, line reads), so
  it is cut by taking windows together as arrays (the replay's strengths 16
  windows at a time, an order's line reads all at once), each result bit for
  bit the one-at-a-time result. A thread pool over the replay's batches made
  post-analysis slower, not faster (GIL contention: the build step went from
  1.9 s to 3.7 s on x86 with 1 or 3 workers; no gain on the Pi), and each
  window's FFT (3 × 2048 points) is too small for FFT workers. Worker
  processes would each hold a copy of the run's samples and spectra, which the
  Pi 3 A+ (424 MB) cannot spare while the live server runs.
- Order matching tests each hypothesis (about ten) against every window. What
  every hypothesis reads of a window the same way (its sensor, speed bin,
  driving phase, floor and cell) is worked out once per drive
  (`sample_facts`); each hypothesis then finds every window's nearest ranked
  peak in one array operation (`PeakTable`), plans its line reads as arrays
  and files them by cell (`_line_reads`), and judges each sensor's reads once
  (`TrackedCells` keeps its judges until a new read comes in). Measured on a
  30-minute, 4-sensor drive on the Pi: the analyze step went from 60 s to
  45 s, the whole post-analysis from 112 s to 99 s, peak RSS +3 MB; the
  analysis JSON is byte-identical on that drive, the CI-seed accuracy
  benchmark and the diagnostic matrix.
- Tried and not kept for order matching: a pool of 3 forked processes, one
  hypothesis each, saved 21 s on the Pi but each child dirtied 30-45 MB of
  the parent's pages through reference counts (86-135 MB in all), leaving 54-100
  MB available while the live server runs, and forking a threaded server is
  fragile; a thread pool gains nothing, as the matching is Python bound under
  the GIL. More than one FFT thread in the replay gains nothing on the Pi.
  Algorithmic cuts to the replay's FFT (decimation, a zoom FFT or Goertzel at
  the order lines) are capped by the FFT's small share once it is batched
  (about 3-4 s of the Pi's total), well under the 15 % a change to the
  analysis must earn.
- The UDP ingest path is single-threaded: it is I/O-bound, very fast (buffer
  append under a brief lock), and the bounded async queue provides backpressure
  with explicit drop logging.

### Post-analysis cost (30-minute drive, 4 sensors, `FFT_N=2048`)

| Host | CPU time | Peak RSS |
|------|----------|----------|
| x86 dev host | ~7.5 s | ~227 MB |
| Raspberry Pi 3 A+ (`nice -n 10`) | ~99 s | ~152 MB |

## Benchmarks

```bash
make benchmark-backend BENCHMARK_OPTS="--benchmark-save=baseline"
make benchmark-compare-backend
```

`make benchmark-backend` uses the default backend benchmark target list defined in
the repository `Makefile`. Override `BACKEND_BENCHMARK_TARGETS` only for ad hoc
single-file runs so the documented default cannot drift from the Makefile.
