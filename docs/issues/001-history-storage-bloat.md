# [Non-security] History storage uses row-per-sample JSON in SQLite, causing predictable bloat and slowdown

**Labels:** performance, backend, maintainability

## Summary

History storage persists every `SensorFrame` as a separate SQLite row containing
the full JSON serialisation of ~30 fields (including nested peak arrays). At
default settings (4 Hz × 4 sensors) a single 30-minute drive produces ~28 800
rows / ~42 MB of JSON text. Over 50 drives the database grows to ~2 GB of
uncompressed text, with no archival, compression, or pruning mechanism.

## Evidence

| File | Symbol / Line | Observation |
|---|---|---|
| `apps/server/vibesensor/history_db.py` | `_SCHEMA_SQL` L51-56 | `samples` table: one row per sample, `sample_json TEXT NOT NULL` |
| `apps/server/vibesensor/history_db.py` | `append_samples()` L186-207 | Inserts one row per `SensorFrame`, serialised via `_safe_json_dumps()` |
| `apps/server/vibesensor/domain_models.py` | `SensorFrame.to_dict()` L437-470 | ~30 fields including `top_peaks` (8 entries), `top_peaks_{x,y,z}` (3 each) |
| `apps/server/vibesensor/config.py` | `metrics_log_hz` L63 | Default = 4 samples/sec/sensor |
| `apps/server/vibesensor/history_db.py` | `iter_run_samples()` L403-442 | Reads back samples via per-row `json.loads()` |
| `apps/server/vibesensor/history_db.py` | `_SCHEMA_VERSION = 4` L27 | No migration path; schema must be exactly v4 |

### Storage growth estimate

| Scenario | Rows | JSON text | SQLite (est.) |
|---|---|---|---|
| 10-min drive (4 sensors @ 4 Hz) | 9 600 | ~14 MB | ~20 MB |
| 30-min drive (4 sensors @ 4 Hz) | 28 800 | ~42 MB | ~59 MB |
| 50 × 30-min drives | 1 440 000 | ~2.1 GB | ~2.9 GB |

Each sample JSON is ~1.5 KB (measured by serialising a realistic `SensorFrame`).
SQLite overhead adds ~40 % on top (row headers, index, WAL).

### Read-path cost

`iter_run_samples()` deserialises every row individually via `json.loads()`.
For 28 800 rows this is ~28 800 `json.loads()` calls, each parsing ~1.5 KB.
`get_run_samples()` (L397-401) materialises all batches into a single list,
holding all parsed dicts in memory simultaneously.

## Impact

- On Raspberry Pi 3A+ (target hardware, limited RAM/storage), a moderately
  active user will exhaust SD card space or experience sluggish UI within
  weeks of regular use.
- Analysis re-runs (`summarize_run_data`) must deserialise the full JSON
  sample set, adding latency proportional to run length.

## Suggested direction

- Store samples in a columnar or binary format (e.g. per-run `.npy` sidecar,
  MessagePack, or SQLite columns for the scalar fields with a separate blob
  for peaks).
- Add a retention/pruning policy (e.g. keep last N runs, or auto-archive
  raw samples after analysis is complete).
- Consider compressing `sample_json` with zlib before INSERT if the row-per-
  sample model is retained.
