# Examples

Sample run data in [schema v2](../docs/run_schema_v2.md) JSONL format for
testing report generation without recording a live session.

## Generate a PDF Report

```bash
vibesensor-report examples/sample_complete_run.jsonl --output examples/sample_complete_run_report.pdf
```

With summary JSON:

```bash
vibesensor-report examples/sample_complete_run.jsonl \
  --output examples/sample_complete_run_report.pdf \
  --summary-json examples/sample_complete_run_summary.json
```

## Schema

Each JSONL file contains:

1. `run_metadata` record (first line) — sensor model, sample rate, FFT config
2. `sample` records — time series with acceleration, speed, FFT peaks
3. Optional `run_end` record

See [docs/run_schema_v2.md](../docs/run_schema_v2.md) for the full field reference.
