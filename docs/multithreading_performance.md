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
- Post-analysis stays on that one thread, with two helper threads for the
  raw replay's FFTs. Its cost is many small steps per window (the raw replay's
  strength pipeline, order matching, line reads), so it is cut by taking
  windows together as arrays (an order's line reads all at once, the replay's
  windows as below), each result bit for bit the one-at-a-time result.
  Worker processes would each hold a copy of the run's samples and spectra,
  which the Pi 3 A+ (512 MB board, ~473 MB visible to Linux with the
  image's headless boot config) cannot spare while the live server runs.
- The raw replay locates each sensor's windows in its raw buffer all at once
  (`contiguous_raw_window_starts`), gathers 64 at a time in one strided step,
  and computes their spectra through one FFT plan (`combined_spectra`; a
  short chunk is zero-padded so there is only the one plan) on helper
  threads (two since the change below, each with its own plan), while the worker thread takes the strengths of the spectra
  already computed 128 at a time as columns (`StrengthRows`, below). It keeps the spectra as rows of one array per
  sample rate (`WindowSpectrum.rows`), which order matching's line reads
  gather from. Measured on a 30-minute, 4-sensor drive on the Pi: the replay
  (build step) went from 35 s to 12.5 s, the analyze step from 35.5 s to
  29.7 s (the line reads on rows), the whole post-analysis from 77 s to 48.5
  s; peak RSS +13 MB (147 to 160 MB: the helper thread and one chunk's FFT
  working set), MemAvailable at least 166 MB throughout. The analysis JSON
  is byte-identical on that drive, the CI-seed accuracy benchmark and the
  diagnostic matrix. The live tick's FFT and strength cost is unchanged
  (4.1 ms on the Pi).
- The replay's strengths come out as columns (`StrengthRows`: each row's
  noise floor, and its peaks as flat row/frequency/amplitude/dB/local-floor
  columns with per-row offsets), written straight into the samples' strength
  fields and the peak columns, with no metrics dict or peak object per window.
  The order statistics (P20 threshold, floor medians) are taken on the
  float32 rows and only their arithmetic in float64, which is exact because
  every float32 widens exactly; a whole batch's peak candidates are ranked by
  one `lexsort`, and the band sums use one in-place prefix sum. The live
  single-spectrum strength is the same function on one row. Measured on PC
  (a 4-sensor simulated drive with raw capture, 9 interleaved rounds pinned
  to the same cores): the strength work per build went from ~430 ms to
  ~250 ms, the build step from 561 ms to 499 ms, peak RSS from 179 MB to
  172 MB and the memray peak from 127 MB to 120 MB; the drive without raw
  capture is unchanged. The analysis JSON is byte-identical. The worker
  thread now waits on the FFT thread (about 50 ms per build on PC, against
  7 ms before), so on PC the FFT thread is the longer of the two.
- With the strengths as columns, the replay waits on its FFT thread on the Pi
  too, so the FFT chunks run on two threads (`_FFT_WORKERS`, three chunks
  queued); each thread keeps its own plan and the chunks are taken in order,
  so every spectrum is the same. Measured on the 30-minute, 4-sensor drive on
  the Pi (5 interleaved rounds after a warm-up): the build step went from
  7.4 s to 5.7 s and the whole post-analysis from 28.2 s to 26.4 s, for
  2.1 s more CPU, peak RSS 128 MB to 134 MB and MemAvailable at least 225 MB
  throughout; on PC, pinned to 4 cores, the build went from 486 ms to
  380 ms. The analysis JSON is byte-identical.
- Of the FFT thread's ~9.4 s on the Pi (49 ms per 64-window chunk), the FFT
  itself (pyFFTW, float32) is ~1.8 s; the rest is elementwise passes (int16
  to g, mean, window, magnitude, the float64 combine). The combine squares
  the float32 magnitudes straight into float64 rather than widening them
  first (exact, one pass fewer): the replay went from 12.4 s to 11.8 s.
- Tried and not kept for the replay's FFT: FFTW_MEASURE plans (29 s to plan
  on the Pi, no faster than FFTW_ESTIMATE, not bit-identical), scipy.fft on
  float32 (14.7 ms per chunk against FFTW's 10.7 ms) and float64 FFTs (FFTW
  20.3 ms, scipy.fft 20.4 ms, numpy 17.8 ms; not bit-identical either).
