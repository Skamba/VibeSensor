# History DB Schema (v15)

The VibeSensor server stores run history, samples, analysis results,
application settings and client names in a single SQLite file located at
`~/.vibesensor/history.db` (or the path specified by `--data-dir`).

## Design goals

| Goal | Approach |
|------|----------|
| Low overhead on Raspberry Pi 3A+ | WAL journal mode, batched inserts (256 rows), typed columns (no per-row JSON parsing) |
| Efficient long recordings | Keyset pagination (`id > ?`), streaming iterator, no full-run memory load |
| Queryable time-series | Typed columns for accel, speed, frequency, strength; indexed by `(run_id, t_s)` |

## Module organization

`adapters/persistence/history_db/` now builds a shared SQLite engine plus narrow
repositories over the same database file:

- `_engine.py`: shared SQLite connection/lock/cursor ownership, schema
  initialization, incompatible-schema backup/export protection, and
  corruption detection.
- `_run_repository.py`: run persistence composed from `_run_lifecycle.py`,
  `_sample_io.py`, and `_queries.py` over the shared engine.
- `_settings_repository.py`: `settings_snapshot` table persistence only.
- `_client_names_repository.py`: `client_names` table persistence only.
- `__init__.py`: adapter bundle factory plus a temporary `HistoryDB`
  compatibility facade for tests/legacy call sites.
- `_run_lifecycle.py`: run creation/finalization, sample appends, analysis writes, delete
  flows, stale-recording recovery, and startup retention pruning for old terminal runs.
- `_sample_io.py`: batched sample reads and keyset-pagination helpers.
- `_queries.py`: run listing/detail queries, metadata reads, health reads, and integrity
  checks.
- `_samples.py`: row-serialization helpers for `samples_v2`.
- `_schema.py`: schema DDL and `SCHEMA_VERSION`.

## Tables

### `runs`

One row per recording session.

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | TEXT PK | UUID for the run |
| `case_id` | TEXT | Diagnostic case this run belongs to |
| `status` | TEXT | `recording` → `analyzing` → `complete` (or `error`). CHECK constraint enforces valid values. Transitions are enforced atomically via WHERE guards. |
| `start_time_utc` | TEXT | ISO-8601 start time |
| `end_time_utc` | TEXT | ISO-8601 end time (set on finalize) |
| `metadata_json` | TEXT | Run-level metadata (car config, language, sensor model, etc.) |
| `car_name` | TEXT | Denormalized active car name used by the history list path |
| `raw_capture_manifest_json` | TEXT | Raw waveform sidecar manifest; may remain after raw files are pruned so history can report missing raw capture explicitly |
| `whole_run_artifact_manifest_json` | TEXT | Whole-run sidecar manifest for dense post-analysis artifacts |
| `analysis_json` | TEXT | Post-run analysis summary |
| `error_message` | TEXT | Error description when status = `error` |
| `sample_count` | INTEGER | Running count of appended samples |
| `created_at` | TEXT | Row creation timestamp |
| `analysis_started_at` | TEXT | When analysis started |
| `analysis_completed_at` | TEXT | When analysis finished |

### `samples_v2`

One row per sensor frame — **no JSON blobs**. All `SensorFrame` scalar fields
are stored as typed columns; peak arrays use compact JSON in a TEXT column and
are rehydrated back into typed `SensorFrame.top_peaks` data on read.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment row ID |
| `run_id` | TEXT FK | References `runs(run_id)` with `ON DELETE CASCADE` |
| `timestamp_utc` | TEXT | ISO-8601 sample time |
| `t_s` | REAL | Seconds since run start (monotonic) |
| `analysis_window_start_us` | INTEGER | Optional raw-analysis window start timestamp in run-monotonic microseconds |
| `analysis_window_end_us` | INTEGER | Optional raw-analysis window end timestamp in run-monotonic microseconds |
| `analysis_window_synced` | INTEGER | Optional boolean flag (`0`/`1`) indicating whether the analysis window is synchronized to raw capture timing |
| `client_id` | TEXT | Sensor MAC address (hex) |
| `client_name` | TEXT | Human-readable sensor name |
| `location` | TEXT | Mounting position (e.g. `front_left`) |
| `sample_rate_hz` | INTEGER | Raw ADC sample rate |
| `speed_kmh` | REAL | Effective vehicle speed |
| `gps_speed_kmh` | REAL | GPS-derived speed |
| `speed_source` | TEXT | `gps`, `obd2`, or `manual` |
| `engine_rpm` | REAL | Engine RPM |
| `engine_rpm_source` | TEXT | Source of RPM data |
| `gear` | REAL | Current gear |
| `final_drive_ratio` | REAL | Final drive ratio |
| `accel_x_g` | REAL | X-axis acceleration (g) |
| `accel_y_g` | REAL | Y-axis acceleration (g) |
| `accel_z_g` | REAL | Z-axis acceleration (g) |
| `dominant_freq_hz` | REAL | Dominant vibration frequency |
| `dominant_axis` | TEXT | Real dominant axis (`x`/`y`/`z`) when one axis clearly owns the strongest peak, `combined` when the strongest peak is non-directional across axes, empty when unavailable |
| `vibration_strength_db` | REAL | Vibration strength in dB |
| `strength_bucket` | TEXT | Strength classification label |
| `strength_peak_amp_g` | REAL | Peak amplitude (g) |
| `strength_floor_amp_g` | REAL | Noise floor amplitude (g) |
| `frames_dropped_total` | INTEGER | Cumulative dropped frames |
| `queue_overflow_drops` | INTEGER | Queue overflow drop count |
| `top_peaks` | TEXT | JSON array of combined top peaks |

