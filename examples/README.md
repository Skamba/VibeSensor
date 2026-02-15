# Examples

This folder contains schema-v2 sample input for deterministic report generation.

Generate a PDF report from the sample run:

```bash
vibesensor-report examples/sample_complete_run.jsonl --output examples/sample_complete_run_report.pdf
```

Optional summary JSON:

```bash
vibesensor-report examples/sample_complete_run.jsonl \
  --output examples/sample_complete_run_report.pdf \
  --summary-json examples/sample_complete_run_summary.json
```