- pyFFTW is imported on the first FFT without its scipy interfaces
  (`_import_pyfftw`): its package otherwise imports `scipy.fftpack` and
  `scipy.fft` (about 140 scipy modules, plus numpy.testing and unittest) only
  to offer drop-in scipy functions the server does not use. On the Pi the
  process with the analysis modules and pyFFTW loaded went from 56 MB to
  39 MB resident, the first FFT's import from 1.3 s to 0.04 s, and
  post-analysis peak RSS from 162 MB to 146 MB at the same time; the FFT
  outputs and the analysis JSON are bit-identical.
- Tried and not kept for the replay: each step's numpy calls on the FFT
  thread wait for the GIL while the worker thread runs Python (5 ms switch
  interval), so fewer, larger calls are what helped; 32 windows per FFT
  chunk were 2 s slower on the Pi than 64 and save only ~2 MB, and 128
  gained nothing for more memory. A second FFT thread saved 0.4 s for +9 MB
  and 2 s more CPU while the strengths' per-window objects were the longer
  part (kept once they became columns, above); one chunk queued instead of two cost 2 s; strengths on
  worker threads were slower (GIL); a fancy-index gather of each window was
  3.7 s on the Pi, and a `sliding_window_view` of a sensor's whole buffer is
  refused on the Pi's 32-bit numpy. The strength batch size does not change
  peak memory, nor does reusing one block buffer. Raising
  `sys.setswitchinterval` would hit the live server too. Equal peak
  candidates rank the higher bin first; the per-row `argsort` this replaced
  left their order to the platform's sort (it differed between AVX-512 and
  scalar builds). Taking each peak's rank in one array step instead of the
  greedy separation loop was slower on PC.
- Order matching tests each hypothesis (about ten) against every window. What
  every hypothesis reads of a window the same way (its sensor, speed bin,
  driving phase, floor, cell, speed and time) is worked out once per drive
  (`drive_facts`), as is each rotation's reference frequency by sample
  (`reference_columns`); each hypothesis then places its frequencies and
  finds every window's nearest ranked peak in one array operation
  (`PeakTable`), plans its line reads as arrays and files them by cell
  (`_line_reads`), and judges each sensor's reads once (`TrackedCells` keeps
  its judges until a new read comes in). Measured on a 30-minute, 4-sensor
  drive on the Pi: the analyze step went from 60 s to 42 s, the whole
  post-analysis from 112 s to 96 s, peak RSS +3 MB; the analysis JSON is
  byte-identical on that drive, the CI-seed accuracy benchmark and the
  diagnostic matrix. The line reads gather straight from the replay's
  spectra where it keeps them as rows of one array (`WindowSpectrum.rows`).
- Each hypothesis then keeps its windows as columns (`_Windows`: predicted
  and matched frequency, sensor, speed bin, phase, floor, amplitude), judges
  their tracking in array operations, and counts the possible and matched
  windows per sensor, speed bin and phase by code; only the matched windows
  it keeps become `OrderMatchObservation`s, built once each. The wheel's
  harmonic comb (`_wheel_harmonic_peaks`) reads only which peaks each
  harmonic matched (`matched_peaks_for_hypothesis`), not the whole match.
  The spectra's grouping by shared rows array is worked out once per drive
  (`spectra_by_rows`) rather than per hypothesis, a sample's location label
  is remembered, and
  the peak findings check a frequency bin against the orders' frequencies
  by bisection rather than against every one. Measured on a 30-minute,
  4-sensor drive on the Pi: the analyze step went from 29.8 s to 21.2 s
  (order matching from 17.7 s to 10.5 s), the whole post-analysis from
  48 s to 40 s, peak RSS unchanged (162 MB); the analysis JSON is
  byte-identical on that drive, the CI-seed accuracy benchmark and the
  diagnostic matrix.
- The analysis reads the drive as columns (`DriveTable`, "Drive table" in
  `docs/analysis_pipeline.md`): the noise baseline, engine reference, order
  session, peak bins, peak table and diagnosis read one array per field and
  the analysed peaks as one flat table, built once, instead of re-deriving
  each sample's peaks, floor, speed bin and label stage by stage. A run's
  peaks are columns (`SamplePeaks`) from the start: the raw replay rebuilds
  a sample's strength fields in place and gathers its peaks straight into
  them, rather than building a `StrengthPeak` tuple and a new `SensorFrame`
  per window, and the loader decodes the kept rows without their peaks and
  reads the stored peaks, straight into columns, only for the samples the
  replay does not rebuild (none on a drive with raw capture). Measured on
  the x86 dev host (30-minute, 4-sensor drive, `OPENBLAS_NUM_THREADS=1`,
  medians of 7 interleaved runs): the whole post-analysis from 2.32 s to
  1.85 s (load 293 to 238 ms, replay 657 to 531 ms, analyze 1273 to 996 ms),
  peak RSS from 196.5 to 178.4 MB; the same drive without its raw capture
  from 1.24 s to 0.95 s, peak RSS from 151.5 to 141.5 MB. The analysis JSON
  is byte-identical on that drive (also with all or half of its raw capture
  removed), the CI-seed accuracy benchmark and the diagnostic matrix. Pi
  timing to be measured after merge.