**Indexes:**
- `idx_samples_v2_run_id` on `(run_id)` — fast lookup by run
- `idx_samples_v2_run_time` on `(run_id, t_s)` — time-range queries

### `settings_snapshot`

Single-row table for persistent application settings.

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Always 1 (CHECK constraint) |
| `value_json` | TEXT | JSON-encoded settings snapshot |
| `updated_at` | TEXT | Last update timestamp |

### `client_names`

Legacy compatibility table for sensor client display names.

Canonical user-managed sensor metadata now lives in the `settings_snapshot`
payload (`sensorsByMac`). The runtime registry may still read `client_names`
for older/offline compatibility paths, but it is no longer the authoritative
home for persisted sensor name/location semantics.

| Column | Type | Description |
|--------|------|-------------|
| `client_id` | TEXT PK | Sensor MAC (hex) |
| `name` | TEXT | Legacy display name |
| `updated_at` | TEXT | Last update timestamp |

## Schema version policy

Schema versioning uses SQLite's `PRAGMA user_version`. The current schema is the
only supported runtime schema. On startup the shared SQLite history engine checks
the stored integer version:

| Stored version | Action |
|----------------|--------|
| `0` on a fresh DB with no user tables | Create all tables, stamp `user_version = 15` |
| `0` with a legacy `schema_meta` table present | Back up the DB, attempt a best-effort run-summary export, then raise `RuntimeError` without requiring destructive deletion |
| `0` with unexpected user tables | Back up the DB, attempt a best-effort run-summary export, then raise `RuntimeError` |
| `15` | No action needed beyond ensuring current tables/indexes exist |
| Any older value, including `11`-`14` | Back up the DB, attempt a best-effort run-summary export, then raise `RuntimeError` |
| Newer than `15` | Back up the DB, attempt a best-effort run-summary export, then raise `RuntimeError` (downgrade not supported) |

There are no in-place migrations from older history DB versions. Before
rejecting a populated non-current database, the engine writes a backup copy under
`history-db-backups/` next to the live database and, when a readable `runs` table
exists, exports a best-effort JSONL summary of stored runs. The server then
raises a clear error; reset or reinstall to create a fresh current-schema DB.

## Performance settings

| Setting | Value | Rationale |
|---------|-------|-----------|
| `journal_mode` | WAL | Allows concurrent reads during writes |
| `wal_autocheckpoint` | 500 | Prevents unbounded WAL growth |
| `foreign_keys` | ON | Cascade deletes for samples when a run is deleted |
| Batch insert size | 256 | Balances transaction overhead vs. memory usage |
| Read batch size | 1000 (default) | Keyset pagination for streaming reads |

## Historical storage comparison (approximate)

This comparison records why the schema moved from older opaque sample JSON blobs
to typed `samples_v2` columns. It is historical design context, not current
guidance for choosing a storage version; current databases use schema v15.

For a 30-minute run at 4 Hz × 4 sensors (~28,800 samples):

| Metric | v4 (JSON blobs) | v5 (structured) |
|--------|-----------------|-----------------|
| Storage | ~42 MB | ~15 MB |
| Write speed | Slower (JSON serialize per row) | Faster (typed bind params) |
| Read speed | Slower (JSON parse per row) | Faster (direct column access) |
| Queryable | No (opaque blobs) | Yes (indexed typed columns) |

## Startup retention policy

On startup, the container builds the shared history engine and run repository,
first recovers stale `recording` rows into `error`, then applies retention in
two stages:

1. If `logging.raw_capture_retention_days` is lower than
   `logging.run_retention_days`, raw waveform sidecars older than the raw-capture
   cutoff are pruned first while the run summary row stays in the DB.
2. `complete` and `error` runs older than `logging.run_retention_days` (default
   `7`) are deleted entirely.

Both cutoffs use the run's terminal timestamp (`analysis_completed_at`, then
`end_time_utc`, then `created_at`) so active `recording` / `analyzing` runs are
never deleted by the automatic policy. Full run deletion still removes sample
rows through the existing `ON DELETE CASCADE` foreign key on `samples_v2`, plus
raw/whole-run sidecar directories.

## Dense whole-run sidecars

Dense post-run arrays stay outside SQLite under
`whole-run-artifacts/<run_id>/`. The `runs.whole_run_artifact_manifest_json`
column stores only a compact manifest: schema/storage versions, input `run_id`,
window policy, algorithm versions, source raw-capture manifest summaries,
configuration, generated artifact paths, and per-artifact record counts/formats.
The same manifest is also written to `whole-run-artifacts/<run_id>/manifest.json`.

`analysis_json.analysis_metadata` keeps the query-friendly run summary:
availability/status, manifest path, generated timestamp, algorithm versions,
configuration, artifact count/keys/paths/formats, window/sensor counts, warning
codes, and compact top findings/summaries. Dense spectra use `.npy` float32
sidecars; window labels, order traces, summary rows, and spatial coherence rows
use JSONL sidecars. History reads treat missing artifact files as `missing` and
ignore corrupt manifest JSON instead of failing the whole run detail/list path.
