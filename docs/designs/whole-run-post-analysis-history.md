# Whole-run post-analysis history and execution notes

> **Status:** Historical
> **Use:** Historical record only. Do not treat this file as current
> implementation guidance. Current architecture and constraints live in
> `docs/designs/whole-run-post-analysis-program.md`.

This file preserves old planning context, benchmark snapshots, and branch notes
that are useful for archaeology but should not steer new implementation work.

## Original scope record

The original execution design covered parent issues #3075, #3076, #3077, #3078,
and #3079, using the completed raw-capture work from #3065 as the foundation.

## Benchmark snapshot

Historical #3085 baseline:

- `benchmark_whole_run_spectra.py` used a 5-minute, 4-sensor, 800 Hz raw-capture
  fixture with `FFT_N=2048` and `feature_interval_s=1.0`.
- The validated `make benchmark-backend` sweep showed the executor fastest in
  sequential mode with `max_workers=1` and `chunk_window_count=32` (mean
  ~547 ms) versus slower 4-worker runs at chunk sizes 64 (~586 ms), 32
  (~622 ms), and 16 (~668 ms).
- The raw range-reader baseline for one full window sweep over one sensor was
  ~371 ms.

Treat these numbers as historical snapshots. Rerun explicit benchmarks on the
target hardware before changing current executor defaults.

## Planned sub-issue breakdown

### Parent #3075 -- whole-run engine

1. #3080 Define deterministic whole-run window contracts and artifact manifest
2. #3081 Add indexed raw-capture range reads for offline window analysis
3. #3082 Build the canonical whole-run window planner from run metadata
4. #3083 Add a file-backed whole-run analysis artifact store and manifest plumbing
5. #3084 Implement the raw-window spectral executor with deterministic chunk scheduling
   - Historical branch note: work landed locally on branch
     `issue-3084-spectral-executor` with deterministic chunk ordering, shared
     FFT primitive extraction into `vibesensor.shared.fft_analysis`, per-sensor
     `.npy` grid/matrix artifacts, per-window `.jsonl` summaries with explicit
     coverage states, and post-analysis manifest persistence plumbing.
6. #3085 Benchmark the whole-run engine on Pi-sized runs

### Parent #3076 -- phase segmentation and context timelines

1. #3086 Define whole-run context timeline and segment contracts
2. #3087 Normalize full-run speed and RPM context onto the window grid
3. #3088 Implement whole-run phase segmentation over normalized timelines
4. #3089 Persist segment timelines and per-window context labels
5. #3090 Surface context completeness and fallback signals to history and report consumers

### Parent #3077 -- order tracking and harmonic stability

1. #3091 Define whole-run order-trace and harmonic evidence contracts
2. #3092 Build per-candidate order traces from window spectra and context labels
3. #3093 Add harmonic stability and order-lock scoring across the full run
4. #3094 Summarize order traces by source family, phase, and support intervals
5. #3095 Persist ranked order-trace summaries and exemplars for downstream fusion

### Parent #3078 -- multi-sensor coherence and spatial evidence

1. #3096 Define multi-sensor coherence and spatial evidence contracts
2. #3097 Join aligned per-window sensor outputs with coverage and missing-data rules
3. #3098 Implement candidate-level coherence and cross-sensor agreement metrics
4. #3099 Implement spatial separation and supporting-window hotspot summaries
5. #3100 Persist spatial evidence and proof-basis summaries for downstream fusion

### Parent #3079 -- fusion, counterevidence, and diagnosis ranking

1. #3101 Define persisted whole-run evidence fusion and diagnosis summary contracts
2. #3102 Model support factors and counterevidence factors with stable keys
3. #3103 Implement the diagnosis ranker over context, order, and spatial evidence
4. #3104 Add summary-only and partial-artifact fallback scoring for legacy runs
5. #3105 Expose fused diagnosis evidence through history and report preparation and PDF surfaces
6. #3106 Add cross-scenario regression coverage for clear, mixed, and ambiguous whole-run diagnoses