- The samples are columns too (`SampleColumns`, "Sample columns" in
  `docs/analysis_pipeline.md`): the loader selects and decodes only the 22
  fields the analysis reads, a column per batch, rather than a 30-field
  `SensorFrame` per sample; the stages that walk the samples group them with
  NumPy, and the raw replay groups its requests per sensor and writes the
  rebuilt strengths as column slices. Measured on the x86 dev host (same
  drive, 22 interleaved rounds pinned to 4 cores, two FFT threads): the
  whole post-analysis from 1.87 s to 1.74 s (load 258 to 247 ms, replay 412
  to 388 ms, analyze 1073 to 994 ms), peak RSS from 174 to 168 MB and the
  memray peak from 126 MB to 117 MB; without the raw capture (26 rounds)
  from 1.05 s to 0.97 s, peak RSS from 135 to 130 MB, memray peak from 90
  to 78 MB. The analysis JSON is byte-identical on that drive (with all,
  none, half the sensors' or half the time's raw capture), the CI-seed
  accuracy benchmark and the diagnostic matrix. Pi timing to be measured
  after merge.
- Order matching stays on columns to the finding (`MatchedWindows`, "Order
  matches as columns" in `docs/analysis_pipeline.md`): a hypothesis's
  matched windows, their heard subset, the line's placement and the windows
  off it, the wheel's harmonic comb, the tracking slope, the speed, phase
  and amplitude evidence and the location scoring per speed bin read one
  array per field, and the tracked cells' reads, medians and scatter are
  arrays too (`CellReads`, `TrackedCells`). Only a finding's matches become
  `OrderMatchObservation`s, with their sample's time and speed shared from
  the drive's values: a new float per finding kept the analysis 0.7 MB
  larger until the summary was stored. The location modules import
  `MatchedWindows` for typing only, so the order modules still load with
  the first analysis rather than at server start. Measured on the x86 dev
  host (same drive, 11 interleaved rounds pinned to 4 cores,
  `OPENBLAS_NUM_THREADS=1`): the whole post-analysis from 1.67 s to 1.32 s
  (analyze 944 to 619 ms; load, replay and store unchanged), peak RSS 168.9
  to 168.1 MB, memray peak 116.8 to 116.6 MB; without the raw capture from
  0.93 s to 0.82 s (analyze 522 to 417 ms), peak RSS 130.0 to 129.0 MB,
  memray peak 79.0 to 75.9 MB. The analysis JSON is byte-identical on that
  drive (with all, none, half the sensors' or half the time's raw capture),
  the CI-seed accuracy benchmark and the diagnostic matrix. Pi timing to be
  measured after merge.
- Tried and not kept for order matching: a pool of 3 forked processes, one
  hypothesis each, saved 21 s on the Pi but each child dirtied 30-45 MB of
  the parent's pages through reference counts (86-135 MB in all), leaving 54-100
  MB available while the live server runs, and forking a threaded server is
  fragile; a thread pool gains nothing, as the matching is Python bound under
  the GIL. Algorithmic cuts to the replay's FFT (decimation, a zoom FFT or
  Goertzel at the order lines) are capped by the FFT's small share once it
  is batched (about 3-4 s of the Pi's total), well under the 15 % a change
  to the analysis must earn.
- Loading the run and storing its analysis are I/O and decode work, cut
  without changing a byte of the stored analysis: sample rows are decoded a
  column per batch, with msgspec decoding each row's peaks JSON straight into
  `StrengthPeak` (the light selection pass decodes only the peak amplitudes);
  the summary is written with a msgspec encoder rather than first copied into
  plain Python values; and the ~7 MB summary is no longer deep-copied when it
  is built, stored or read back. On the Pi this took the load from ~13.7 s to
  ~4.5 s, the summary + store steps from ~8.9 s to ~2.5 s and the whole
  post-analysis from 97 s to 79 s, peak memory 5 MB lower. What did not
  help: decoding every row's peaks as one JSON array (slower than per row),
  and decoding into a msgspec `Struct` then converting (2× slower than
  decoding into the dataclass).
- History reads of a run with a long drive's analysis (~7 MB) were dominated
  by copying it: the run-detail projection deep-copied the stored analysis
  before rebuilding its findings. The projections now build new objects only
  for what they change, stored JSON is read with msgspec (stdlib `json` still
  reads non-standard numbers and reports malformed text), and stored matched
  points of plain floats and strings become domain observations without
  per-field coercion. Responses are byte-identical; on the Pi (`nice -n 10`,
  30-minute drive) the run detail went from 5.4 s to 2.7 s, insights from
  4.5 s to 3.5 s, the run list from 1.07 s to 0.43 s and the report PDF
  from 1.5 s to 0.95 s (0.35 s once cached). Most of what is left is rebuilding the ~24,000
  matched points as domain objects and validating and writing the response.
- The UDP ingest path is single-threaded: it is I/O-bound, very fast (buffer
  append under a brief lock), and the bounded async queue provides backpressure
  with explicit drop logging.

### Post-analysis cost (30-minute drive, 4 sensors, `FFT_N=2048`)

| Host | CPU time | Peak RSS |
|------|----------|----------|
| x86 dev host | ~2.1 s | ~168 MB |
| Raspberry Pi 3 A+ (`nice -n 10`) | ~39 s (before the drive table) | ~146 MB |

The x86 row is the post-analysis's own CPU time (load to store, `OPENBLAS_NUM_THREADS=1`).

### 64-bit, numba and free-threading (measured, not kept)

Measured on the Pi 3 A+ on 2026-10-10, re-analysing the same 30-minute,
4-sensor drive (`nice -n 10`, server idle, MemAvailable sampled every second,
headless boot config on both images). None of these is kept: none is clearly
faster, and all of them cost the memory that capture needs.

| Variant | Post-analysis | Peak RSS | Min MemAvailable | Output |
|---------|---------------|----------|------------------|--------|
| armhf (32-bit), Python 3.13 (shipped) | 37.5-37.7 s | 162 MB | 213-218 MB | reference |
| arm64 (64-bit), Python 3.13 | 36.8-39.5 s | 207-216 MB | 122-139 MB | identical |
| arm64, Python 3.14 (GIL) | 38.0-40.6 s | 208-217 MB | 114-123 MB | identical |
| arm64, numba 0.68, one kernel, cache warm | 41.8-42.2 s | 262-274 MB | 90-103 MB | identical |
| arm64, numba, first run (compiles) | 51.8 s | 269 MB | 91 MB | identical |
| arm64, free-threaded 3.14t, 1 thread | 39.0-40.8 s | 238-243 MB | 85-93 MB | float-level diffs, same verdicts |
| arm64, free-threaded 3.14t, 2 threads | 35.4-36.6 s | 260-263 MB | 60-61 MB | as 1 thread |
| arm64, free-threaded 3.14t, 4 threads | 39.7 s | 267 MB | 31 MB (swapping) | as 1 thread |

- 64-bit gives no speed: the remaining cost is interpreter work (small
  objects, dict lookups, calls), not wide numeric kernels, and every Python
  object is larger, so it only costs ~50 MB peak and ~80 MB headroom.
- numba (aarch64 wheels only; none for armv7l) costs ~72 MB to import and
  ~28 MB more once LLVM loads, 6.2-6.6 s to load cached kernels per process
  and ~15 s to compile them the first time. The compiled order-matching line
  reads went from 1.5 s to 0.4 s, far less than those fixed costs, and much of
  what remains (building per-window Python objects) cannot be compiled.
- Free-threaded 3.14t (aarch64 wheels for numpy/scipy/msgspec; none for
  pyFFTW, replaced by scipy.fft float32 for the test) costs ~25-30 MB on one
  thread; order matching per hypothesis and the replay's strength batches on
  a pool scale poorly (2 threads save ~3 s for ~50 MB, 4 threads swap).
- The prototype code and timing scripts are kept on the unmerged branch
  `exp64-jit` (`VS_EXP_NUMBA=1`, `VS_EXP_THREADS=N`, `tools/exp64/`).
- The headless boot config (`gpu_mem=16`, no `vc4-kms-v3d`) that both images
  use raised Linux-visible RAM from ~425 MB to ~473 MB and the post-analysis
  minimum MemAvailable on armhf from 176-177 MB to 213-218 MB, at the same
  speed.

## Benchmarks

```bash
make benchmark-backend BENCHMARK_OPTS="--benchmark-save=baseline"
make benchmark-compare-backend
```

`make benchmark-backend` uses the default backend benchmark target list defined in
the repository `Makefile`. Override `BACKEND_BENCHMARK_TARGETS` only for ad hoc
single-file runs so the documented default cannot drift from the Makefile.
